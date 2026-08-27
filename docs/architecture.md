# Checkpost — Architecture

**One line:** the merchant-side gateway that makes a merchant safely transactable by AI buyer
agents — verify who the agent is and what it is authorized to do, enforce the merchant's own
policy deterministically, execute payments idempotently on Razorpay, and prove every decision
with an audit trail.

## Why this exists

Agentic commerce has produced a thousand buyers and no bouncer. Buyer-side agents get wallets,
spend caps and mandates (AP2, x402 wallets, Prava-style cards). The merchant — who carries the
fraud, policy and reconciliation risk — gets anonymous POST requests. Checkpost is the
merchant's front door for agent traffic.

Demo merchant: **Sehat Pharmacy**, an online pharmacy. Chosen deliberately: pharmacies have a
genuinely hard policy surface (prescription-gated SKUs, per-SKU quantity caps, order-value
limits, purchase-frequency rules), which makes "policy enforcement" concrete instead of
abstract, and gives the human-approval gate a real-world justification (pharmacist review).

## Actors

| Actor | Role |
|---|---|
| AI buyer agent | Shops on behalf of a human principal, presenting a signed mandate |
| Checkpost gateway | The product: trust + policy + payment control plane |
| Merchant operator | Pharmacist using the dashboard: approvals, audit timeline, policy editing |
| Razorpay (test mode) | Settlement rail: Orders, Payment Links, payment fetch, webhooks, refunds |

## The pipeline (the whole product in one diagram)

```text
AI buyer agent
      │  purchase proposal (cart + intent + mandate ref)
      ▼
[1] Schema validation            deterministic   reject malformed input
[2] Agent identity check         deterministic   passport (merchant-issued key)
[3] Mandate verification         deterministic   signature, expiry, spend cap, scope
[4] Intent–cart match            LLM (advisory)  does the cart semantically match the
                                                 mandate's stated purpose? ambiguous → escalate
[5] Injection screen             LLM (advisory)  instruction-shaped content in agent payload
                                                 or catalog fields → flag + quarantine
[6] Policy engine                deterministic   compiled merchant rules: SKU gates, quantity
                                                 caps, value limits, velocity, approval rules
      ▼
 decision: AUTHORIZED │ BLOCKED (+ explained safe alternative) │ PENDING_APPROVAL (human gate)
      ▼
[7] Idempotent order creation    deterministic   Razorpay Orders API, receipt = proposal id
[8] Payment + verification       deterministic   webhook (deduped) → API fetch confirms truth
[9] Reconciler                   deterministic   UNCERTAIN states resolved by verify-then-act,
                                                 never blind retry
      ▼
[10] Audit event stream          every step above emits a structured, replayable event
```

**The invariant: money moves only through steps 6–8. No LLM output can move money.** LLM
verdicts (steps 4–5) can only *tighten* the outcome — escalate or flag — never authorize.
LLM call failure defaults to escalation (fail-safe, not fail-open).

## Components

```
gateway/
├── api/        FastAPI routes: agent-facing (catalog, proposals, payment), merchant-facing
│               (approvals, policies, audit), Razorpay webhooks
├── core/       config, database session, security primitives
├── domain/     SQLAlchemy models + the proposal state machine (single source of truth
│               for legal transitions)
├── trust/      agent passports and mandate verification (HMAC-signed mandates; production
│               path is AP2 verifiable credentials / NPCI UAP once live)
├── policy/     compiled policy schema (Pydantic) + deterministic evaluation engine —
│               pure functions, exhaustively unit-tested
├── llm/        Gemini client + the three advisory roles: policy compiler, intent matcher,
│               injection screen; strict JSON outputs; advisory-only by construction
├── payments/   RazorpayClient interface with two implementations: real (test-mode HTTP)
│               and mock (fault-injecting simulator); idempotency store; reconciler loop
└── audit/      structured audit event emission

buyer_agent/    demo AI buyer ("PillPal") that shops through the gateway — including
                misbehaving modes used in the demo and eval suite
dashboard/      merchant console (React + Vite): live agent timeline, approval queue,
                policy editor, audit drill-down
tests/          unit / integration / safety / evals — see docs/evaluation.md
```

## Proposal state machine

```text
RECEIVED → VALIDATED → TRUST_VERIFIED → SCREENED → AUTHORIZED → ORDER_CREATED
                │             │             │           │              │
                ▼             ▼             ▼           ▼              ▼
             REJECTED      REJECTED      BLOCKED    PENDING_      AWAITING_PAYMENT
                                            │       APPROVAL        │        │
                                            ▼       │      │        ▼        ▼
                                        (safe alt) ▼       ▼      PAID   UNCERTAIN
                                              AUTHORIZED  DENIED    │        │
                                                                    ▼        ▼
                                                               FULFILLED  RECONCILING
                                                                            │    │
                                                                            ▼    ▼
                                                                          PAID  FAILED
```

Transitions are enforced in one place (`domain/state_machine.py`); illegal transitions raise
and are themselves audit events. Every transition records actor, cause, and evidence.

## Razorpay integration (all test mode)

| Capability | Endpoint | Why |
|---|---|---|
| Orders | `POST /v1/orders` | The gated money action. `receipt` = proposal id gives natural idempotency; `notes` carry agent + mandate ids for reconciliation. |
| Fetch order payments | `GET /v1/orders/{id}/payments` | Ground truth for reconciliation — docs recommend supplementing webhooks with API verification. |
| Payment Links | `POST /v1/payment_links` | The human-approval path: pharmacist approves → link issued → principal (human) pays. |
| Webhooks | `order.paid`, `payment.captured`, `payment.failed` | Async truth stream. Signature verified (HMAC-SHA256). Duplicates are documented behavior → dedupe on `x-razorpay-event-id`. Out-of-order tolerated. |
| Refunds | `POST /v1/payments/{id}/refund` | Remediation when a violation is detected post-payment. |

`RAZORPAY_MODE=mock` runs an in-process simulator with the same interface plus fault
injection (timeouts, duplicate webhooks, out-of-order delivery) — used by the eval suite and
for running the repo without keys. `RAZORPAY_MODE=test` uses real test-mode APIs.

## Where the LLM is — and is not

| Task | Why an LLM | Authority |
|---|---|---|
| Policy compilation (merchant NL → rule JSON) | Merchants write policy in language, not JSON | None — merchant confirms compiled rules before activation |
| Intent–cart match | "Does this cart match 'monthly diabetes refill'?" is semantic | Advisory: can escalate, never approve |
| Injection screen | Instruction-shaped text is fuzzy | Advisory: can flag/quarantine, never approve |

Everything financial — limits, caps, velocity, signatures, idempotency, state transitions —
is deterministic code with unit tests, because correctness there is mandatory.
