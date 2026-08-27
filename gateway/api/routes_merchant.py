"""Merchant-facing API: approval queue, audit timeline, policy management, agent registry."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.api.pipeline import decide_approval
from gateway.core.db import get_session
from gateway.domain.models import (
    Agent, Approval, AuditEvent, CompiledPolicy, LLMCall, Mandate, Product, Proposal,
)
from gateway.domain.states import ProposalState
from gateway.llm import checks as llm
from gateway.payments.client import get_client

router = APIRouter(prefix="/merchant", tags=["merchant"])


@router.get("/proposals")
def list_proposals(session: Session = Depends(get_session), limit: int = 50):
    rows = session.scalars(
        select(Proposal).order_by(Proposal.created_at.desc()).limit(limit)).all()
    agents = {a.id: a for a in session.scalars(select(Agent)).all()}
    return {"proposals": [{
        "proposal_id": p.id, "state": p.state, "agent": agents[p.agent_id].name,
        "intent_text": p.intent_text, "total_paise": p.total_paise,
        "created_at": p.created_at.isoformat(),
    } for p in rows]}


@router.get("/proposals/{proposal_id}")
def proposal_detail(proposal_id: str, session: Session = Depends(get_session)):
    proposal = session.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "proposal not found")
    mandate = session.get(Mandate, proposal.mandate_id)
    events = session.scalars(
        select(AuditEvent).where(AuditEvent.trace_id == proposal_id)
        .order_by(AuditEvent.seq)).all()
    llm_calls = session.scalars(
        select(LLMCall).where(LLMCall.proposal_id == proposal_id).order_by(LLMCall.seq)).all()
    return {
        "proposal_id": proposal.id, "state": proposal.state,
        "intent_text": proposal.intent_text, "cart": proposal.cart,
        "priced_cart": proposal.priced_cart, "total_paise": proposal.total_paise,
        "decision": proposal.decision,
        "mandate": {"id": mandate.id, "principal": mandate.principal,
                    "purpose": mandate.purpose,
                    "max_amount_paise": mandate.max_amount_paise} if mandate else None,
        "razorpay_order_id": proposal.razorpay_order_id or None,
        "razorpay_payment_id": proposal.razorpay_payment_id or None,
        "payment_link_url": proposal.payment_link_url or None,
        "transitions": [{
            "from": t.from_state, "to": t.to_state, "actor": t.actor, "cause": t.cause,
            "evidence": t.evidence, "at": t.created_at.isoformat(),
        } for t in proposal.transitions],
        "audit_events": [{
            "id": e.id, "actor": e.actor, "action": e.action, "detail": e.detail,
            "at": e.created_at.isoformat(),
        } for e in events],
        "llm_calls": [{
            "role": c.role, "model": c.model, "latency_ms": c.latency_ms,
            "verdict": c.verdict, "error": c.error or None,
        } for c in llm_calls],
    }


@router.get("/approvals")
def approval_queue(session: Session = Depends(get_session)):
    rows = session.scalars(
        select(Approval).where(Approval.status == "pending").order_by(Approval.created_at)).all()
    proposals = {p.id: p for p in session.scalars(
        select(Proposal).where(Proposal.id.in_([a.proposal_id for a in rows]))).all()}
    return {"approvals": [{
        "approval_id": a.id, "proposal_id": a.proposal_id, "reason": a.reason,
        "total_paise": proposals[a.proposal_id].total_paise,
        "intent_text": proposals[a.proposal_id].intent_text,
        "created_at": a.created_at.isoformat(),
    } for a in rows]}


class Decision(BaseModel):
    approve: bool
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = ""


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: str, body: Decision, session: Session = Depends(get_session)):
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "approval not found")
    if approval.status != "pending":
        raise HTTPException(409, f"approval already {approval.status}")
    proposal = session.get(Proposal, approval.proposal_id)
    if ProposalState(proposal.state) != ProposalState.PENDING_APPROVAL:
        raise HTTPException(409, f"proposal is in state {proposal.state}")
    decide_approval(session, get_client(), approval=approval, proposal=proposal,
                    approve=body.approve, reviewer=body.reviewer, note=body.note)
    return {"proposal_id": proposal.id, "state": proposal.state,
            "payment_link_url": proposal.payment_link_url or None}


@router.get("/audit")
def audit_feed(session: Session = Depends(get_session), limit: int = 100):
    rows = session.scalars(
        select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)).all()
    return {"events": [{
        "id": e.id, "trace_id": e.trace_id, "proposal_id": e.proposal_id or None,
        "actor": e.actor, "action": e.action, "detail": e.detail,
        "at": e.created_at.isoformat(),
    } for e in rows]}


class PolicyDraftIn(BaseModel):
    source_text: str = Field(min_length=1, max_length=8000)


@router.post("/policies/compile")
def compile_policy(body: PolicyDraftIn, session: Session = Depends(get_session)):
    """LLM-compile merchant prose into rules. Result is a DRAFT until confirmed."""
    merchant_id = session.scalars(select(Agent.merchant_id)).first()
    skus = list(session.scalars(select(Product.sku)).all())
    categories = sorted(set(session.scalars(select(Product.category)).all()))
    compiled = llm.compile_policy(session, source_text=body.source_text,
                                  known_skus=skus, known_categories=categories)
    if compiled is None:
        raise HTTPException(503, "policy compiler unavailable (LLM disabled or failed); "
                                 "activate a policy by POSTing rules directly")
    draft = CompiledPolicy(merchant_id=merchant_id, source_text=body.source_text,
                           rules=compiled.rules.model_dump(), status="draft")
    session.add(draft)
    session.flush()
    return {"policy_id": draft.id, "rules": compiled.rules.model_dump(),
            "notes": compiled.notes, "status": "draft"}


class PolicyConfirmIn(BaseModel):
    confirmed_by: str = Field(min_length=1, max_length=120)


@router.post("/policies/{policy_id}/confirm")
def confirm_policy(policy_id: str, body: PolicyConfirmIn,
                   session: Session = Depends(get_session)):
    """Human confirmation is what activates a compiled policy — never the LLM."""
    draft = session.get(CompiledPolicy, policy_id)
    if draft is None:
        raise HTTPException(404, "policy not found")
    for row in session.scalars(select(CompiledPolicy).where(
            CompiledPolicy.merchant_id == draft.merchant_id,
            CompiledPolicy.status == "active")).all():
        row.status = "retired"
    draft.status, draft.confirmed_by = "active", body.confirmed_by
    return {"policy_id": draft.id, "status": "active"}


@router.get("/policies/active")
def active_policy(session: Session = Depends(get_session)):
    row = session.scalars(select(CompiledPolicy).where(
        CompiledPolicy.status == "active").order_by(CompiledPolicy.created_at.desc())).first()
    if row is None:
        return {"policy": None}
    return {"policy": {"id": row.id, "source_text": row.source_text, "rules": row.rules,
                       "confirmed_by": row.confirmed_by}}
