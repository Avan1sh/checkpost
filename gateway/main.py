"""Checkpost gateway — FastAPI application entry point."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gateway.core.config import get_settings
from gateway.core.db import init_db, session_scope
from gateway.payments.client import get_client
from gateway.payments.reconciler import reconcile_pending


async def _reconciler_loop() -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.reconciler_interval_seconds)
        try:
            with session_scope() as session:
                reconcile_pending(session, get_client())
        except Exception:  # the loop must survive anything; failures are in audit events
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(_reconciler_loop())
    yield
    task.cancel()


app = FastAPI(
    title="Checkpost",
    description="Merchant-side trust, policy and payment gateway for AI buyers.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)

from gateway.api.routes_agent import router as agent_router        # noqa: E402
from gateway.api.routes_merchant import router as merchant_router  # noqa: E402
from gateway.api.routes_webhooks import router as webhook_router   # noqa: E402

app.include_router(agent_router)
app.include_router(merchant_router)
app.include_router(webhook_router)


@app.get("/health")
def health():
    return {"status": "ok", "razorpay_mode": get_settings().razorpay_mode,
            "llm_enabled": get_settings().llm_enabled}
