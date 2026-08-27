"""Structured audit event emission — the evidence stream behind every decision."""
from typing import Optional

from sqlalchemy.orm import Session

from gateway.domain.models import AuditEvent, Proposal


def emit(
    session: Session,
    *,
    actor: str,
    action: str,
    proposal: Optional[Proposal] = None,
    trace_id: str = "",
    agent_id: str = "",
    detail: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        trace_id=trace_id or (proposal.id if proposal else ""),
        proposal_id=proposal.id if proposal else "",
        agent_id=agent_id or (proposal.agent_id if proposal else ""),
        actor=actor,
        action=action,
        detail=detail or {},
    )
    session.add(event)
    return event
