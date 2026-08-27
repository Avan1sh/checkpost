"""The proposal pipeline — every purchase proposal walks these steps in order.

validation -> trust -> advisory screening -> deterministic policy -> payment execution
Each step can only move the proposal through the state machine, which records evidence.
"""
from datetime import datetime, time as dtime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.audit.events import emit
from gateway.domain.models import Agent, Approval, CompiledPolicy, Mandate, Product, Proposal
from gateway.domain.state_machine import transition
from gateway.domain.states import ProposalState
from gateway.llm import checks as llm
from gateway.payments.client import RazorpayClient
from gateway.payments.orders import ensure_order
from gateway.policy import engine
from gateway.policy.schema import PolicyContext, PolicyRuleSet, PricedLine
from gateway.trust.mandates import MandateRejection, verify_mandate


def _load_active_rules(session: Session, merchant_id: str) -> PolicyRuleSet:
    row = session.scalars(
        select(CompiledPolicy)
        .where(CompiledPolicy.merchant_id == merchant_id, CompiledPolicy.status == "active")
        .order_by(CompiledPolicy.created_at.desc())
    ).first()
    return PolicyRuleSet.model_validate(row.rules) if row else PolicyRuleSet()


def _policy_context(session: Session, agent_id: str) -> PolicyContext:
    midnight = datetime.combine(datetime.now(timezone.utc).date(), dtime.min, tzinfo=timezone.utc)
    counted_states = [s.value for s in (
        ProposalState.AUTHORIZED, ProposalState.ORDER_CREATED, ProposalState.AWAITING_PAYMENT,
        ProposalState.UNCERTAIN, ProposalState.RECONCILING, ProposalState.PAID, ProposalState.FULFILLED,
    )]
    rows = session.scalars(
        select(Proposal).where(
            Proposal.agent_id == agent_id,
            Proposal.created_at >= midnight,
            Proposal.state.in_(counted_states),
        )
    ).all()
    return PolicyContext(
        agent_orders_today=len(rows),
        agent_value_today_paise=sum(p.total_paise for p in rows),
    )


def submit_proposal(
    session: Session,
    client: RazorpayClient,
    *,
    agent: Agent,
    mandate: Mandate,
    intent_text: str,
    cart: list[dict],
) -> Proposal:
    proposal = Proposal(
        merchant_id=agent.merchant_id, agent_id=agent.id, mandate_id=mandate.id,
        intent_text=intent_text, cart=cart,
    )
    session.add(proposal)
    session.flush()
    emit(session, actor="agent", action="proposal.received", proposal=proposal,
         detail={"intent": intent_text[:500], "cart": cart})

    # [1] Validation — re-price from the catalog; agent-supplied prices/SKUs are never trusted.
    priced: list[PricedLine] = []
    problems: list[str] = []
    for line in cart:
        sku, qty = str(line.get("sku", "")), int(line.get("qty", 0))
        product = session.scalars(
            select(Product).where(Product.merchant_id == agent.merchant_id, Product.sku == sku)
        ).first()
        if product is None:
            problems.append(f"unknown SKU '{sku}'")
        elif product.quarantined:
            problems.append(f"'{sku}' is quarantined pending merchant review")
        elif qty <= 0:
            problems.append(f"invalid quantity {qty} for '{sku}'")
        elif product.stock < qty:
            problems.append(f"insufficient stock for '{sku}' ({product.stock} available)")
        else:
            priced.append(PricedLine(
                sku=product.sku, name=product.name, category=product.category, qty=qty,
                unit_paise=product.price_paise, line_paise=qty * product.price_paise,
                requires_approval=product.requires_approval,
                max_qty_per_order=product.max_qty_per_order,
            ))
    if problems or not priced:
        proposal.decision = {"stage": "validation", "problems": problems or ["empty cart"]}
        transition(session, proposal, ProposalState.REJECTED, actor="system",
                   cause="cart validation failed", evidence={"problems": problems})
        return proposal
    proposal.priced_cart = [line.model_dump() for line in priced]
    proposal.total_paise = sum(line.line_paise for line in priced)
    transition(session, proposal, ProposalState.VALIDATED, actor="system",
               cause="cart re-priced from catalog",
               evidence={"total_paise": proposal.total_paise})

    # [2] Trust — passport already checked at the API layer; verify the mandate here.
    try:
        verify_mandate(mandate, order_total_paise=proposal.total_paise,
                       cart_categories={line.category for line in priced})
    except MandateRejection as rejection:
        proposal.decision = {"stage": "trust", "code": rejection.code, "message": rejection.message}
        transition(session, proposal, ProposalState.REJECTED, actor="trust",
                   cause=rejection.code, evidence={"message": rejection.message})
        return proposal
    transition(session, proposal, ProposalState.TRUST_VERIFIED, actor="trust",
               cause="mandate signature, expiry, cap and scope verified",
               evidence={"mandate_id": mandate.id, "principal": mandate.principal})

    # [3] Advisory screening — can only tighten the outcome. None (LLM off/failed) => escalate.
    screen_escalations: list[str] = []
    screen_flags: list[str] = []

    product_fields = {
        f"product_description:{line.sku}": session.scalars(
            select(Product).where(Product.merchant_id == agent.merchant_id,
                                  Product.sku == line.sku)).first().description
        for line in priced
    }
    from gateway.core.config import get_settings
    fail_closed = get_settings().llm_failure_policy == "escalate"

    injection = llm.injection_screen(
        session, proposal_id=proposal.id,
        fields={"agent_intent": intent_text, **product_fields})
    if injection is None:
        if fail_closed:
            screen_escalations.append("injection screen unavailable — defaulting to human review")
    elif injection.flagged:
        screen_flags.append(f"instruction-shaped content detected in: {injection.suspicious_fields}")
        for field in injection.suspicious_fields:
            if field.startswith("product_description:"):
                sku = field.split(":", 1)[1]
                product = session.scalars(select(Product).where(
                    Product.merchant_id == agent.merchant_id, Product.sku == sku)).first()
                if product is not None:
                    product.quarantined = True
                    emit(session, actor="screening", action="catalog.quarantined",
                         proposal=proposal, detail={"sku": sku, "reasons": injection.reasons})

    match = llm.intent_match(
        session, proposal_id=proposal.id, mandate_purpose=mandate.purpose,
        intent_text=intent_text, priced_cart=proposal.priced_cart)
    if match is None:
        if fail_closed:
            screen_escalations.append("intent–cart match unavailable — defaulting to human review")
    elif match.match != "match":
        screen_escalations.append(
            f"intent–cart match verdict '{match.match}': {'; '.join(match.reasons) or 'no reasons given'}")

    screening = {
        "injection": injection.model_dump() if injection else {"unavailable": True},
        "intent_match": match.model_dump() if match else {"unavailable": True},
        "flags": screen_flags, "escalations": screen_escalations,
    }
    transition(session, proposal, ProposalState.SCREENED, actor="screening",
               cause="advisory checks recorded", evidence=screening)

    # [4] Deterministic policy — the only authority that can approve.
    rules = _load_active_rules(session, agent.merchant_id)
    verdict = engine.evaluate(priced, rules, _policy_context(session, agent.id))
    proposal.decision = {
        "stage": "policy", "screening": screening,
        "verdict": verdict.model_dump(),
    }

    if verdict.result == "block":
        transition(session, proposal, ProposalState.BLOCKED, actor="policy_engine",
                   cause="; ".join(v.rule for v in verdict.violations),
                   evidence=verdict.model_dump())
        return proposal

    needs_human = verdict.result == "escalate" or screen_escalations or screen_flags
    if needs_human:
        reasons = ([v.message for v in verdict.escalations]
                   + screen_escalations
                   + [f"screening flag: {flag}" for flag in screen_flags])
        session.add(Approval(proposal_id=proposal.id, reason="\n".join(reasons)))
        transition(session, proposal, ProposalState.PENDING_APPROVAL, actor="policy_engine",
                   cause="human review required", evidence={"reasons": reasons})
        return proposal

    transition(session, proposal, ProposalState.AUTHORIZED, actor="policy_engine",
               cause="all deterministic checks passed", evidence={"rules_applied": rules.model_dump()})

    # [5] Payment execution — the idempotent choke point.
    return ensure_order(session, client, proposal)


def decide_approval(
    session: Session,
    client: RazorpayClient,
    *,
    approval: Approval,
    proposal: Proposal,
    approve: bool,
    reviewer: str,
    note: str = "",
) -> Proposal:
    """Human gate outcome. Approval issues a Razorpay Payment Link addressed to the
    principal (a human pays after human review — the agent never handles this payment)."""
    from gateway.domain.models import utcnow

    approval.status = "approved" if approve else "denied"
    approval.reviewer, approval.note, approval.decided_at = reviewer, note, utcnow()

    if not approve:
        transition(session, proposal, ProposalState.DENIED, actor=f"reviewer:{reviewer}",
                   cause="human review denied", evidence={"note": note})
        return proposal

    transition(session, proposal, ProposalState.AUTHORIZED, actor=f"reviewer:{reviewer}",
               cause="human review approved", evidence={"note": note})
    link_id, url = client.create_payment_link(
        reference_id=proposal.id, amount_paise=proposal.total_paise,
        description=f"Sehat Pharmacy order {proposal.id} (reviewed by {reviewer})",
        notes={"proposal_id": proposal.id, "agent_id": proposal.agent_id, "approved_by": reviewer})
    proposal.payment_link_id, proposal.payment_link_url = link_id, url
    transition(session, proposal, ProposalState.ORDER_CREATED, actor="payments",
               cause="payment link issued to principal after human approval",
               evidence={"payment_link_id": link_id})
    transition(session, proposal, ProposalState.AWAITING_PAYMENT, actor="payments",
               cause="awaiting principal's payment via link")
    return proposal
