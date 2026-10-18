
from app.database import get_connection
from app.customer_metrics import get_purchase_metrics
from app.payment_metrics import get_payment_metrics


def get_customer_state(
    customer_id: str,
    sim_day: int,
    conn=None,
):
    """
    Calculate a customer's financial state as of a simulation day.

    Includes:
    - Customer profile
    - Accounts receivable
    - Overdue invoices
    - Purchasing behavior
    - Payment behavior

    Only invoices and payments dated on or before sim_day
    are included.

    If conn is provided, reuse that SQLite connection.
    This allows event processing and state calculations
    to happen inside the same database transaction.
    """

    # 1. Validate simulation day
    if (
        not isinstance(sim_day, int)
        or isinstance(sim_day, bool)
        or sim_day < 0
    ):
        raise ValueError("sim_day must be a non-negative integer")

    # 2. Reuse an existing connection or open a new one
    if conn is None:
        with get_connection() as db:
            return get_customer_state(
                customer_id,
                sim_day,
                conn=db,
            )

    # 3. Retrieve customer information
    customer = conn.execute(
        """
        SELECT
            id,
            display_name,
            payment_terms_days,
            credit_limit_cents,
            joined_sim_day

        FROM customers

        WHERE id = ?
          AND joined_sim_day <= ?
        """,
        (customer_id, sim_day),
    ).fetchone()

    if customer is None:
        raise ValueError(
            f"Customer {customer_id} not found on day {sim_day}"
        )

    # 4. Retrieve invoices and payments as of sim_day
    rows = conn.execute(
        """
        SELECT
            i.id,
            i.total_cents,
            i.due_sim_day,
            COALESCE(SUM(p.amount_cents), 0) AS paid_cents

        FROM invoices i

        LEFT JOIN payment_applications p
            ON p.invoice_id = i.id
            AND p.txn_sim_day <= ?

        WHERE i.customer_id = ?
          AND i.txn_sim_day <= ?

        GROUP BY
            i.id,
            i.total_cents,
            i.due_sim_day
        """,
        (sim_day, customer_id, sim_day),
    ).fetchall()

    # 5. Calculate accounts receivable
    outstanding_cents = 0
    overdue_cents = 0
    overdue_invoice_count = 0
    max_days_overdue = 0
    open_invoice_count = 0

    for row in rows:
        remaining_cents = max(
            0,
            row["total_cents"] - row["paid_cents"],
        )

        outstanding_cents += remaining_cents

        if remaining_cents > 0:
            open_invoice_count += 1

        if remaining_cents > 0 and sim_day > row["due_sim_day"]:
            overdue_cents += remaining_cents
            overdue_invoice_count += 1

            days_overdue = sim_day - row["due_sim_day"]

            max_days_overdue = max(
                max_days_overdue,
                days_overdue,
            )

    # 6. Calculate purchasing behavior using the SAME connection
    purchase_metrics = get_purchase_metrics(
        customer_id,
        sim_day,
        conn=conn,
    )

    recent_revenue_cents = purchase_metrics[
        "recent_30d_revenue_cents"
    ]

    previous_revenue_cents = purchase_metrics[
        "previous_30d_revenue_cents"
    ]

    revenue_change_pct = None

    if previous_revenue_cents > 0:
        revenue_change_pct = round(
            (
                (recent_revenue_cents - previous_revenue_cents)
                / previous_revenue_cents
            ) * 100,
            2,
        )

    # 7. Calculate payment behavior using the SAME connection
    payment_metrics = get_payment_metrics(
        customer_id,
        sim_day,
        conn=conn,
    )

    # 8. Return unified customer state
    return {
        "customer_id": customer["id"],
        "customer_name": customer["display_name"],
        "sim_day": sim_day,

        "customer_profile": {
            "payment_terms_days": customer["payment_terms_days"],
            "credit_limit_cents": customer["credit_limit_cents"],
            "customer_tenure_days": (
                sim_day - customer["joined_sim_day"]
            ),
        },

        # Existing keys preserved for Jev compatibility
        "invoice_count": len(rows),
        "outstanding_ar": outstanding_cents / 100,
        "overdue_ar": overdue_cents / 100,
        "overdue_invoice_count": overdue_invoice_count,
        "max_days_overdue": max_days_overdue,
        "open_invoice_count": open_invoice_count,

        "purchase_behavior": {
            "recent_30d_invoice_count": purchase_metrics[
                "recent_30d_invoice_count"
            ],
            "previous_30d_invoice_count": purchase_metrics[
                "previous_30d_invoice_count"
            ],
            "recent_30d_revenue_cents": recent_revenue_cents,
            "previous_30d_revenue_cents": previous_revenue_cents,
            "revenue_change_pct": revenue_change_pct,
        },

        "payment_behavior": {
            "fully_paid_invoice_count": payment_metrics[
                "fully_paid_invoice_count"
            ],
            "partially_paid_invoice_count": payment_metrics[
                "partially_paid_invoice_count"
            ],
            "unpaid_invoice_count": payment_metrics[
                "unpaid_invoice_count"
            ],
            "late_paid_invoice_count": payment_metrics[
                "late_paid_invoice_count"
            ],
            "total_collected_cents": payment_metrics[
                "total_collected_cents"
            ],
        },
    }


if __name__ == "__main__":
    customer_id = "cust-customer-5"

    for day in [7, 10, 15, 60]:
        state = get_customer_state(
            customer_id,
            day,
        )

        print(f"\n========== DAY {day} ==========")
        print(state)
