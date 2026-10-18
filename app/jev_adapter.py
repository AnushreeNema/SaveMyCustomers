
import json

from app.event_processor import build_event_context, EVENT_PATH


def build_jev_input(context):
    """
    Convert a customer event context into structured
    input for Jev System One.

    Supports customer messages, invoice creation,
    and payment events.
    """

    before = context["previous_state"]
    after = context["current_state"]

    def change(field):
        return round(
            after[field] - before[field],
            2,
        )

    def behavior_change(section, field):
        return (
            after.get(section, {}).get(field, 0)
            - before.get(section, {}).get(field, 0)
        )

    return {
        "customer": {
            "id": context["customer_id"],
            "name": after["customer_name"],
        },

        "simulation_day": context["sim_day"],

        "event": {
            "type": context["new_event"]["type"],
            "description": context["new_event"]["description"],
        },

        "financial_changes": {
            "outstanding_ar_before": before["outstanding_ar"],
            "outstanding_ar_after": after["outstanding_ar"],
            "outstanding_ar_delta": change("outstanding_ar"),

            "overdue_ar_before": before["overdue_ar"],
            "overdue_ar_after": after["overdue_ar"],
            "overdue_ar_delta": change("overdue_ar"),

            "overdue_invoice_count_delta": change(
                "overdue_invoice_count"
            ),

            "open_invoice_count_delta": change(
                "open_invoice_count"
            ),

            "invoice_count_delta": change(
                "invoice_count"
            ),
        },

        "purchase_behavior": {
            "recent_30d_invoice_count": (
                after["purchase_behavior"][
                    "recent_30d_invoice_count"
                ]
            ),

            "previous_30d_invoice_count": (
                after["purchase_behavior"][
                    "previous_30d_invoice_count"
                ]
            ),

            "recent_30d_revenue_cents": (
                after["purchase_behavior"][
                    "recent_30d_revenue_cents"
                ]
            ),

            "previous_30d_revenue_cents": (
                after["purchase_behavior"][
                    "previous_30d_revenue_cents"
                ]
            ),

            "revenue_change_pct": (
                after["purchase_behavior"]["revenue_change_pct"]
            ),

            "recent_30d_revenue_delta_cents": behavior_change(
                "purchase_behavior",
                "recent_30d_revenue_cents",
            ),
        },

        "payment_behavior": {
            "fully_paid_invoice_count": (
                after["payment_behavior"][
                    "fully_paid_invoice_count"
                ]
            ),

            "partially_paid_invoice_count": (
                after["payment_behavior"][
                    "partially_paid_invoice_count"
                ]
            ),

            "unpaid_invoice_count": (
                after["payment_behavior"][
                    "unpaid_invoice_count"
                ]
            ),

            "late_paid_invoice_count": (
                after["payment_behavior"][
                    "late_paid_invoice_count"
                ]
            ),

            "total_collected_cents": (
                after["payment_behavior"][
                    "total_collected_cents"
                ]
            ),

            "total_collected_delta_cents": behavior_change(
                "payment_behavior",
                "total_collected_cents",
            ),
        },

        "current_financial_state": {
            "outstanding_ar": after["outstanding_ar"],
            "overdue_ar": after["overdue_ar"],
            "overdue_invoice_count": (
                after["overdue_invoice_count"]
            ),
            "max_days_overdue": after["max_days_overdue"],
            "open_invoice_count": after["open_invoice_count"],
        },

        "task": (
            "Evaluate whether the NEW event provides meaningful "
            "evidence of a change in the customer relationship. "
            "Use financial before/after changes as context, "
            "but do not confuse routine accounting activity "
            "with a meaningful relationship change. "
            "A new invoice or ordinary payment is not, by itself, "
            "evidence that the relationship improved or worsened. "
            "Determine the relationship direction and whether "
            "deeper System Two investigation is justified."
        ),
    }


if __name__ == "__main__":
    context = build_event_context(EVENT_PATH)
    jev_input = build_jev_input(context)

    print(json.dumps(jev_input, indent=2))
