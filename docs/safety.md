# Checkpost — Safety Model

## The one rule

**No LLM output can move money.** This is wiring, not prompting: the pipeline gives LLM
verdicts exactly two powers — *escalate* (route to a human) and *flag* (quarantine
content). The only component that can produce `AUTHORIZED` is the deterministic policy
engine, and the only component that can create a Razorpay order is the idempotent
choke point downstream of it. `tests/safety/test_failures.py::test_llm_verdict_cannot_authorize`
asserts this: an LLM verdict saying "approve immediately" changes nothing.

## Boundaries and why each exists

| Boundary | Enforced by | Why |
|---|---|---|
| Agent passport (`X-Agent-Key`, hashed at rest) | API layer | A merchant must know *which* agent is buying before anything else; anonymous agent traffic is unauditable. |
| Mandate signature (HMAC over agent, principal, purpose, cap, scope, expiry) | trust layer | Delegated authority must be tamper-evident — an agent editing its own cap must be caught (tested). |
| Mandate expiry & revocation | trust layer | Delegation is time-boxed and withdrawable; stale authority is refused. |
| Mandate spend cap (counts prior spend) | trust layer | The *principal's* limit on their agent — independent of merchant policy. |
| Mandate category scope | trust layer | An agent for diabetes refills shouldn't buy anything else, even if the merchant would sell it. |
| Catalog re-pricing | validation | Agent-supplied prices/SKUs are never trusted; closes stale-price and fabricated-price attacks. |
| Per-SKU / category quantity caps | policy engine | Anti-hoarding and (pharmacy) regulatory limits. |
| Blocked categories | policy engine | Some goods are never sold through agent channels (controlled substances). |
| Order value cap + approval threshold | policy engine | Bounds the blast radius of any single bad decision; large orders get human eyes. |
| Per-agent daily velocity caps (orders + value) | policy engine | A compromised or looping agent is rate-limited by construction. |
| Human approval gate | approvals + Payment Links | Rx items and high-value orders need a person; the payment then goes to the *principal* via link — the agent never handles it. |
| Idempotent order creation (receipt = proposal id, check-before-create) | payments | At most one Razorpay order per proposal, ever — even across timeouts and retries. |
| Webhook signature + event-id dedup + monotonic states | webhook layer | Forged, duplicated, or out-of-order events cannot corrupt payment state. |
| Bounded reconciliation with explicit FAILED | reconciler | Nothing silently spins forever; exhaustion alerts the merchant. |
| Fail-closed advisory checks (configurable) | pipeline | If the LLM is down, the gateway gets stricter, not blinder. |

## Prompt-injection posture (defense in depth, in order)

1. **Architecture**: LLM verdicts are advisory — even a fully hijacked model output
   cannot authorize a payment. This is the layer that actually matters.
2. **Data/instruction separation**: untrusted text reaches the LLM only inside
   `<untrusted_data>` tags, with tag-breakout stripping, under a system prompt that
   defines it as data.
3. **Detection**: the injection screen flags instruction-shaped content, quarantines the
   offending catalog item (withheld from agent traffic), audits the attempt, and routes
   the proposal to a human.

## What we deliberately did NOT do

- No LLM-evaluated policies ("ask the model if this order is okay") — policies compile to
  a schema once, get human confirmation, and run as code.
- No agent-supplied pricing, totals, or product metadata in any decision path.
- No trust in webhooks as truth — they are triggers; the Razorpay API fetch is the truth.
- No silent retry of ambiguous failures — UNCERTAIN is a first-class state owned by the
  reconciler, and its policy is verify-then-act.
