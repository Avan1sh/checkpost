"""Proposal lifecycle states and the legal-transition table.

This module is the single source of truth for what a purchase proposal may do next.
Any transition not listed here raises, and the attempt itself is auditable.
"""
from enum import Enum


class ProposalState(str, Enum):
    RECEIVED = "received"                  # raw submission stored
    VALIDATED = "validated"                # schema ok, cart re-priced from catalog
    TRUST_VERIFIED = "trust_verified"      # passport + mandate signature/expiry/cap ok
    SCREENED = "screened"                  # LLM advisory checks recorded (match/injection)
    AUTHORIZED = "authorized"              # deterministic policy engine approved
    BLOCKED = "blocked"                    # policy rejected; safe alternative offered
    PENDING_APPROVAL = "pending_approval"  # routed to human (pharmacist) review
    DENIED = "denied"                      # human rejected
    REJECTED = "rejected"                  # failed validation or trust checks
    ORDER_CREATED = "order_created"        # Razorpay order exists (or payment link issued)
    AWAITING_PAYMENT = "awaiting_payment"  # order shared with agent/principal
    UNCERTAIN = "uncertain"                # ambiguous API outcome — reconciler owns this
    RECONCILING = "reconciling"            # reconciler actively verifying ground truth
    PAID = "paid"                          # payment verified via API fetch, not just webhook
    FULFILLED = "fulfilled"                # merchant completed the order
    FAILED = "failed"                      # exhausted recovery; merchant alerted
    EXPIRED = "expired"                    # approval or payment window lapsed
    REFUNDED = "refunded"                  # post-hoc remediation


TERMINAL_STATES = frozenset({
    ProposalState.BLOCKED,
    ProposalState.DENIED,
    ProposalState.REJECTED,
    ProposalState.FULFILLED,
    ProposalState.FAILED,
    ProposalState.EXPIRED,
    ProposalState.REFUNDED,
})

LEGAL_TRANSITIONS: dict[ProposalState, frozenset[ProposalState]] = {
    ProposalState.RECEIVED: frozenset({ProposalState.VALIDATED, ProposalState.REJECTED}),
    ProposalState.VALIDATED: frozenset({ProposalState.TRUST_VERIFIED, ProposalState.REJECTED}),
    ProposalState.TRUST_VERIFIED: frozenset({ProposalState.SCREENED, ProposalState.REJECTED}),
    ProposalState.SCREENED: frozenset({
        ProposalState.AUTHORIZED, ProposalState.BLOCKED, ProposalState.PENDING_APPROVAL,
    }),
    ProposalState.PENDING_APPROVAL: frozenset({
        ProposalState.AUTHORIZED, ProposalState.DENIED, ProposalState.EXPIRED,
    }),
    ProposalState.AUTHORIZED: frozenset({
        ProposalState.ORDER_CREATED, ProposalState.UNCERTAIN, ProposalState.FAILED,
    }),
    ProposalState.ORDER_CREATED: frozenset({ProposalState.AWAITING_PAYMENT}),
    ProposalState.AWAITING_PAYMENT: frozenset({
        ProposalState.PAID, ProposalState.UNCERTAIN, ProposalState.FAILED, ProposalState.EXPIRED,
    }),
    ProposalState.UNCERTAIN: frozenset({ProposalState.RECONCILING}),
    ProposalState.RECONCILING: frozenset({
        ProposalState.PAID, ProposalState.AWAITING_PAYMENT, ProposalState.ORDER_CREATED,
        ProposalState.UNCERTAIN, ProposalState.FAILED,
    }),
    ProposalState.PAID: frozenset({ProposalState.FULFILLED, ProposalState.REFUNDED}),
}


class IllegalTransition(Exception):
    def __init__(self, current: ProposalState, target: ProposalState):
        self.current, self.target = current, target
        super().__init__(f"illegal transition {current.value} -> {target.value}")


def assert_legal(current: ProposalState, target: ProposalState) -> None:
    if target not in LEGAL_TRANSITIONS.get(current, frozenset()):
        raise IllegalTransition(current, target)
