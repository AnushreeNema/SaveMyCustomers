
"""
Early Bird — Deterministic Strategy Comparison

Evaluates candidate retention offers using owner-supplied
financial assumptions.

AI cannot approve offers or override financial checks.
No API calls, database writes, or email sending.
"""

from app.offer_evaluator import evaluate_offer_safely


def compare_retention_strategies(
    *,
    order_revenue,
    cost_of_goods,
    retention_budget,
    minimum_margin_percent,
    strategies,
):
    """
    Evaluate a list of retention strategies.

    Each strategy must include:
      - title
      - action
      - discount_percent
      - shipping_credit
      - service_recovery_cost

    Missing costs remain unknown, not zero.

    Only the deterministic evaluator can mark an
    offer FINANCIALLY_FEASIBLE.
    """

    results = []

    for strategy in strategies:
        title = strategy.get("title", "Untitled strategy")
        action = strategy.get("action", "")

        evaluation = evaluate_offer_safely(
            order_revenue=order_revenue,
            cost_of_goods=cost_of_goods,
            retention_budget=retention_budget,
            minimum_margin_percent=minimum_margin_percent,
            discount_percent=strategy.get(
                "discount_percent"
            ),
            shipping_credit=strategy.get(
                "shipping_credit"
            ),
            service_recovery_cost=strategy.get(
                "service_recovery_cost"
            ),
        )

        results.append({
            "title": title,
            "action": action,
            "financial_evaluation": evaluation,
            "approval_required": True,
        })

    return results
