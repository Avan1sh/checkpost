# Checkpost — Decision Log

Short records of the decisions that shaped the system, with the alternatives that lost.

## D1 — Merchant-side gateway, not another buyer agent
Everything at 2026 hackathons sits buyer-side (shopping agents, wallets, spend caps).
The merchant carries the actual fraud/policy/reconciliation risk and has no tooling on
Indian rails. Track 1's own wording — "make a merchant transactable by an AI buyer end to
end" — is answered from the merchant's side. Rejected: shopping agent (saturated),
reconciliation-only engine (fails the "why AI" test standalone), mandate wallet
(crowded buyer-side pattern).

## D2 — Pharmacy as the demo vertical
A gateway is abstract; a pharmacy makes every control concrete: Rx-gated SKUs justify the
human-approval gate, quantity caps justify the policy engine, real regulations justify
auditability. Rejected: generic electronics store (no interesting policy surface),
ticketing/anti-scalping (good, but policy surface is thinner than pharmacy's).

## D3 — FastAPI + SQLite + in-process reconciler; no Redis, no queue
A 9-day solo build reviewed by engineers rewards a repo that runs with one command and code
that is honest about scale. SQLite + SQLAlchemy keeps setup at zero while the schema stays
Postgres-portable. The reconciler is an asyncio loop — a queue would be theater at this
scale. Docker provided for convenience, not required.

## D4 — One strong agent + deterministic tools; no multi-agent choreography
The gateway itself is not an agent — it is deterministic infrastructure with three bounded
LLM call sites. The only true agent is the demo buyer. Multi-agent architectures were
rejected as ornamental: nothing here needs agents negotiating with agents.

## D5 — HMAC-signed mandates (demo-grade), AP2/UAP named as the production path
Real agent-identity rails (AP2 verifiable credentials, Visa TAP, NPCI UAP) are not
merchant-deployable today. We implement the same *shape* — principal, scope, spend cap,
expiry, signature — with HMAC so the trust layer is real and testable, and document the
swap-in path. Rejected: full VC/DID stack (days of work, zero demo value over HMAC),
no trust layer (guts the thesis).

## D6 — Mock-first Razorpay client behind one interface
`RAZORPAY_MODE=mock|test`. The mock is not a shortcut — it is the fault-injection harness
(timeouts, duplicate webhooks, out-of-order delivery) that makes the failure demos and the
eval suite deterministic and key-free. The real client hits test-mode APIs with the same
interface. Rejected: real-API-only (evals become flaky and non-reproducible for judges).

## D7 — LLM verdicts are advisory by construction, not by prompt
The pipeline wiring gives LLM outputs exactly two powers: escalate and flag. Approval
requires the deterministic engine. "The prompt tells the model to be careful" was rejected
as a safety mechanism — prompts are not boundaries.

## D8 — Cart is re-priced from the catalog; agent-supplied prices are never trusted
Closes the stale-price / fabricated-price class of attacks with one rule.

## D9 — Gemini (Google AI Studio) for the three advisory roles
The advisory layer needs structured JSON verdicts and nothing else — no long context, no
tool use, no reasoning traces. Gemini Flash does that well, and its free tier makes the
project reproducible by anyone cloning the repo, including judges, without a paid key.

The swap itself is the point worth noting: moving the whole system from Claude to Gemini
touched one function (`_run()` in `gateway/llm/checks.py`) plus config. That is a direct
consequence of the architecture — a component that cannot move money, cannot approve
anything, and only ever returns a schema-validated verdict is inherently swappable. The
deterministic core, the state machine, and every safety property were untouched, and the
test suite passed before and after unchanged.

Two adjustments came with the move:
- The policy compiler now emits into `CompiledRulesDraft` rather than `PolicyRuleSet`
  directly, folding key/value caps into the engine's dicts via `to_ruleset()`. This keeps
  the deterministic engine's schema from being shaped by what an LLM can emit, and keeps
  the model's output schema to arrays and scalars, which every provider supports.
  (Google's SDK does transform Python dicts into schemas with `additional_properties`, so
  this is a portability and coupling choice, not a Gemini limitation.)
- Free-tier rate limits (~10-15 requests/minute) are retried with backoff inside `_run()`;
  every other failure abstains immediately, since a slow escalation is worse than a fast one.

Rejected: OpenAI (no free tier for a student), local models (adds ops burden and a weaker
structured-output story for no architectural gain).
