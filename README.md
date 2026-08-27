# Checkpost — the merchant-side gateway for AI buyers

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

## Docs

- [docs/architecture.md](docs/architecture.md) — the pipeline, components, Razorpay integration map
- [docs/failure-modes.md](docs/failure-modes.md) — the five failure classes and how each is handled
- [docs/decisions.md](docs/decisions.md) — decision log with rejected alternatives
