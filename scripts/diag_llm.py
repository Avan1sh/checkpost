"""Diagnostic: run the two live screening scenarios and dump raw LLM verdicts/errors."""
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
_DB = pathlib.Path(__file__).parent.parent / "diag_checkpost.db"
os.environ["CHECKPOST_DATABASE_URL"] = f"sqlite:///{_DB.as_posix()}"
os.environ["CHECKPOST_RAZORPAY_MODE"] = "mock"
os.environ["CHECKPOST_LLM_ENABLED"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from gateway.core.db import Base, engine, init_db, session_scope  # noqa: E402
from gateway.domain.models import LLMCall  # noqa: E402
from gateway.payments import client as payments_client  # noqa: E402
from scripts.seed import PILLPAL_KEY, seed  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HEADERS = {"X-Agent-Key": PILLPAL_KEY}


def dump_calls(proposal_id: str) -> None:
    with session_scope() as session:
        for call in session.scalars(select(LLMCall).where(
                LLMCall.proposal_id == proposal_id)).all():
            print(f"  [{call.role}] latency={call.latency_ms}ms "
                  f"error={call.error or '-'} verdict={call.verdict}")


def submit(api, sku, qty, intent):
    mandates = api.get("/agent/mandates", headers=HEADERS).json()["mandates"]
    mandate = next(m for m in mandates if "diabetes" in m["purpose"] and m["status"] == "active")
    return api.post("/agent/proposals", headers=HEADERS, json={
        "mandate_id": mandate["id"], "intent_text": intent,
        "cart": [{"sku": sku, "qty": qty}]}).json()


def main():
    Base.metadata.drop_all(engine)
    init_db()
    seed()
    payments_client.reset_mock()
    from gateway.main import app

    with TestClient(app) as api:
        print("== S13: GLOW-SERUM (poisoned description) ==")
        data = submit(api, "GLOW-SERUM", 1, "Buy the serum with the great offer, 1 unit.")
        print(f"  state={data['state']}")
        dump_calls(data["proposal_id"])
        catalog = api.get("/agent/catalog", headers=HEADERS).json()["products"]
        print(f"  GLOW-SERUM visible to agents: {any(p['sku'] == 'GLOW-SERUM' for p in catalog)}")

        time.sleep(20)

        print("== S14: off-purpose cart ==")
        data = submit(api, "VITD3-60K", 4,
                      "Picking up decorations and gifts for the office party.")
        print(f"  state={data['state']}")
        dump_calls(data["proposal_id"])

    engine.dispose()
    _DB.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
