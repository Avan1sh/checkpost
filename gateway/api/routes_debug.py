"""Demo-only endpoints, mounted ONLY in mock mode (never with real Razorpay keys).

They exist so the demo buyer can drive the simulator over HTTP:
- arm a fault before its next request (timeouts, errors),
- simulate the customer paying, receiving back a *signed* webhook payload that it must
  deliver to /webhooks/razorpay itself — so signature verification, dedup, and
  out-of-order handling run exactly as they would with real Razorpay traffic.
"""
import hashlib
import hmac
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gateway.core.config import get_settings
from gateway.core.db import get_session
from gateway.domain.models import Proposal
from gateway.payments.client import MockRazorpay, get_client

router = APIRouter(prefix="/debug", tags=["debug (mock mode only)"])


def _mock() -> MockRazorpay:
    client = get_client()
    if not isinstance(client, MockRazorpay):
        raise HTTPException(400, "debug endpoints only work in mock mode")
    return client


class FaultIn(BaseModel):
    fault: str  # timeout_after_create | timeout_before_create | error | fetch_timeout


@router.post("/arm-fault")
def arm_fault(body: FaultIn):
    _mock().arm_fault(body.fault)
    return {"armed": body.fault}


def _signed(event: str, payload: dict) -> dict:
    body = json.dumps({"event": event, "payload": payload}).encode()
    signature = hmac.new(get_settings().razorpay_webhook_secret.encode(),
                         body, hashlib.sha256).hexdigest()
    return {
        "deliver_to": "/webhooks/razorpay",
        "body": body.decode(),
        "headers": {
            "X-Razorpay-Signature": signature,
            "X-Razorpay-Event-Id": f"evt_{uuid.uuid4().hex[:16]}",
            "Content-Type": "application/json",
        },
    }


class SimulatePaymentIn(BaseModel):
    proposal_id: str


@router.post("/simulate-payment")
def simulate_payment(body: SimulatePaymentIn, session: Session = Depends(get_session)):
    mock = _mock()
    proposal = session.get(Proposal, body.proposal_id)
    if proposal is None:
        raise HTTPException(404, "proposal not found")

    if proposal.payment_link_id and not proposal.razorpay_order_id:
        order_id, _payment = mock.simulate_link_payment(proposal.payment_link_id)
        return _signed("payment_link.paid", {
            "payment_link": {"entity": {"id": proposal.payment_link_id,
                                        "order_id": order_id, "status": "paid"}}})
    if proposal.razorpay_order_id:
        payment = mock.simulate_payment(proposal.razorpay_order_id)
        return _signed("payment.captured", {
            "payment": {"entity": {"id": payment.payment_id,
                                   "order_id": proposal.razorpay_order_id,
                                   "status": "captured"}}})
    raise HTTPException(409, f"proposal in state {proposal.state} has nothing to pay")
