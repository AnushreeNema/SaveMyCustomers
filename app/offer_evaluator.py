
"""
Early Bird — Deterministic Retention Offer Evaluator

No AI calls.
No database writes.
No email sending.

Evaluates the economics of ONE proposed future order.
All monetary inputs are in dollars.

A passing result means the offer satisfies the supplied
financial assumptions and guardrails — not that customer
retention or future profit is guaranteed.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def money(value):
    """Convert a number safely to a two-decimal Decimal."""
    if value is None or isinstance(value, bool):
        raise ValueError("A required financial input is missing")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid financial value: {value}")

    if not result.is_finite():
        raise ValueError("Financial inputs must be finite")

    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def evaluate_offer(
    *,
    order_revenue,
    cost_of_goods,
    discount_percent=0,
    shipping_credit=0,
    service_recovery_cost=0,
    retention_budget,
    minimum_margin_percent,
):
    """
    Evaluate one proposed retention offer.

    order_revenue:
        Expected revenue before discounts.

    cost_of_goods:
        Expected cost of fulfilling that order.

    discount_percent:
        Percentage reduction in selling price.

    shipping_credit:
        Additional business-funded customer credit.

    service_recovery_cost:
        Additional labor, logistics, or service cost.

    retention_budget:
        Maximum permitted cost of the offer.

    minimum_margin_percent:
        Minimum gross contribution margin after the offer.

    Note:
        Shipping credits are treated as an additional cost,
        not as a reduction in net sales.
    """

    revenue = money(order_revenue)
    cogs = money(cost_of_goods)
    discount_rate = money(discount_percent)
    shipping = money(shipping_credit)
    service = money(service_recovery_cost)
    budget = money(retention_budget)
    minimum_margin = money(minimum_margin_percent)

    if revenue <= 0:
        raise ValueError("Order revenue must be positive")

    if any(value < 0 for value in (
        cogs, discount_rate, shipping, service, budget
    )):
        raise ValueError("Costs and discounts cannot be negative")

    if not Decimal("0") <= discount_rate <= HUNDRED:
        raise ValueError("Discount must be between 0 and 100%")

    if not Decimal("0") <= minimum_margin <= HUNDRED:
        raise ValueError("Minimum margin must be between 0 and 100%")

    # Baseline before the retention offer.
    baseline_profit = revenue - cogs

    # Financial impact of the proposed offer.
    discount_amount = (
        revenue * discount_rate / HUNDRED
    ).quantize(CENT, rounding=ROUND_HALF_UP)

    net_revenue = revenue - discount_amount

    total_offer_cost = discount_amount + shipping + service

    projected_profit = (
        net_revenue - cogs - shipping - service
    ).quantize(CENT, rounding=ROUND_HALF_UP)

    projected_margin = (
        projected_profit / net_revenue * HUNDRED
    ).quantize(CENT, rounding=ROUND_HALF_UP) if net_revenue > 0 else None

    # Evaluate using unrounded margin comparison.
    margin_passes = (
        net_revenue > 0
        and projected_profit * HUNDRED
        >= minimum_margin * net_revenue
    )

    checks = {
        "baseline_is_profitable": baseline_profit > 0,
        "offer_within_budget": total_offer_cost <= budget,
        "positive_projected_profit": projected_profit > 0,
        "minimum_margin_preserved": margin_passes,
    }

    approved_by_rules = all(checks.values())

    failed_checks = [
        name for name, passed in checks.items()
        if not passed
    ]

    return {
        "status": (
            "FINANCIALLY_FEASIBLE"
            if approved_by_rules
            else "REJECTED"
        ),
        "financially_feasible": approved_by_rules,
        "baseline_gross_profit": str(baseline_profit),
        "discount_amount": str(discount_amount),
        "net_order_revenue": str(net_revenue),
        "total_offer_cost": str(total_offer_cost),
        "projected_gross_profit": str(projected_profit),
        "projected_margin_percent": (
            str(projected_margin)
            if projected_margin is not None
            else None
        ),
        "minimum_margin_percent": str(minimum_margin),
        "checks": checks,
        "failed_checks": failed_checks,
        "requires_owner_approval": True,
    }


def evaluate_offer_safely(**kwargs):
    """
    Never label an offer financially feasible
    if its required inputs are missing or invalid.
    """
    try:
        return evaluate_offer(**kwargs)

    except (ValueError, TypeError, ArithmeticError) as exc:
        return {
            "status": "UNVERIFIED",
            "financially_feasible": False,
            "reason": str(exc),
            "requires_owner_approval": True,
        }
