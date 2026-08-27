"""Razorpay webhook receiver: signature-verified, deduplicated, order-tolerant.

Webhooks are treated as *triggers*, never as truth: on a payment event we fetch the
order's payments from Razorpay and act on what the API says (docs recommend exactly this).
"""
import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.audit.events import emit
from gateway.core.config import get_settings
from gateway.core.db import get_session
from gateway.domain.models import Proposal, WebhookEvent
from gateway.domain.states import ProposalState
from gateway.payments.client import PaymentsTimeout, get_client
from gateway.payments.orders import verify_and_apply_payment

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(body: bytes, signature: str) -> bool:
    secret = get_settings().razorpay_webhook_secret.encode()
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    session: Session = Depends(get_session),
    x_razorpay_signature: str = Header(default=""),
    x_razorpay_event_id: str = Header(default=""),
):
    body = await request.body()
    if not _verify_signature(body, x_razorpay_signature):
        emit(session, actor="webhooks", action="webhook.bad_signature",
             detail={"event_id": x_razorpay_event_id})
        raise HTTPException(400, "invalid signature")
    if not x_razorpay_event_id:
        raise HTTPException(400, "missing x-razorpay-event-id")

    payload = json.loads(body)
    event_type = payload.get("event", "")

    # Dedupe: duplicate delivery is documented Razorpay behaviour. Ack and drop replays.
    existing = session.get(WebhookEvent, x_razorpay_event_id)
    if existing is not None:
        existing.duplicate_count += 1
        emit(session, actor="webhooks", action="webhook.duplicate_dropped",
             detail={"event_id": x_razorpay_event_id, "event": event_type,
                     "duplicate_count": existing.duplicate_count})
        return {"status": "duplicate_ignored"}
    session.add(WebhookEvent(event_id=x_razorpay_event_id, event_type=event_type, payload=payload))
    emit(session, actor="webhooks", action="webhook.received",
         detail={"event_id": x_razorpay_event_id, "event": event_type})

    proposal = _locate_proposal(session, event_type, payload)
    if proposal is None:
        return {"status": "no_matching_proposal"}

    if event_type in ("payment.captured", "order.paid", "payment_link.paid"):
        try:
            verify_and_apply_payment(session, get_client(), proposal)
        except PaymentsTimeout as exc:
            # Verification itself is ambiguous -> park for the reconciler, don't guess.
            if ProposalState(proposal.state) == ProposalState.AWAITING_PAYMENT:
                from gateway.domain.state_machine import transition
                transition(session, proposal, ProposalState.UNCERTAIN, actor="webhooks",
                           cause="payment verification timed out after webhook",
                           evidence={"error": str(exc)})
    elif event_type == "payment.failed":
        current = ProposalState(proposal.state)
        if current in (ProposalState.PAID, ProposalState.FULFILLED, ProposalState.REFUNDED):
            # Out-of-order delivery: never regress a settled state; record the conflict.
            emit(session, actor="webhooks", action="webhook.out_of_order_ignored",
                 proposal=proposal,
                 detail={"event": event_type, "current_state": current.value})
        else:
            emit(session, actor="webhooks", action="payment.attempt_failed", proposal=proposal,
                 detail={"event_id": x_razorpay_event_id})

    session.get(WebhookEvent, x_razorpay_event_id).processed = True
    return {"status": "ok", "proposal_id": proposal.id, "state": proposal.state}


def _locate_proposal(session: Session, event_type: str, payload: dict) -> Proposal | None:
    entity = {}
    contains = payload.get("payload", {})
    if "payment" in contains:
        entity = contains["payment"].get("entity", {})
        order_id = entity.get("order_id", "")
        if order_id:
            return session.scalars(
                select(Proposal).where(Proposal.razorpay_order_id == order_id)).first()
    if "order" in contains:
        order_id = contains["order"].get("entity", {}).get("id", "")
        if order_id:
            return session.scalars(
                select(Proposal).where(Proposal.razorpay_order_id == order_id)).first()
    if "payment_link" in contains:
        entity = contains["payment_link"].get("entity", {})
        link_id = entity.get("id", "")
        proposal = session.scalars(
            select(Proposal).where(Proposal.payment_link_id == link_id)).first()
        if proposal is not None and not proposal.razorpay_order_id and entity.get("order_id"):
            proposal.razorpay_order_id = entity["order_id"]
        return proposal
    return None
