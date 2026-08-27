"""The only way a proposal changes state.

Enforces the legal-transition table, records a ProposalTransition row and an AuditEvent
for every change — including refused illegal attempts, which are themselves evidence.
"""
from sqlalchemy.orm import Session

from gateway.audit.events import emit
from gateway.domain.models import Proposal, ProposalTransition
from gateway.domain.states import IllegalTransition, ProposalState, assert_legal


def transition(
    session: Session,
    proposal: Proposal,
    target: ProposalState,
    *,
    actor: str,
    cause: str,
    evidence: dict | None = None,
) -> Proposal:
    current = ProposalState(proposal.state)
    try:
        assert_legal(current, target)
    except IllegalTransition:
        emit(session, actor=actor, action="transition.refused", proposal=proposal,
             detail={"from": current.value, "to": target.value, "cause": cause})
        raise

    proposal.state = target
    session.add(ProposalTransition(
        proposal_id=proposal.id,
        from_state=current.value,
        to_state=target.value,
        actor=actor,
        cause=cause[:200],
        evidence=evidence or {},
    ))
    emit(session, actor=actor, action=f"proposal.{target.value}", proposal=proposal,
         detail={"from": current.value, "cause": cause, **({"evidence": evidence} if evidence else {})})
    session.flush()
    return proposal
