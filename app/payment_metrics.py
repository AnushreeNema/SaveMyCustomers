
from app.database import get_connection


def get_payment_metrics(
    customer_id: str,
    sim_day: int,
    conn=None,
):
    """
    Calculate customer payment behavior as of sim_day.

    If conn is provided, reuse that SQLite connection.
    Otherwise, open a connection automatically.

    This allows the state engine to read financial changes
    inside the same transaction that processes an event.
    """

    if conn is None:
        with get_connection() as db:
            return get_payment_metrics(
                customer_id,
                sim_day,
                conn=db,
            )

    rows = conn.execute(
        """
        SELECT
            i.id,
            i.total_cents,
            i.due_sim_day,
            COALESCE(SUM(p.amount_cents), 0) AS paid_cents,
            MAX(p.txn_sim_day) AS last_payment_day

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

    fully_paid_count = 0
    partially_paid_count = 0
    unpaid_count = 0
    late_paid_count = 0
    total_paid_cents = 0

    for row in rows:
        paid_cents = row["paid_cents"]
        total_cents = row["total_cents"]

        total_paid_cents += paid_cents

        if paid_cents >= total_cents:
            fully_paid_count += 1

            if (
                row["last_payment_day"] is not None
                and row["last_payment_day"] > row["due_sim_day"]
            ):
                late_paid_count += 1

        elif paid_cents > 0:
            partially_paid_count += 1

        else:
            unpaid_count += 1

    return {
        "customer_id": customer_id,
        "sim_day": sim_day,
        "fully_paid_invoice_count": fully_paid_count,
        "partially_paid_invoice_count": partially_paid_count,
        "unpaid_invoice_count": unpaid_count,
        "late_paid_invoice_count": late_paid_count,
        "total_collected_cents": total_paid_cents,
    }


if __name__ == "__main__":
    customer_id = "cust-customer-5"

    for day in [7, 10, 15, 60]:
        metrics = get_payment_metrics(customer_id, day)

        print(f"\nDay {day}:")
        print(metrics)
