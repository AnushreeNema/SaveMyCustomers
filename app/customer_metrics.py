
from app.database import get_connection


def get_purchase_metrics(
    customer_id: str,
    sim_day: int,
    conn=None,
):
    """
    Calculate customer purchasing behavior as of sim_day.

    Compares:
    - Recent 30 days: sim_day - 29 through sim_day
    - Previous 30 days: sim_day - 59 through sim_day - 30

    If conn is provided, reuse the existing SQLite connection.
    Otherwise, open a new connection automatically.

    Revenue represents invoiced amounts, not cash collected.
    """

    if conn is None:
        with get_connection() as db:
            return get_purchase_metrics(
                customer_id,
                sim_day,
                conn=db,
            )

    rows = conn.execute(
        """
        SELECT
            COUNT(
                CASE
                    WHEN txn_sim_day BETWEEN ? AND ?
                    THEN 1
                END
            ) AS recent_count,

            COALESCE(
                SUM(
                    CASE
                        WHEN txn_sim_day BETWEEN ? AND ?
                        THEN total_cents
                        ELSE 0
                    END
                ),
                0
            ) AS recent_cents,

            COUNT(
                CASE
                    WHEN txn_sim_day BETWEEN ? AND ?
                    THEN 1
                END
            ) AS previous_count,

            COALESCE(
                SUM(
                    CASE
                        WHEN txn_sim_day BETWEEN ? AND ?
                        THEN total_cents
                        ELSE 0
                    END
                ),
                0
            ) AS previous_cents

        FROM invoices

        WHERE customer_id = ?
          AND txn_sim_day <= ?
        """,
        (
            sim_day - 29,
            sim_day,

            sim_day - 29,
            sim_day,

            sim_day - 59,
            sim_day - 30,

            sim_day - 59,
            sim_day - 30,

            customer_id,
            sim_day,
        ),
    ).fetchone()

    return {
        "customer_id": customer_id,
        "sim_day": sim_day,
        "recent_30d_invoice_count": rows["recent_count"],
        "recent_30d_revenue_cents": rows["recent_cents"],
        "previous_30d_invoice_count": rows["previous_count"],
        "previous_30d_revenue_cents": rows["previous_cents"],
    }


if __name__ == "__main__":
    customer_id = "cust-customer-5"
    sim_day = 60

    metrics = get_purchase_metrics(
        customer_id,
        sim_day,
    )

    print(metrics)
