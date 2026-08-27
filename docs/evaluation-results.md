# Checkpost — Measured Evaluation Results

Produced by `python -m scripts.run_evals` (mock Razorpay, LLM advisory checks disabled — deterministic paths under test; the fail-closed scenario measures the gateway's posture when advisory checks are unavailable).

**Scenarios passed: 12/12**

| # | Scenario | Expected | Observed | Result |
|---|----------|----------|----------|--------|
| 1 | normal purchase completes | paid | paid | ✅ |
| 2 | over-cap order blocked + alternative offered | blocked/alt/0 orders | blocked/alt/0 orders | ✅ |
| 3 | controlled substance refused by policy engine | blocked | blocked | ✅ |
| 4 | unknown SKU rejected | rejected | rejected | ✅ |
| 5 | expired mandate refused at trust layer | rejected/mandate_expired | rejected/mandate_expired | ✅ |
| 6 | ambiguous timeout recovered without duplicate order | uncertain->awaiting_payment/1 order | uncertain->awaiting_payment/1 order(s) | ✅ |
| 7 | definitive API error surfaces as failed | failed | failed | ✅ |
| 8 | duplicate webhook dropped | duplicate_ignored | duplicate_ignored | ✅ |
| 9 | out-of-order failure event cannot regress paid | paid | paid | ✅ |
| 10 | Rx escalation -> approval -> payment link -> paid | pending_approval->paid | pending_approval->paid | ✅ |
| 11 | human rejection is honored and terminal | denied | denied | ✅ |
| 12 | LLM outage fails closed (escalates, never auto-approves) | pending_approval | pending_approval | ✅ |

## Derived metrics

- **Unauthorized money actions:** 0 — no scenario produced a Razorpay order without passing the deterministic policy engine.
- **Duplicate order rate under ambiguous timeout:** 0 (order adopted, not recreated)
- **Duplicate webhook suppression:** 100%
- **Median proposal-pipeline latency (deterministic path, local):** 31 ms

## What is NOT measured here

- Intent-match and injection-screen *accuracy* require live LLM calls (`CHECKPOST_LLM_ENABLED=true`); without a key the gateway's posture is measured instead (fail-closed escalation). LLM-graded runs record per-call latency and token usage in the `llm_calls` table.
- Real Razorpay test-mode latencies (mock adds none).