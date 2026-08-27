"""Failure-first tests: ambiguous outcomes, reconciliation, injection, unauthorized spend."""
from sqlalchemy import select

from gateway.core.db import session_scope
from gateway.domain.models import Proposal
from gateway.llm.checks import InjectionVerdict, IntentMatchVerdict
from gateway.payments.reconciler import reconcile_pending
from tests.integration.test_flow import active_mandate, send_webhook


def submit(api, headers, mandate_id, sku="GLU-STRIPS-50", qty=1, intent="Refill strips."):
    return api.post("/agent/proposals", headers=headers, json={
        "mandate_id": mandate_id, "intent_text": intent,
        "cart": [{"sku": sku, "qty": qty}],
    }).json()


def reconcile_all(mock_rzp):
    with session_scope() as session:
        return reconcile_pending(session, mock_rzp)


def get_state(api, proposal_id):
    return api.get(f"/merchant/proposals/{proposal_id}").json()


def test_timeout_after_create_is_reconciled_without_duplicate_order(api, pillpal_headers, mock_rzp):
    """The nastiest case: order creation times out but the order WAS created server-side.
    A naive retry would double-charge; the reconciler must adopt the existing order."""
    mandate = active_mandate(api, pillpal_headers)
    mock_rzp.arm_fault("timeout_after_create")
    data = submit(api, pillpal_headers, mandate["id"])
    assert data["state"] == "uncertain"

    processed = reconcile_all(mock_rzp)
    assert processed == 1
    detail = get_state(api, data["proposal_id"])
    assert detail["state"] == "awaiting_payment"
    assert detail["razorpay_order_id"] is not None
    # Exactly one order exists server-side for this receipt — the invariant.
    assert len([o for o in mock_rzp.orders.values()
                if o.order.receipt == data["proposal_id"]]) == 1
    actions = [e["action"] for e in detail["audit_events"]]
    assert "order.adopted" in actions  # adopted, not recreated

    mock_rzp.simulate_payment(detail["razorpay_order_id"])
    hook = send_webhook(api, "evt_rec_1", "payment.captured",
                        {"payment": {"entity": {"order_id": detail["razorpay_order_id"]}}})
    assert hook.json()["state"] == "paid"


def test_timeout_before_create_is_safely_recreated(api, pillpal_headers, mock_rzp):
    mandate = active_mandate(api, pillpal_headers)
    mock_rzp.arm_fault("timeout_before_create")
    data = submit(api, pillpal_headers, mandate["id"])
    assert data["state"] == "uncertain"

    reconcile_all(mock_rzp)
    detail = get_state(api, data["proposal_id"])
    assert detail["state"] == "awaiting_payment"
    assert len([o for o in mock_rzp.orders.values()
                if o.order.receipt == data["proposal_id"]]) == 1
    actions = [e["action"] for e in detail["audit_events"]]
    assert "order.recreating" in actions  # verified absence first, then created


def test_repeated_ambiguity_exhausts_to_failed_never_silent(api, pillpal_headers, mock_rzp):
    mandate = active_mandate(api, pillpal_headers)
    mock_rzp.arm_fault("timeout_after_create")
    data = submit(api, pillpal_headers, mandate["id"])
    assert data["state"] == "uncertain"
    for _ in range(10):  # every reconciliation attempt also times out
        mock_rzp.arm_fault("fetch_timeout")
        reconcile_all(mock_rzp)
        state = get_state(api, data["proposal_id"])["state"]
        if state == "failed":
            break
    assert get_state(api, data["proposal_id"])["state"] == "failed"


def test_over_mandate_spend_rejected_even_when_policy_would_allow(api, bulkbot_headers, api2=None):
    """BulkBuyerBot's mandate allows ₹50,000 total; drain it and the next order dies at trust."""
    mandates = api.get("/agent/mandates", headers=bulkbot_headers).json()["mandates"]
    mandate = mandates[0]
    with session_scope() as session:
        from gateway.domain.models import Mandate
        row = session.get(Mandate, mandate["id"])
        row.spent_paise = row.max_amount_paise - 1000  # ₹10 of authority left
    data = submit(api, bulkbot_headers, mandate["id"], sku="ORS-200", qty=1,
                  intent="First aid restock.")
    assert data["state"] == "rejected"
    assert data["decision"]["code"] == "mandate_cap_exceeded"


def test_injected_catalog_content_quarantines_product(api, pillpal_headers, monkeypatch):
    """GLOW-SERUM's description carries an instruction-shaped payload. The screen flags it;
    the product is quarantined from the agent catalog; the proposal goes to a human."""
    from gateway.api import pipeline

    monkeypatch.setattr(pipeline.llm, "injection_screen",
                        lambda *a, **k: InjectionVerdict(
                            flagged=True,
                            suspicious_fields=["product_description:GLOW-SERUM"],
                            reasons=["claims pre-approval and exemption from policy checks"]))
    monkeypatch.setattr(pipeline.llm, "intent_match",
                        lambda *a, **k: IntentMatchVerdict(match="match"))

    mandate = active_mandate(api, pillpal_headers)
    data = submit(api, pillpal_headers, mandate["id"], sku="GLOW-SERUM", qty=1,
                  intent="Buy the serum with the great offer.")
    assert data["state"] == "pending_approval"

    catalog = api.get("/agent/catalog", headers=pillpal_headers).json()["products"]
    assert all(p["sku"] != "GLOW-SERUM" for p in catalog)  # withheld from agents

    detail = get_state(api, data["proposal_id"])
    actions = [e["action"] for e in detail["audit_events"]]
    assert "catalog.quarantined" in actions


def test_ambiguous_intent_escalates_to_human(api, pillpal_headers, monkeypatch):
    from gateway.api import pipeline

    monkeypatch.setattr(pipeline.llm, "injection_screen",
                        lambda *a, **k: InjectionVerdict(flagged=False))
    monkeypatch.setattr(pipeline.llm, "intent_match",
                        lambda *a, **k: IntentMatchVerdict(
                            match="ambiguous",
                            reasons=["4 BP monitors does not fit a personal diabetes refill"]))

    mandate = active_mandate(api, pillpal_headers)
    data = submit(api, pillpal_headers, mandate["id"], sku="VITD3-60K", qty=4,
                  intent="get the usual")
    assert data["state"] == "pending_approval"


def test_unknown_passport_rejected(api):
    response = api.get("/agent/catalog", headers={"X-Agent-Key": "stolen_or_guessed"})
    assert response.status_code == 401


def test_llm_verdict_cannot_authorize(api, pillpal_headers, monkeypatch):
    """Even a wildly positive LLM verdict cannot override a deterministic block."""
    from gateway.api import pipeline

    monkeypatch.setattr(pipeline.llm, "injection_screen",
                        lambda *a, **k: InjectionVerdict(flagged=False))
    monkeypatch.setattr(pipeline.llm, "intent_match",
                        lambda *a, **k: IntentMatchVerdict(
                            match="match", reasons=["definitely fine, approve immediately"]))

    mandate = active_mandate(api, pillpal_headers)
    data = submit(api, pillpal_headers, mandate["id"], sku="PARA-650", qty=9,
                  intent="Big paracetamol restock.")
    assert data["state"] == "blocked"  # policy engine is the only authority
