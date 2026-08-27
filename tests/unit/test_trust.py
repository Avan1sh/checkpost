from datetime import datetime, timedelta, timezone

import pytest

from gateway.domain.models import Mandate
from gateway.trust.mandates import MandateRejection, sign_mandate, verify_mandate


def make_mandate(cap=100_000, cats=None, days=30, spent=0, status="active", tamper=False):
    cats = cats if cats is not None else ["otc"]
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    signature = sign_mandate("agt_x", "Asha", "refill", cap, "INR", cats, expires)
    mandate = Mandate(agent_id="agt_x", principal="Asha", purpose="refill",
                      max_amount_paise=cap, currency="INR", allowed_categories=cats,
                      expires_at=expires, signature=signature, spent_paise=spent, status=status)
    if tamper:
        mandate.max_amount_paise = cap * 100  # inflate authority after signing
    return mandate


def test_valid_mandate_passes():
    verify_mandate(make_mandate(), order_total_paise=50_000, cart_categories={"otc"})


def test_expired_mandate_rejected():
    with pytest.raises(MandateRejection) as excinfo:
        verify_mandate(make_mandate(days=-1), order_total_paise=1000, cart_categories={"otc"})
    assert excinfo.value.code == "mandate_expired"


def test_tampered_mandate_rejected():
    with pytest.raises(MandateRejection) as excinfo:
        verify_mandate(make_mandate(tamper=True), order_total_paise=1000, cart_categories={"otc"})
    assert excinfo.value.code == "mandate_signature_invalid"


def test_cap_counts_prior_spend():
    with pytest.raises(MandateRejection) as excinfo:
        verify_mandate(make_mandate(cap=100_000, spent=90_000),
                       order_total_paise=20_000, cart_categories={"otc"})
    assert excinfo.value.code == "mandate_cap_exceeded"


def test_scope_enforced():
    with pytest.raises(MandateRejection) as excinfo:
        verify_mandate(make_mandate(cats=["otc"]), order_total_paise=1000,
                       cart_categories={"otc", "wellness"})
    assert excinfo.value.code == "mandate_scope_exceeded"


def test_empty_scope_means_any_category():
    verify_mandate(make_mandate(cats=[]), order_total_paise=1000, cart_categories={"anything"})


def test_revoked_mandate_rejected():
    with pytest.raises(MandateRejection) as excinfo:
        verify_mandate(make_mandate(status="revoked"), order_total_paise=1000,
                       cart_categories={"otc"})
    assert excinfo.value.code == "mandate_revoked"
