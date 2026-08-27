"""Agent-facing API: catalog discovery, mandate lookup, proposal submission and status."""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.api.pipeline import submit_proposal
from gateway.core.db import get_session
from gateway.domain.models import Agent, Mandate, Product, Proposal
from gateway.payments.client import get_client
from gateway.trust.mandates import hash_passport

router = APIRouter(prefix="/agent", tags=["agent"])


def require_agent(
    session: Session = Depends(get_session),
    x_agent_key: str = Header(default=""),
) -> Agent:
    if not x_agent_key:
        raise HTTPException(401, "missing X-Agent-Key passport header")
    agent = session.scalars(
        select(Agent).where(Agent.key_hash == hash_passport(x_agent_key))
    ).first()
    if agent is None:
        raise HTTPException(401, "unknown agent passport")
    if agent.status != "active":
        raise HTTPException(403, f"agent is {agent.status}")
    return agent


@router.get("/catalog")
def catalog(agent: Agent = Depends(require_agent), session: Session = Depends(get_session)):
    """Agent-readable catalog. Quarantined items are withheld from agent traffic."""
    products = session.scalars(
        select(Product).where(Product.merchant_id == agent.merchant_id,
                              Product.quarantined.is_(False))
    ).all()
    return {"products": [{
        "sku": p.sku, "name": p.name, "description": p.description, "category": p.category,
        "price_paise": p.price_paise, "requires_pharmacist_approval": p.requires_approval,
        "max_qty_per_order": p.max_qty_per_order, "in_stock": p.stock > 0,
    } for p in products]}


@router.get("/mandates")
def mandates(agent: Agent = Depends(require_agent), session: Session = Depends(get_session)):
    rows = session.scalars(select(Mandate).where(Mandate.agent_id == agent.id)).all()
    return {"mandates": [{
        "id": m.id, "principal": m.principal, "purpose": m.purpose,
        "max_amount_paise": m.max_amount_paise, "spent_paise": m.spent_paise,
        "allowed_categories": m.allowed_categories, "expires_at": m.expires_at.isoformat(),
        "status": m.status,
    } for m in rows]}


class CartLine(BaseModel):
    sku: str
    qty: int = Field(gt=0, le=1000)


class ProposalIn(BaseModel):
    mandate_id: str
    intent_text: str = Field(min_length=1, max_length=4000)
    cart: list[CartLine] = Field(min_length=1, max_length=50)


def _proposal_view(p: Proposal) -> dict:
    return {
        "proposal_id": p.id, "state": p.state, "total_paise": p.total_paise,
        "priced_cart": p.priced_cart, "decision": p.decision,
        "razorpay_order_id": p.razorpay_order_id or None,
        "payment_link_url": p.payment_link_url or None,
    }


@router.post("/proposals")
def create_proposal(
    body: ProposalIn,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
):
    mandate = session.get(Mandate, body.mandate_id)
    if mandate is None or mandate.agent_id != agent.id:
        raise HTTPException(404, "mandate not found for this agent")
    proposal = submit_proposal(
        session, get_client(), agent=agent, mandate=mandate,
        intent_text=body.intent_text, cart=[line.model_dump() for line in body.cart])
    return _proposal_view(proposal)


@router.get("/proposals/{proposal_id}")
def proposal_status(
    proposal_id: str,
    agent: Agent = Depends(require_agent),
    session: Session = Depends(get_session),
):
    proposal = session.get(Proposal, proposal_id)
    if proposal is None or proposal.agent_id != agent.id:
        raise HTTPException(404, "proposal not found")
    return _proposal_view(proposal)
