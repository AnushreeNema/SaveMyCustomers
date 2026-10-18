
"""
Early Bird — Customer Financial Context

Retrieves actual financial facts from SQLite.

No OpenAI calls.
No Jev calls.
No database modifications.

Amounts are derived from invoice and payment records.
"""

from decimal import Decimal

from app.database import get_connection


def cents_to_dollars(value):
    return str(
        (Decimal(int(value or 0)) / Decimal("100"))
        .quantize(Decimal("0.01"))
    )


def get_customer_financial_context(customer_id, as_of_sim_day=None):
    """
    Build an auditable customer financial profile.

    If as_of_sim_day is provided, only transactions
    on or before that simulation day are included.
    """

    with get_connection() as conn:

        customer = conn.execute(
            """
            SELECT
                id,
                display_name,
                email,
                payment_terms_days,
                credit_limit_cents,
                joined_sim_day
            FROM customers
            WHERE id = ?
            """,
            (customer_id,),
        ).fetchone()

        if customer is None:
            raise ValueError(
                f"Customer not found: {customer_id}"
            )

        if as_of_sim_day is None:
            latest = conn.execute(
                """
                SELECT MAX(sim_day) AS latest_day
                FROM customer_state_history
                WHERE customer_id = ?
                """,
                (customer_id,),
            ).fetchone()

            if latest and latest["latest_day"] is not None:
                as_of_sim_day = int(latest["latest_day"])
            else:
                latest_invoice = conn.execute(
                    """
                    SELECT MAX(txn_sim_day) AS latest_day
                    FROM invoices
                    WHERE customer_id = ?
                    """,
                    (customer_id,),
                ).fetchone()

                as_of_sim_day = int(
                    latest_invoice["latest_day"]
                    if latest_invoice["latest_day"] is not None
                    else 0
                )

        invoice_rows = conn.execute(
            """
            SELECT
                id,
                txn_sim_day,
                due_sim_day,
                total_cents
            FROM invoices
            WHERE customer_id = ?
              AND txn_sim_day <= ?
            ORDER BY txn_sim_day, id
            """,
            (customer_id, as_of_sim_day),
        ).fetchall()

        payment_rows = conn.execute(
            """
            SELECT
                payment_id,
                invoice_id,
                txn_sim_day,
                amount_cents
            FROM payment_applications
            WHERE customer_id = ?
              AND txn_sim_day <= ?
            ORDER BY txn_sim_day, payment_id
            """,
            (customer_id, as_of_sim_day),
        ).fetchall()

        event_rows = conn.execute(
            """
            SELECT
                event_id,
                sim_day,
                event_type,
                description
            FROM customer_events
            WHERE customer_id = ?
              AND sim_day <= ?
            ORDER BY sim_day DESC, event_id DESC
            LIMIT 10
            """,
            (customer_id, as_of_sim_day),
        ).fetchall()

    invoices = {
        row["id"]: {
            "total_cents": int(row["total_cents"]),
            "due_sim_day": int(row["due_sim_day"]),
        }
        for row in invoice_rows
    }

    paid_by_invoice = {
        invoice_id: 0
        for invoice_id in invoices
    }

    for payment in payment_rows:
        invoice_id = payment["invoice_id"]

        if invoice_id in paid_by_invoice:
            paid_by_invoice[invoice_id] += int(
                payment["amount_cents"]
            )

    total_invoiced_cents = sum(
        invoice["total_cents"]
        for invoice in invoices.values()
    )

    total_paid_cents = sum(
        paid_by_invoice.values()
    )

    outstanding_cents = 0
    overdue_cents = 0
    paid_invoice_count = 0

    for invoice_id, invoice in invoices.items():

        remaining = max(
            0,
            invoice["total_cents"]
            - paid_by_invoice[invoice_id],
        )

        outstanding_cents += remaining

        if (
            remaining > 0
            and invoice["due_sim_day"] < as_of_sim_day
        ):
            overdue_cents += remaining

        if remaining == 0:
            paid_invoice_count += 1

    return {
        "customer_id": customer["id"],
        "customer_name": customer["display_name"],
        "as_of_sim_day": as_of_sim_day,

        "financial_metrics": {
            "total_invoiced": cents_to_dollars(
                total_invoiced_cents
            ),
            "total_paid": cents_to_dollars(
                total_paid_cents
            ),
            "outstanding_ar": cents_to_dollars(
                outstanding_cents
            ),
            "overdue_ar": cents_to_dollars(
                overdue_cents
            ),
            "invoice_count": len(invoices),
            "fully_paid_invoice_count": paid_invoice_count,
            "payment_application_count": len(payment_rows),
            "credit_limit": cents_to_dollars(
                customer["credit_limit_cents"]
            ),
        },

        "recent_events": [
            {
                "event_id": row["event_id"],
                "sim_day": row["sim_day"],
                "event_type": row["event_type"],
                "description": row["description"],
            }
            for row in event_rows
        ],

        "profitability": {
            "cost_of_goods": None,
            "gross_margin_percent": None,
            "status": "UNKNOWN",
            "reason": (
                "The accounting database does not contain "
                "cost-of-goods or gross-margin information."
            ),
        },
    }
