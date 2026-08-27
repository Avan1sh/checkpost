"""Deterministic policy evaluation — the only authority that can approve money movement.

Pure functions over (priced cart, rules, context). No I/O, no LLM, no clock reads:
everything time- or history-dependent arrives pre-computed in PolicyContext so that
evaluation is reproducible and exhaustively unit-testable.

Verdict semantics:
- "block":     at least one hard violation. A safe alternative cart is offered when one
               can be constructed deterministically (clamped quantities, removed lines).
- "escalate":  nothing hard is violated, but at least one rule demands human review
               (Rx-gated products, approval categories, value over approval threshold).
- "authorize": no violations, no escalations. Only this result can lead to an order.
"""
from gateway.policy.schema import (
    PolicyContext,
    PolicyRuleSet,
    PolicyVerdict,
    PricedLine,
    SafeAlternative,
    Violation,
)


def evaluate(cart: list[PricedLine], rules: PolicyRuleSet, ctx: PolicyContext) -> PolicyVerdict:
    return _evaluate(cart, rules, ctx, build_alternative=True)


def _evaluate(cart: list[PricedLine], rules: PolicyRuleSet, ctx: PolicyContext,
              *, build_alternative: bool) -> PolicyVerdict:
    total = sum(line.line_paise for line in cart)
    violations: list[Violation] = []
    escalations: list[Violation] = []

    # --- hard violations -------------------------------------------------
    for line in cart:
        if line.category in rules.blocked_categories:
            violations.append(Violation(
                rule="blocked_category", sku=line.sku,
                message=f"'{line.name}' is in category '{line.category}', not sold to agents."))

        sku_cap = min(
            line.max_qty_per_order,
            rules.per_sku_qty_caps.get(line.sku, line.max_qty_per_order),
        )
        if line.qty > sku_cap:
            violations.append(Violation(
                rule="sku_qty_cap", sku=line.sku,
                message=f"Quantity {line.qty} of '{line.name}' exceeds the cap of {sku_cap} per order."))

    category_totals: dict[str, int] = {}
    for line in cart:
        category_totals[line.category] = category_totals.get(line.category, 0) + line.qty
    for category, cap in rules.category_qty_caps.items():
        if category_totals.get(category, 0) > cap:
            violations.append(Violation(
                rule="category_qty_cap",
                message=f"Total of {category_totals[category]} units in '{category}' exceeds the cap of {cap} per order."))

    if rules.max_order_paise is not None and total > rules.max_order_paise:
        violations.append(Violation(
            rule="max_order_value",
            message=f"Order total ₹{total / 100:.2f} exceeds the per-order limit of ₹{rules.max_order_paise / 100:.2f}."))

    if rules.agent_daily_order_cap is not None and ctx.agent_orders_today >= rules.agent_daily_order_cap:
        violations.append(Violation(
            rule="agent_daily_order_cap",
            message=f"Agent has already placed {ctx.agent_orders_today} orders today (cap {rules.agent_daily_order_cap})."))

    if (rules.agent_daily_value_cap_paise is not None
            and ctx.agent_value_today_paise + total > rules.agent_daily_value_cap_paise):
        violations.append(Violation(
            rule="agent_daily_value_cap",
            message=(f"Order would take today's agent spend to "
                     f"₹{(ctx.agent_value_today_paise + total) / 100:.2f}, over the daily cap of "
                     f"₹{rules.agent_daily_value_cap_paise / 100:.2f}.")))

    # --- escalations (human review) --------------------------------------
    for line in cart:
        if line.requires_approval:
            escalations.append(Violation(
                rule="product_requires_approval", sku=line.sku,
                message=f"'{line.name}' requires pharmacist review before sale."))
        elif line.category in rules.approval_required_categories:
            escalations.append(Violation(
                rule="category_requires_approval", sku=line.sku,
                message=f"Category '{line.category}' requires human review."))

    if rules.approval_over_paise is not None and total > rules.approval_over_paise:
        escalations.append(Violation(
            rule="value_requires_approval",
            message=f"Order total ₹{total / 100:.2f} is above the ₹{rules.approval_over_paise / 100:.2f} auto-approval threshold."))

    if violations:
        return PolicyVerdict(
            result="block",
            violations=violations,
            escalations=escalations,
            safe_alternative=_build_alternative(cart, rules, ctx) if build_alternative else None,
        )
    if escalations:
        return PolicyVerdict(result="escalate", escalations=escalations)
    return PolicyVerdict(result="authorize")


def _build_alternative(
    cart: list[PricedLine], rules: PolicyRuleSet, ctx: PolicyContext,
) -> SafeAlternative | None:
    """Construct the largest compliant sub-cart by deterministic clamping and removal.

    Strategy: drop blocked-category lines, clamp quantities to caps, then — if a value cap
    is still exceeded — remove the most expensive lines until it fits. If the result is
    empty or itself fails evaluation (e.g. a velocity cap no cart can satisfy), offer nothing.
    """
    lines: list[PricedLine] = []
    for line in cart:
        if line.category in rules.blocked_categories:
            continue
        sku_cap = min(line.max_qty_per_order, rules.per_sku_qty_caps.get(line.sku, line.max_qty_per_order))
        qty = min(line.qty, sku_cap)
        cat_cap = rules.category_qty_caps.get(line.category)
        if cat_cap is not None:
            already = sum(l.qty for l in lines if l.category == line.category)
            qty = min(qty, max(cat_cap - already, 0))
        if qty <= 0:
            continue
        lines.append(line.model_copy(update={"qty": qty, "line_paise": qty * line.unit_paise}))

    def total_of(ls: list[PricedLine]) -> int:
        return sum(l.line_paise for l in ls)

    caps = [c for c in (rules.max_order_paise,
                        None if rules.agent_daily_value_cap_paise is None
                        else rules.agent_daily_value_cap_paise - ctx.agent_value_today_paise)
            if c is not None]
    value_cap = min(caps) if caps else None
    if value_cap is not None:
        lines.sort(key=lambda l: l.line_paise)  # keep cheap lines, drop expensive ones
        while lines and total_of(lines) > value_cap:
            lines.pop()

    if not lines:
        return None
    verdict = _evaluate(lines, rules, ctx, build_alternative=False)
    if verdict.result == "block":
        return None
    note = "Largest compliant version of the requested cart."
    if verdict.result == "escalate":
        note += " Note: this alternative still requires human review."
    return SafeAlternative(cart=lines, total_paise=total_of(lines), note=note)
