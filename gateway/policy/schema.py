"""Compiled policy schema.

Merchants write policy in natural language; the LLM compiler proposes an instance of
PolicyRuleSet; the merchant confirms it; only then is it active. Evaluation of these rules
(engine.py) is pure deterministic code — the LLM never evaluates policy.
"""
from typing import Optional

from pydantic import BaseModel, Field


class PolicyRuleSet(BaseModel):
    """Everything the merchant enforces on agent-initiated orders. Amounts in paise."""

    max_order_paise: Optional[int] = Field(
        default=None, description="Hard cap on a single agent order's total value.")
    approval_over_paise: Optional[int] = Field(
        default=None, description="Orders above this value require human approval.")
    per_sku_qty_caps: dict[str, int] = Field(
        default_factory=dict, description="sku -> max quantity per order.")
    category_qty_caps: dict[str, int] = Field(
        default_factory=dict, description="category -> max total units per order.")
    blocked_categories: list[str] = Field(
        default_factory=list, description="Categories never sold to agents.")
    approval_required_categories: list[str] = Field(
        default_factory=list, description="Categories that always need human review (e.g. prescription).")
    agent_daily_order_cap: Optional[int] = Field(
        default=None, description="Max paid/authorized orders per agent per day.")
    agent_daily_value_cap_paise: Optional[int] = Field(
        default=None, description="Max total order value per agent per day.")


class PricedLine(BaseModel):
    """A cart line after re-pricing from the merchant catalog (agent prices are never trusted)."""
    sku: str
    name: str
    category: str
    qty: int
    unit_paise: int
    line_paise: int
    requires_approval: bool = False   # product-level gate (e.g. Rx-required)
    max_qty_per_order: int = 10       # product-level cap


class PolicyContext(BaseModel):
    """Facts about the agent's recent behaviour, computed from the DB by the caller."""
    agent_orders_today: int = 0
    agent_value_today_paise: int = 0


class Violation(BaseModel):
    rule: str
    message: str
    sku: Optional[str] = None


class SafeAlternative(BaseModel):
    cart: list[PricedLine]
    total_paise: int
    note: str


class PolicyVerdict(BaseModel):
    result: str  # "authorize" | "block" | "escalate"
    violations: list[Violation] = Field(default_factory=list)
    escalations: list[Violation] = Field(default_factory=list)
    safe_alternative: Optional[SafeAlternative] = None
