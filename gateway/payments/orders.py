"""Order creation and payment verification — the single choke point for money actions.

Invariant: at most one Razorpay order per proposal, ever. Enforced by
(a) the local record on the proposal row, and (b) check-before-create against
Razorpay using receipt = proposal id, so even a lost response cannot cause a duplicate.
"""
from sqlalchemy.orm import Session

from gateway.audit.events import emit
from gateway.domain.models import Mandate, Proposal
from gateway.domain.state_machine import transition
from gateway.domain.states import ProposalState
from gateway.payments.client import PaymentsError, PaymentsTimeout, RazorpayClient


def ensure_order(session: Session, client: RazorpayClient, proposal: Proposal) -> Proposal:
    """From AUTHORIZED (or RECONCILING): guarantee exactly one order exists, or park in UNCERTAIN."""
    if proposal.razorpay_order_id:
        return proposal

    notes = {"proposal_id": proposal.id, "agent_id": proposal.agent_id,
             "mandate_id": proposal.mandate_id, "gateway": "checkpost"}
    try:
        existing = client.fetch_order_by_receipt(proposal.id)
        if existing is not None:
            proposal.razorpay_order_id = existing.order_id
            emit(session, actor="payments", action="order.adopted", proposal=proposal,
                 detail={"order_id": existing.order_id,
                         "reason": "order already existed for this receipt (prior ambiguous outcome)"})
        else:
            order = client.create_order(
                receipt=proposal.id, amount_paise=proposal.total_paise,
                currency="INR", notes=notes)
            proposal.razorpay_order_id = order.order_id
            emit(session, actor="payments", action="order.created", proposal=proposal,
                 detail={"order_id": order.order_id, "amount_paise": order.amount_paise})
    except PaymentsTimeout as exc:
        transition(session, proposal, ProposalState.UNCERTAIN, actor="payments",
                   cause="ambiguous API outcome during order creation",
                   evidence={"error": str(exc)})
        return proposal
    except PaymentsError as exc:
        transition(session, proposal, ProposalState.FAILED, actor="payments",
                   cause="definitive API error during order creation",
                   evidence={"error": str(exc)})
        return proposal

    transition(session, proposal, ProposalState.ORDER_CREATED, actor="payments",
               cause="razorpay order ensured", evidence={"order_id": proposal.razorpay_order_id})
    transition(session, proposal, ProposalState.AWAITING_PAYMENT, actor="payments",
               cause="payment instructions issued to agent")
    return proposal


def verify_and_apply_payment(session: Session, client: RazorpayClient, proposal: Proposal) -> bool:
    """Fetch ground truth from Razorpay and, if a captured payment matches, mark PAID.

    Webhooks only *trigger* this; the API fetch is the truth (docs recommend exactly this).
    Returns True when the proposal reached PAID.
    """
    if not proposal.razorpay_order_id:
        return False
    payments = client.fetch_order_payments(proposal.razorpay_order_id)  # may raise PaymentsTimeout
    captured = [p for p in payments if p.status == "captured"]
    if not captured:
        return False

    payment = captured[0]
    if payment.amount_paise != proposal.total_paise:
        emit(session, actor="payments", action="payment.amount_mismatch", proposal=proposal,
             detail={"expected_paise": proposal.total_paise, "actual_paise": payment.amount_paise,
                     "payment_id": payment.payment_id})
        transition(session, proposal, ProposalState.FAILED, actor="payments",
                   cause="captured amount does not match authorized total",
                   evidence={"payment_id": payment.payment_id})
        return False

    proposal.razorpay_payment_id = payment.payment_id
    current = ProposalState(proposal.state)
    if current in (ProposalState.PAID, ProposalState.FULFILLED, ProposalState.REFUNDED):
        return True  # monotonic: already settled, nothing to regress
    transition(session, proposal, ProposalState.PAID, actor="payments",
               cause="payment verified via API fetch",
               evidence={"payment_id": payment.payment_id, "amount_paise": payment.amount_paise})

    mandate = session.get(Mandate, proposal.mandate_id)
    if mandate is not None:
        mandate.spent_paise += proposal.total_paise
    return True
