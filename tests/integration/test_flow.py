"""End-to-end flows through the HTTP API with the mock Razorpay simulator."""
import hashlib
import hmac
import json

from gateway.core.config import get_settings


def send_webhook(api, event_id: str, event: str, payload: dict):
    body = json.dumps({"event": event, "payload": payload}).encode()
    signature = hmac.new(get_settings().razorpay_webhook_secret.encode(),
                         body, hashlib.sha256).hexdigest()
    return api.post("/webhooks/razorpay", content=body, headers={
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": event_id,
        "Content-Type": "application/json",
    })


def active_mandate(api, headers, purpose_word="diabetes"):
    mandates = api.get("/agent/mandates", headers=headers).json()["mandates"]
    return next(m for m in mandates if purpose_word in m["purpose"] and m["status"] == "active")


def test_happy_path_then_duplicate_and_out_of_order_webhooks(api, pillpal_headers, mock_rzp):
    mandate = active_mandate(api, pillpal_headers)
    response = api.post("/agent/proposals", headers=pillpal_headers, json={
        "mandate_id": mandate["id"],
        "intent_text": "Monthly refill: two boxes of glucometer strips for my mother.",
        "cart": [{"sku": "GLU-STRIPS-50", "qty": 2}],
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["state"] == "awaiting_payment"
    assert data["total_paise"] == 2 * 84_900
    order_id = data["razorpay_order_id"]
    assert order_id

    # Payment happens on Razorpay; webhook triggers verification against API truth.
    mock_rzp.simulate_payment(order_id)
    hook = send_webhook(api, "evt_1", "payment.captured",
                        {"payment": {"entity": {"order_id": order_id, "status": "captured"}}})
    assert hook.json()["state"] == "paid"

    # Duplicate delivery (documented Razorpay behaviour) is acked and dropped.
    dup = send_webhook(api, "evt_1", "payment.captured",
                       {"payment": {"entity": {"order_id": order_id, "status": "captured"}}})
    assert dup.json()["status"] == "duplicate_ignored"

    # Out-of-order payment.failed after PAID must not regress the state.
    late = send_webhook(api, "evt_2", "payment.failed",
                        {"payment": {"entity": {"order_id": order_id, "status": "failed"}}})
    assert late.json()["state"] == "paid"

    detail = api.get(f"/merchant/proposals/{data['proposal_id']}").json()
    assert detail["state"] == "paid"
    actions = [e["action"] for e in detail["audit_events"]]
    assert "webhook.out_of_order_ignored" in actions


def test_policy_block_offers_safe_alternative(api, pillpal_headers):
    mandate = active_mandate(api, pillpal_headers)
    response = api.post("/agent/proposals", headers=pillpal_headers, json={
        "mandate_id": mandate["id"],
        "intent_text": "Stocking up on paracetamol.",
        "cart": [{"sku": "PARA-650", "qty": 9}],
    })
    data = response.json()
    assert data["state"] == "blocked"
    verdict = data["decision"]["verdict"]
    assert any(v["rule"] == "sku_qty_cap" for v in verdict["violations"])
    assert verdict["safe_alternative"]["cart"][0]["qty"] == 3
    assert data["razorpay_order_id"] is None  # blocked proposals never touch Razorpay


def test_expired_mandate_rejected_before_policy(api, pillpal_headers):
    mandates = api.get("/agent/mandates", headers=pillpal_headers).json()["mandates"]
    expired = next(m for m in mandates if "cold and fever" in m["purpose"])
    response = api.post("/agent/proposals", headers=pillpal_headers, json={
        "mandate_id": expired["id"],
        "intent_text": "Fever purchase.",
        "cart": [{"sku": "PARA-650", "qty": 1}],
    })
    data = response.json()
    assert data["state"] == "rejected"
    assert data["decision"]["code"] == "mandate_expired"


def test_rx_escalation_human_approval_payment_link(api, pillpal_headers, mock_rzp):
    mandate = active_mandate(api, pillpal_headers)
    response = api.post("/agent/proposals", headers=pillpal_headers, json={
        "mandate_id": mandate["id"],
        "intent_text": "Metformin refill for my mother, prescription on file.",
        "cart": [{"sku": "METFORMIN-500", "qty": 2}],
    })
    data = response.json()
    assert data["state"] == "pending_approval"

    queue = api.get("/merchant/approvals").json()["approvals"]
    approval = next(a for a in queue if a["proposal_id"] == data["proposal_id"])
    decided = api.post(f"/merchant/approvals/{approval['approval_id']}/decide",
                       json={"approve": True, "reviewer": "Dr. Nair",
                             "note": "Prescription verified."})
    body = decided.json()
    assert body["state"] == "awaiting_payment"
    assert body["payment_link_url"]

    link_id = body["payment_link_url"].rsplit("/", 1)[-1]
    order_id, _payment = mock_rzp.simulate_link_payment(link_id)
    hook = send_webhook(api, "evt_link_1", "payment_link.paid",
                        {"payment_link": {"entity": {"id": link_id, "order_id": order_id}}})
    assert hook.json()["state"] == "paid"


def test_denied_approval_ends_the_proposal(api, pillpal_headers):
    mandate = active_mandate(api, pillpal_headers)
    data = api.post("/agent/proposals", headers=pillpal_headers, json={
        "mandate_id": mandate["id"],
        "intent_text": "Metformin refill.",
        "cart": [{"sku": "METFORMIN-500", "qty": 1}],
    }).json()
    approval = api.get("/merchant/approvals").json()["approvals"][0]
    decided = api.post(f"/merchant/approvals/{approval['approval_id']}/decide",
                       json={"approve": False, "reviewer": "Dr. Nair",
                             "note": "No prescription on file."})
    assert decided.json()["state"] == "denied"
    again = api.post(f"/merchant/approvals/{approval['approval_id']}/decide",
                     json={"approve": True, "reviewer": "Mallory"})
    assert again.status_code == 409  # decisions are single-shot


def test_bad_webhook_signature_rejected(api):
    body = json.dumps({"event": "payment.captured", "payload": {}}).encode()
    response = api.post("/webhooks/razorpay", content=body, headers={
        "X-Razorpay-Signature": "forged", "X-Razorpay-Event-Id": "evt_x",
        "Content-Type": "application/json"})
    assert response.status_code == 400
