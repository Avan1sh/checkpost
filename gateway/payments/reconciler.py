"""The reconciler: owns every UNCERTAIN proposal. Verify, then act — never blind retry.

Resolution order for a proposal parked in UNCERTAIN:
1. If we hold no order id, ask Razorpay whether an order exists for our receipt
   (the lost-response case). Found -> adopt it. Not found -> safe to create one.
2. If we hold (or just adopted) an order id, fetch its payments:
   captured -> PAID. none yet -> back to AWAITING_PAYMENT with the same order.
3. Any step that times out again returns the proposal to UNCERTAIN with an attempt
   recorded; attempts are bounded, exhaustion -> FAILED + merchant alert. Nothing silent.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.audit.events import emit
from gateway.core.config import get_settings
from gateway.domain.models import Proposal
from gateway.domain.state_machine import transition
from gateway.domain.states import ProposalState
from gateway.payments.client import PaymentsError, PaymentsTimeout, RazorpayClient
from gateway.payments.orders import ensure_order, verify_and_apply_payment


def reconcile_proposal(session: Session, client: RazorpayClient, proposal: Proposal) -> ProposalState:
    settings = get_settings()
    proposal.reconcile_attempts += 1
    transition(session, proposal, ProposalState.RECONCILING, actor="reconciler",
               cause=f"reconciliation attempt {proposal.reconcile_attempts}")
    try:
        if not proposal.razorpay_order_id:
            existing = client.fetch_order_by_receipt(proposal.id)
            if existing is not None:
                proposal.razorpay_order_id = existing.order_id
                emit(session, actor="reconciler", action="order.adopted", proposal=proposal,
                     detail={"order_id": existing.order_id,
                             "reason": "order found for receipt after ambiguous outcome"})
            else:
                # Ground truth says nothing was created — safe to create now, via the same
                # idempotent choke point (which re-checks the receipt before creating).
                emit(session, actor="reconciler", action="order.recreating", proposal=proposal,
                     detail={"reason": "verified no order exists for receipt"})
                return ProposalState(ensure_order(session, client, proposal).state)

        if verify_and_apply_payment(session, client, proposal):
            return ProposalState(proposal.state)

        if ProposalState(proposal.state) == ProposalState.RECONCILING:
            transition(session, proposal, ProposalState.AWAITING_PAYMENT, actor="reconciler",
                       cause="order verified, no payment captured yet",
                       evidence={"order_id": proposal.razorpay_order_id})
        return ProposalState(proposal.state)

    except PaymentsTimeout as exc:
        if proposal.reconcile_attempts >= settings.reconciler_max_attempts:
            transition(session, proposal, ProposalState.FAILED, actor="reconciler",
                       cause="reconciliation attempts exhausted; merchant alerted",
                       evidence={"attempts": proposal.reconcile_attempts, "error": str(exc)})
        else:
            transition(session, proposal, ProposalState.UNCERTAIN, actor="reconciler",
                       cause="still ambiguous; will retry with backoff",
                       evidence={"attempts": proposal.reconcile_attempts, "error": str(exc)})
        return ProposalState(proposal.state)
    except PaymentsError as exc:
        transition(session, proposal, ProposalState.FAILED, actor="reconciler",
                   cause="definitive API error during reconciliation",
                   evidence={"error": str(exc)})
        return ProposalState(proposal.state)


def reconcile_pending(session: Session, client: RazorpayClient) -> int:
    """One sweep over everything parked in UNCERTAIN. Returns number processed."""
    rows = session.scalars(
        select(Proposal).where(Proposal.state == ProposalState.UNCERTAIN.value)
    ).all()
    for proposal in rows:
        reconcile_proposal(session, client, proposal)
    return len(rows)
