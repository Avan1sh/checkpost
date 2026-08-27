# Checkpost — the merchant-side gateway for AI buyers

[![CI](https://github.com/Avan1sh/checkpost/actions/workflows/ci.yml/badge.svg)](https://github.com/Avan1sh/checkpost/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

**Razorpay AI Buildathon · Track 1 (AI Growth & Agentic Commerce)**

Agentic commerce has produced a thousand buyers and no bouncer. Buyer-side agents get
wallets, spend caps and mandates; the merchant — who carries the fraud, policy and
reconciliation risk — gets anonymous POST requests. **Checkpost is the front door a
merchant puts between AI buyer agents and their Razorpay account:**

- **Trust** — agent passports + signed mandates (who is buying, on whose behalf, with
  what authority) verified before anything else happens.
- **Policy** — the merchant's own rules (written in plain language, LLM-compiled,
  human-confirmed) enforced by a deterministic engine. Blocked orders come back with an
  explained, compliant alternative.
- **Human gate** — prescription items and high-value orders route to pharmacist review;
  approval issues a Razorpay Payment Link to the human principal.
- **Payments that stay true** — idempotent order creation (at most one Razorpay order per
  proposal, ever), webhook dedup, verify-before-retry reconciliation of ambiguous outcomes.
- **Audit** — every decision, verdict, and state change is a structured, replayable event.

**The invariant: no LLM output can move money.** LLM verdicts (intent–cart match,
injection screening, policy compilation) can only tighten an outcome — escalate or flag —
never authorize. See [docs/architecture.md](docs/architecture.md).

Demo merchant: **Sehat Pharmacy** — chosen because pharmacies have a genuinely hard policy
surface (Rx-gated SKUs, quantity caps, controlled substances) that makes every control
concrete.

## Run it (no keys required)

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
.venv/Scripts/python -m scripts.seed
.venv/Scripts/python -m uvicorn gateway.main:app --reload
```

The default `RAZORPAY_MODE=mock` runs an in-process Razorpay simulator with fault
injection — the failure demos and the whole test suite run deterministically and key-free.
Set `CHECKPOST_RAZORPAY_MODE=test` plus test-mode keys in `.env` to hit real Razorpay
test APIs (same interface, same code paths).

API docs at `http://localhost:8000/docs`. Agent endpoints authenticate with the
`X-Agent-Key` passports printed by the seed script.

**Merchant dashboard** (traffic, decision timelines, approval queue, policy, audit log):

```bash
npm --prefix dashboard install && npm --prefix dashboard run dev   # http://localhost:5173
```

**Demo buyer agent** — seven scripted scenarios (happy path, policy block with
alternative, Rx approval, controlled substance, catalog injection, ambiguous timeout,
duplicate webhook), or a real LLM agent that shops with tools:

```bash
python -m buyer_agent.pillpal all
python -m buyer_agent.pillpal agent "refill my mother's diabetes supplies under 2000 rupees"
```


## Live modes

- **LLM advisory checks** (intent–cart matching, injection screening, policy compiler):
  set `CHECKPOST_LLM_ENABLED=true` and `CHECKPOST_GEMINI_API_KEY` in `.env`. Get a free
  key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — the default
  model (`gemini-3.5-flash-lite`) runs on Google AI Studio's free tier, so the whole project
  is reproducible without paid credentials. (Flash-Lite is the default deliberately: the
  free tier caps full Flash models at ~20 requests/day, which the eval suite alone would
  exhaust; Lite's daily quota is far larger and the advisory verdicts don't need more
  model.) Without a key the gateway **fails closed** —
  advisory checks abstain and proposals escalate to human review
  (`CHECKPOST_LLM_FAILURE_POLICY` controls this posture).
- **Real Razorpay test mode:** `CHECKPOST_RAZORPAY_MODE=test` plus
  `CHECKPOST_RAZORPAY_KEY_ID` / `CHECKPOST_RAZORPAY_KEY_SECRET`. Same interface, same
  code paths as the simulator; point a test-mode webhook at `/webhooks/razorpay` with
  your `CHECKPOST_RAZORPAY_WEBHOOK_SECRET`.

## Tests

```bash
.venv/Scripts/python -m pytest tests -q
```

- `tests/unit` — policy engine and mandate verification, exhaustively.
- `tests/integration` — full HTTP flows: happy path, blocks with alternatives, human
  approval → payment link, duplicate + out-of-order webhooks.
- `tests/safety` — failure-first: ambiguous-timeout reconciliation without duplicate
  orders, bounded retry exhaustion, catalog injection quarantine, and the invariant test
  that an LLM verdict cannot override a deterministic block.

## Evaluation

```bash
python -m scripts.run_evals
```

Runs 12 deterministic scenarios (15 with a live LLM key) against a fresh gateway and
writes measured results to [docs/evaluation-results.md](docs/evaluation-results.md).
Every number comes from an executed scenario in that run — nothing is hardcoded.
Latest run: **15/15** with a live Gemini key — the 12 deterministic scenarios plus live
injection quarantine, off-purpose-cart escalation, and policy compilation from prose.
Without a key the same command runs **12/12** and skips the three LLM scenarios, which is
exactly what CI verifies on every push.

Headline results: zero unauthorized money actions, zero duplicate orders under ambiguous
timeouts, 100% duplicate-webhook suppression, and fail-closed behaviour under LLM outage.

## Docs

- [docs/architecture.md](docs/architecture.md) — the pipeline, components, Razorpay integration map
- [docs/safety.md](docs/safety.md) — boundary table, injection posture, deliberate non-choices
- [docs/failure-modes.md](docs/failure-modes.md) — the five failure classes and how each is handled
- [docs/decisions.md](docs/decisions.md) — decision log with rejected alternatives
- [docs/evaluation-results.md](docs/evaluation-results.md) — measured eval output

## Repo map

```text
gateway/          the product: api/ core/ domain/ trust/ policy/ llm/ payments/ audit/
buyer_agent/      PillPal — scripted demo scenarios + real tool-calling LLM agent
dashboard/        React merchant console (Vite, no UI framework)
scripts/          seed.py (demo world) · run_evals.py (measured evaluation)
tests/            unit/ integration/ safety/
docs/             architecture · safety · failure-modes · decisions · eval results
```
