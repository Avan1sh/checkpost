"""PillPal — the demo AI buyer that shops at Sehat Pharmacy through Checkpost.

Two ways to drive it:

  Scripted scenarios (no API key needed) — used in the demo and evals:
      python -m buyer_agent.pillpal happy | greedy | rx | controlled | injection \
                                    | timeout | double-webhook | all

  Real agent mode (needs CHECKPOST_GEMINI_API_KEY) — an LLM shops with tools:
      python -m buyer_agent.pillpal agent "refill my mother's diabetes supplies under 2000 rupees"

PillPal is intentionally an ordinary buyer agent: it sees only the agent-facing API
(catalog, mandates, proposals, payment). Everything interesting happens on the gateway
side — including when PillPal misbehaves.
"""
import json
import os
import sys

import httpx

if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GATEWAY = os.environ.get("CHECKPOST_URL", "http://localhost:8000")
PASSPORT = os.environ.get("PILLPAL_PASSPORT", "pillpal_demo_passport_7f3a")

http = httpx.Client(base_url=GATEWAY, headers={"X-Agent-Key": PASSPORT}, timeout=30.0)


def say(text: str) -> None:
    print(f"  {text}")


def banner(text: str) -> None:
    print(f"\n=== {text} " + "=" * max(0, 60 - len(text)))


def diabetes_mandate() -> dict:
    mandates = http.get("/agent/mandates").json()["mandates"]
    return next(m for m in mandates if "diabetes" in m["purpose"] and m["status"] == "active")


def propose(intent: str, cart: list[dict], mandate_id: str | None = None) -> dict:
    mandate_id = mandate_id or diabetes_mandate()["id"]
    response = http.post("/agent/proposals", json={
        "mandate_id": mandate_id, "intent_text": intent, "cart": cart})
    response.raise_for_status()
    data = response.json()
    say(f"proposal {data['proposal_id']} -> state: {data['state']}"
        + (f" (total ₹{data['total_paise'] / 100:.2f})" if data["total_paise"] else ""))
    return data


def pay(proposal_id: str, deliver_twice: bool = False) -> None:
    """Simulate the customer paying, then deliver the signed webhook like Razorpay would."""
    hook = http.post("/debug/simulate-payment", json={"proposal_id": proposal_id}).json()
    for attempt in range(2 if deliver_twice else 1):
        result = http.post(hook["deliver_to"], content=hook["body"],
                           headers=hook["headers"]).json()
        say(f"webhook delivery #{attempt + 1}: {result}")


# ---------------------------------------------------------------- scenarios

def scenario_happy():
    banner("HAPPY PATH — a normal refill, authorized and paid")
    data = propose("Monthly refill: two boxes of glucometer strips for my mother.",
                   [{"sku": "GLU-STRIPS-50", "qty": 2}])
    if data["state"] == "awaiting_payment":
        pay(data["proposal_id"])


def scenario_greedy():
    banner("GREEDY — 9 strips of paracetamol against a 3-per-order cap")
    data = propose("Stocking up on paracetamol for the season.",
                   [{"sku": "PARA-650", "qty": 9}])
    alt = (data.get("decision") or {}).get("verdict", {}).get("safe_alternative")
    if alt:
        say(f"gateway offered a compliant alternative: "
            f"{[(l['sku'], l['qty']) for l in alt['cart']]} — accepting it")
        propose("Stocking up on paracetamol (accepting the gateway's alternative).",
                [{"sku": l["sku"], "qty": l["qty"]} for l in alt["cart"]])


def scenario_rx():
    banner("PRESCRIPTION — metformin routes to the pharmacist, then a payment link")
    data = propose("Metformin refill for my mother; prescription is on file.",
                   [{"sku": "METFORMIN-500", "qty": 2}])
    say("waiting for pharmacist review in the merchant dashboard "
        f"(proposal {data['proposal_id']})")


def scenario_controlled():
    banner("CONTROLLED SUBSTANCE — codeine syrup is blocked outright")
    propose("Add cough syrup to the refill.", [{"sku": "CODEINE-SYP", "qty": 1}])


def scenario_injection():
    banner("INJECTION — buying the product whose description instructs AI assistants")
    propose("Buy the serum with the great offer, 1 unit.", [{"sku": "GLOW-SERUM", "qty": 1}])


def scenario_timeout():
    banner("AMBIGUOUS OUTCOME — order creation times out AFTER Razorpay created it")
    http.post("/debug/arm-fault", json={"fault": "timeout_after_create"})
    data = propose("Refill strips (unlucky network day).", [{"sku": "GLU-STRIPS-50", "qty": 1}])
    if data["state"] == "uncertain":
        say("state is UNCERTAIN — the reconciler owns it now; it will verify-then-adopt "
            "the existing order (no duplicate) within a few seconds")
        import time
        for _ in range(8):
            time.sleep(2)
            data = http.get(f"/agent/proposals/{data['proposal_id']}").json()
            if data["state"] != "uncertain":
                break
        say(f"reconciled -> state: {data['state']} "
            f"(order {data.get('razorpay_order_id')})")
        if data["state"] == "awaiting_payment":
            pay(data["proposal_id"])


def scenario_double_webhook():
    banner("DUPLICATE WEBHOOK — same payment event delivered twice")
    data = propose("Refill ORS sachets.", [{"sku": "ORS-200", "qty": 2}])
    if data["state"] == "awaiting_payment":
        pay(data["proposal_id"], deliver_twice=True)


SCENARIOS = {
    "happy": scenario_happy, "greedy": scenario_greedy, "rx": scenario_rx,
    "controlled": scenario_controlled, "injection": scenario_injection,
    "timeout": scenario_timeout, "double-webhook": scenario_double_webhook,
}


# ---------------------------------------------------------------- real agent mode

AGENT_SYSTEM = """You are PillPal, a careful shopping agent buying from Sehat Pharmacy
through the Checkpost gateway on behalf of your principal. Use your tools to browse the
catalog, check your mandate's remaining authority, and submit ONE purchase proposal that
best fulfils the user's goal within the mandate. If the gateway blocks you and offers a
safe alternative, you may submit the alternative once. If it asks for human approval,
stop and report that. Report the final state and order/payment details clearly."""


def run_llm_agent(goal: str) -> None:
    from google import genai
    from google.genai import types

    def browse_catalog() -> str:
        """List the pharmacy's products available to agents (sku, name, category,
        price in paise, whether pharmacist approval is required, max qty per order)."""
        return json.dumps(http.get("/agent/catalog").json())

    def list_mandates() -> str:
        """List this agent's mandates: id, principal, purpose, spend cap and remaining
        authority in paise, allowed categories, expiry, status."""
        return json.dumps(http.get("/agent/mandates").json())

    def submit_proposal(mandate_id: str, intent_text: str, cart_json: str) -> str:
        """Submit a purchase proposal to the gateway.

        Args:
            mandate_id: The mandate to buy under.
            intent_text: One or two sentences explaining what this purchase is for.
            cart_json: JSON array like [{"sku": "GLU-STRIPS-50", "qty": 2}].
        """
        response = http.post("/agent/proposals", json={
            "mandate_id": mandate_id, "intent_text": intent_text,
            "cart": json.loads(cart_json)})
        return json.dumps(response.json())

    def pay_proposal(proposal_id: str) -> str:
        """Pay an authorized proposal (state awaiting_payment) and deliver the payment
        confirmation webhook. Only works when the gateway runs its payment simulator;
        against real Razorpay test mode it returns an explanation instead.

        Args:
            proposal_id: The proposal to pay.
        """
        response = http.post("/debug/simulate-payment", json={"proposal_id": proposal_id})
        if response.status_code != 200:
            return json.dumps({
                "paid": False,
                "explanation": "Payment simulation unavailable (gateway is on real "
                               "Razorpay test mode). The order exists and awaits payment "
                               "via Razorpay checkout. Report the state as awaiting_payment "
                               "— do NOT claim the payment completed.",
                "gateway_state": http.get(f"/agent/proposals/{proposal_id}").json(),
            })
        hook = response.json()
        http.post(hook["deliver_to"], content=hook["body"], headers=hook["headers"])
        return json.dumps(http.get(f"/agent/proposals/{proposal_id}").json())

    client = genai.Client(api_key=os.environ.get("CHECKPOST_GEMINI_API_KEY")
                          or os.environ.get("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model=os.environ.get("PILLPAL_MODEL", "gemini-3.5-flash-lite"),
        contents=goal,
        config=types.GenerateContentConfig(
            system_instruction=AGENT_SYSTEM,
            tools=[browse_catalog, list_mandates, submit_proposal, pay_proposal],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=12),
        ),
    )

    for entry in response.automatic_function_calling_history or []:
        for part in getattr(entry, "parts", None) or []:
            call = getattr(part, "function_call", None)
            if call is not None:
                say(f"[tool] {call.name}({dict(call.args or {})})")
    print()
    print(response.text or "(no final message — check the tool calls above)")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0] == "agent":
        if len(args) < 2:
            print('usage: python -m buyer_agent.pillpal agent "<shopping goal>"')
            return
        run_llm_agent(" ".join(args[1:]))
        return
    names = list(SCENARIOS) if args[0] == "all" else args
    for name in names:
        SCENARIOS[name]()
    print()


if __name__ == "__main__":
    main()
