"""Agent passports and mandate verification.

Demo-grade trust layer with the same *shape* as AP2 mandates / NPCI UAP delegation:
a mandate binds (agent, principal, purpose, spend cap, category scope, expiry) under a
signature. Here the signature is HMAC-SHA256 under a merchant-held secret; in production
this slot is filled by AP2 verifiable credentials or UAP attestations (docs/decisions.md D5).
"""
import hashlib
import hmac
from datetime import datetime, timezone

from gateway.core.config import get_settings
from gateway.domain.models import Mandate


def hash_passport(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _canonical(agent_id: str, principal: str, purpose: str, max_amount_paise: int,
               currency: str, allowed_categories: list[str], expires_at: datetime) -> bytes:
    cats = ",".join(sorted(allowed_categories))
    ts = int(expires_at.replace(tzinfo=expires_at.tzinfo or timezone.utc).timestamp())
    return f"{agent_id}|{principal}|{purpose}|{max_amount_paise}|{currency}|{cats}|{ts}".encode()


def sign_mandate(agent_id: str, principal: str, purpose: str, max_amount_paise: int,
                 currency: str, allowed_categories: list[str], expires_at: datetime) -> str:
    secret = get_settings().mandate_signing_secret.encode()
    msg = _canonical(agent_id, principal, purpose, max_amount_paise, currency,
                     allowed_categories, expires_at)
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


class MandateRejection(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(f"{code}: {message}")


def verify_mandate(mandate: Mandate, *, order_total_paise: int,
                   cart_categories: set[str], now: datetime | None = None) -> None:
    """Raise MandateRejection unless this order is within the mandate's authority."""
    now = now or datetime.now(timezone.utc)

    if mandate.status != "active":
        raise MandateRejection("mandate_revoked", "The mandate has been revoked by its principal.")

    expected = sign_mandate(mandate.agent_id, mandate.principal, mandate.purpose,
                            mandate.max_amount_paise, mandate.currency,
                            list(mandate.allowed_categories or []), mandate.expires_at)
    if not hmac.compare_digest(expected, mandate.signature):
        raise MandateRejection("mandate_signature_invalid",
                               "Mandate signature does not verify — possible tampering.")

    expires = mandate.expires_at if mandate.expires_at.tzinfo else mandate.expires_at.replace(tzinfo=timezone.utc)
    if now >= expires:
        raise MandateRejection("mandate_expired", f"Mandate expired at {expires.isoformat()}.")

    remaining = mandate.max_amount_paise - mandate.spent_paise
    if order_total_paise > remaining:
        raise MandateRejection(
            "mandate_cap_exceeded",
            f"Order total ₹{order_total_paise / 100:.2f} exceeds the mandate's remaining "
            f"authority of ₹{remaining / 100:.2f}.")

    allowed = set(mandate.allowed_categories or [])
    if allowed:
        outside = cart_categories - allowed
        if outside:
            raise MandateRejection(
                "mandate_scope_exceeded",
                f"Cart contains categories outside the mandate's scope: {sorted(outside)}.")
