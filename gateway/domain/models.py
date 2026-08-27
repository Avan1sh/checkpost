"""SQLAlchemy models. All money values are integer paise."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gateway.core.db import Base
from gateway.domain.states import ProposalState


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mer"))
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Agent(Base):
    """An AI buyer registered with the merchant. Its API key ("passport") is stored hashed."""
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("agt"))
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    name: Mapped[str] = mapped_column(String(120))
    operator: Mapped[str] = mapped_column(String(120))  # who runs the agent (platform/company)
    key_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | suspended
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Mandate(Base):
    """Signed delegation from a human principal to an agent (AP2-shaped, HMAC-signed demo)."""
    __tablename__ = "mandates"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mnd"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    principal: Mapped[str] = mapped_column(String(120))          # the human who delegated
    purpose: Mapped[str] = mapped_column(Text)                   # stated purpose, e.g. "monthly diabetes refill"
    max_amount_paise: Mapped[int] = mapped_column(Integer)       # total spend cap
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    allowed_categories: Mapped[list] = mapped_column(JSON, default=list)  # [] = any
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    signature: Mapped[str] = mapped_column(String(128))
    spent_paise: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | revoked
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("merchant_id", "sku"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("prd"))
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    sku: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64))
    price_paise: Mapped[int] = mapped_column(Integer)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)  # e.g. Rx-gated
    max_qty_per_order: Mapped[int] = mapped_column(Integer, default=10)
    stock: Mapped[int] = mapped_column(Integer, default=100)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)  # injection screen hit


class Proposal(Base):
    """A purchase proposal from an agent — the unit the whole pipeline operates on."""
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("prp"))
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.id"))
    state: Mapped[ProposalState] = mapped_column(String(24), default=ProposalState.RECEIVED)
    intent_text: Mapped[str] = mapped_column(Text)
    cart: Mapped[list] = mapped_column(JSON)          # as submitted: [{sku, qty, ...}]
    priced_cart: Mapped[list] = mapped_column(JSON, default=list)  # re-priced from catalog
    total_paise: Mapped[int] = mapped_column(Integer, default=0)
    decision: Mapped[dict] = mapped_column(JSON, default=dict)     # verdicts, violations, alternative
    razorpay_order_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    razorpay_payment_id: Mapped[str] = mapped_column(String(64), default="")
    payment_link_id: Mapped[str] = mapped_column(String(64), default="")
    payment_link_url: Mapped[str] = mapped_column(String(256), default="")
    reconcile_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    transitions: Mapped[list["ProposalTransition"]] = relationship(
        back_populates="proposal", order_by="ProposalTransition.seq")


class ProposalTransition(Base):
    __tablename__ = "proposal_transitions"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    from_state: Mapped[str] = mapped_column(String(24))
    to_state: Mapped[str] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(64))    # system | policy_engine | reconciler | reviewer:<name> | agent
    cause: Mapped[str] = mapped_column(String(200))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    proposal: Mapped[Proposal] = relationship(back_populates="transitions")


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("apr"))
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)          # why human review is required
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | denied | expired
    reviewer: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookEvent(Base):
    """Every received webhook, keyed on Razorpay's event id — the dedupe ledger."""
    __tablename__ = "webhook_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # x-razorpay-event-id
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(32), unique=True, default=lambda: new_id("evt"))
    trace_id: Mapped[str] = mapped_column(String(32), index=True)   # = proposal id for pipeline events
    proposal_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    agent_id: Mapped[str] = mapped_column(String(32), default="")
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LLMCall(Base):
    """Every LLM invocation, for the honest cost/latency/accuracy story in evals."""
    __tablename__ = "llm_calls"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    role: Mapped[str] = mapped_column(String(32))  # intent_match | injection_screen | policy_compile
    model: Mapped[str] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    verdict: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CompiledPolicy(Base):
    """Merchant policy: natural-language source + LLM-compiled rules + human confirmation."""
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pol"))
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"))
    source_text: Mapped[str] = mapped_column(Text)
    rules: Mapped[dict] = mapped_column(JSON)          # PolicyRuleSet schema
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | active | retired
    confirmed_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
