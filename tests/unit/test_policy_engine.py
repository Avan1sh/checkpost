from gateway.policy.engine import evaluate
from gateway.policy.schema import PolicyContext, PolicyRuleSet, PricedLine


def line(sku="ORS-200", category="otc", qty=1, unit=12000, rx=False, max_qty=5, name=None):
    return PricedLine(sku=sku, name=name or sku, category=category, qty=qty,
                      unit_paise=unit, line_paise=qty * unit,
                      requires_approval=rx, max_qty_per_order=max_qty)


RULES = PolicyRuleSet(
    max_order_paise=500_000,
    approval_over_paise=200_000,
    blocked_categories=["controlled"],
    approval_required_categories=["prescription"],
    category_qty_caps={"otc": 10},
    agent_daily_order_cap=10,
    agent_daily_value_cap_paise=1_000_000,
)
CTX = PolicyContext()


def test_clean_cart_authorizes():
    verdict = evaluate([line(qty=2)], RULES, CTX)
    assert verdict.result == "authorize"
    assert not verdict.violations and not verdict.escalations


def test_sku_qty_cap_blocks_with_clamped_alternative():
    verdict = evaluate([line(qty=9, max_qty=5)], RULES, CTX)
    assert verdict.result == "block"
    assert any(v.rule == "sku_qty_cap" for v in verdict.violations)
    assert verdict.safe_alternative is not None
    assert verdict.safe_alternative.cart[0].qty == 5


def test_blocked_category_blocks_and_drops_from_alternative():
    cart = [line(), line(sku="CODEINE-SYP", category="controlled")]
    verdict = evaluate(cart, RULES, CTX)
    assert verdict.result == "block"
    assert any(v.rule == "blocked_category" for v in verdict.violations)
    skus = [l.sku for l in verdict.safe_alternative.cart]
    assert "CODEINE-SYP" not in skus and "ORS-200" in skus


def test_order_value_cap_blocks_and_trims_alternative():
    cart = [line(sku="A", unit=300_000, qty=1, max_qty=5), line(sku="B", unit=300_000, qty=1, max_qty=5)]
    verdict = evaluate(cart, RULES, CTX)
    assert verdict.result == "block"
    assert any(v.rule == "max_order_value" for v in verdict.violations)
    assert verdict.safe_alternative.total_paise <= 500_000


def test_daily_velocity_blocks_without_alternative():
    ctx = PolicyContext(agent_orders_today=10)
    verdict = evaluate([line()], RULES, ctx)
    assert verdict.result == "block"
    assert any(v.rule == "agent_daily_order_cap" for v in verdict.violations)
    assert verdict.safe_alternative is None  # no cart can satisfy a velocity cap


def test_daily_value_cap_counts_prior_spend():
    ctx = PolicyContext(agent_value_today_paise=990_000)
    verdict = evaluate([line(qty=2)], RULES, ctx)  # 24,000 paise pushes past 1,000,000
    assert verdict.result == "block"
    assert any(v.rule == "agent_daily_value_cap" for v in verdict.violations)


def test_rx_product_escalates_not_blocks():
    verdict = evaluate([line(sku="METFORMIN-500", category="prescription", rx=True, unit=3200)],
                       RULES, CTX)
    assert verdict.result == "escalate"
    assert any(v.rule == "product_requires_approval" for v in verdict.escalations)


def test_high_value_escalates():
    verdict = evaluate([line(sku="BP", category="wellness", unit=219_900, qty=1, max_qty=1)],
                       RULES, CTX)
    assert verdict.result == "escalate"
    assert any(v.rule == "value_requires_approval" for v in verdict.escalations)


def test_alternative_notes_when_it_still_needs_review():
    # Over qty cap AND contains an Rx item: clamped alternative still requires review.
    cart = [line(qty=9, max_qty=5),
            line(sku="METFORMIN-500", category="prescription", rx=True, unit=3200)]
    verdict = evaluate(cart, RULES, CTX)
    assert verdict.result == "block"
    assert verdict.safe_alternative is not None
    assert "review" in verdict.safe_alternative.note


def test_category_qty_cap():
    verdict = evaluate([line(qty=5, max_qty=10), line(sku="PARA", qty=6, max_qty=10)], RULES, CTX)
    assert verdict.result == "block"
    assert any(v.rule == "category_qty_cap" for v in verdict.violations)


def test_no_rules_means_authorize():
    verdict = evaluate([line(qty=3)], PolicyRuleSet(), CTX)
    assert verdict.result == "authorize"
