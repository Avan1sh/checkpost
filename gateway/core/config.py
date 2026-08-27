"""Application configuration, loaded from environment / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CHECKPOST_", extra="ignore")

    database_url: str = "sqlite:///./checkpost.db"

    # "mock" runs the in-process simulator (no keys needed); "test" hits Razorpay test mode.
    razorpay_mode: str = "mock"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = "whsec_demo"

    # Secret used to sign/verify agent mandates (demo-grade HMAC trust layer, see docs/decisions.md D5).
    mandate_signing_secret: str = "mandate_demo_secret"

    # Advisory LLM provider: Google AI Studio (Gemini). The advisory layer is
    # provider-swappable by design — see docs/decisions.md D9.
    gemini_api_key: str = ""
    llm_model: str = "gemini-2.5-flash"
    llm_max_retries: int = 3  # free-tier rate limits (429) are retried with backoff
    # When false (default for tests/evals without a key), LLM checks abstain.
    llm_enabled: bool = False
    # What an abstaining/failed advisory check does: "escalate" (fail-closed, default —
    # proposals go to human review) or "proceed" (deterministic checks alone decide).
    llm_failure_policy: str = "escalate"

    reconciler_interval_seconds: float = 5.0
    reconciler_max_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
