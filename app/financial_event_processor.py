
import json
from pathlib import Path

from app.database import get_connection
from app.state_engine import get_customer_state


def validate_sim_day(sim_day):
    if type(sim_day) is not int or sim_day < 0:
        raise ValueError(
            "sim_day must be a non-negative integer"
        )


def validate_positive_cents(amount_cents):
    if type(amount_cents) is not int or amount_cents <= 0:
        raise ValueError(
            "Amount must be positive integer cents"
        )


def validate_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string"
        )


def check_event_not_processed(conn, event_id):
    """
    Return False for a previously processed event.

    Different events may have identical amounts.
    Only the same event ID is considered a retry.
    """
    existing = conn.execute(
        """
        SELECT event_id
        FROM processed_events
        WHERE event_id = ?
        """,
        (event_id,),
    ).fetchone()

    return existing is None


def check_event_order(conn, customer_id, sim_day):
    """
    Reject events older than the latest saved
    customer state snapshot.

    Same-day events are allowed and processed
    in their execution order.
    """
    latest = conn.execute(
        """
        SELECT MAX(sim_day) AS latest_day
        FROM customer_state_history
        WHERE customer_id = ?
        """,
        (customer_id,),
    ).fetchone()

    if (
        latest["latest_day"] is not None
        and sim_day < latest["latest_day"]
    ):
        raise ValueError(
            "Backdated event rejected: customer already "
            "has a newer saved state"
        )


def save_event_records(
    conn,
    event,
    state_before,
    state_after,
):
    """
    Save event metadata, financial snapshots,
    and the processed-event marker.

    Must be called inside the same transaction
    as the accounting update.
    """

    event_id = event["event_id"]
    customer_id = event["customer_id"]
    sim_day = event["sim_day"]
    event_type = event["event_type"]
    description = event["description"]

    conn.execute(
        """
        INSERT INTO customer_events (
            event_id,
            customer_id,
            sim_day,
            event_type,
            description
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event_id,
            customer_id,
            sim_day,
            event_type,
            description,
        ),
    )

    conn.execute(
        """
        INSERT INTO customer_state_history (
            event_id,
            customer_id,
            sim_day,
            event_type,
            state_before_json,
            state_after_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            customer_id,
            sim_day,
            event_type,
            json.dumps(state_before),
            json.dumps(state_after),
        ),
    )

    conn.execute(
        """
        INSERT INTO processed_events (
            event_id,
            event_type,
            sim_day
        )
        VALUES (?, ?, ?)
        """,
        (
            event_id,
            event_type,
            sim_day,
        ),
    )


def build_result(
    event,
    state_before,
    state_after,
    financial_change_cents,
):
    return {
        "event_id": event["event_id"],
        "customer_id": event["customer_id"],
        "sim_day": event["sim_day"],
        "previous_state": state_before,
        "new_event": {
            "type": event["event_type"],
            "description": event["description"],
        },
        "current_state": state_after,
        "financial_change_cents": financial_change_cents,
    }


def process_invoice_event(event):
    """
    Create an invoice and record the financial
    state transition atomically.
    """

    if event.get("event_type") != "invoice_created":
        raise ValueError(
            "Expected an invoice_created event"
        )

    event_id = event["event_id"]
    customer_id = event["customer_id"]
    sim_day = event["sim_day"]
    description = event["description"]

    invoice = event["invoice"]
    invoice_id = invoice["id"]
    total_cents = invoice["total_cents"]
    due_sim_day = invoice["due_sim_day"]

    for name, value in (
        ("event_id", event_id),
        ("customer_id", customer_id),
        ("description", description),
        ("invoice_id", invoice_id),
    ):
        validate_text(value, name)

    validate_sim_day(sim_day)
    validate_positive_cents(total_cents)
    validate_sim_day(due_sim_day)

    if due_sim_day < sim_day:
        raise ValueError(
            "Invoice due day cannot precede issue day"
        )

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        if not check_event_not_processed(conn, event_id):
            print(
                f"Event {event_id} already processed. Skipping."
            )
            return None

        check_event_order(
            conn,
            customer_id,
            sim_day,
        )

        # Customer state before the invoice.
        state_before = get_customer_state(
            customer_id,
            sim_day,
            conn=conn,
        )

        # Insert the new invoice.
        # Duplicate invoice IDs raise an error.
        conn.execute(
            """
            INSERT INTO invoices (
                id,
                customer_id,
                txn_sim_day,
                due_sim_day,
                total_cents
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                customer_id,
                sim_day,
                due_sim_day,
                total_cents,
            ),
        )

        # Customer state after the invoice.
        state_after = get_customer_state(
            customer_id,
            sim_day,
            conn=conn,
        )

        save_event_records(
            conn,
            event,
            state_before,
            state_after,
        )

    return build_result(
        event,
        state_before,
        state_after,
        total_cents,
    )


def process_payment_event(event):
    """
    Apply a payment to an existing invoice
    and record the financial state transition
    atomically.
    """

    if event.get("event_type") != "payment_received":
        raise ValueError(
            "Expected a payment_received event"
        )

    event_id = event["event_id"]
    customer_id = event["customer_id"]
    sim_day = event["sim_day"]
    description = event["description"]

    payment = event["payment"]
    payment_id = payment["id"]
    invoice_id = payment["invoice_id"]
    amount_cents = payment["amount_cents"]

    for name, value in (
        ("event_id", event_id),
        ("customer_id", customer_id),
        ("description", description),
        ("payment_id", payment_id),
        ("invoice_id", invoice_id),
    ):
        validate_text(value, name)

    validate_sim_day(sim_day)
    validate_positive_cents(amount_cents)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        if not check_event_not_processed(conn, event_id):
            print(
                f"Event {event_id} already processed. Skipping."
            )
            return None

        check_event_order(
            conn,
            customer_id,
            sim_day,
        )

        # Verify the invoice exists and belongs
        # to the correct customer.
        invoice = conn.execute(
            """
            SELECT
                id,
                customer_id,
                txn_sim_day,
                total_cents
            FROM invoices
            WHERE id = ?
            """,
            (invoice_id,),
        ).fetchone()

        if invoice is None:
            raise ValueError(
                f"Invoice {invoice_id} does not exist"
            )

        if invoice["customer_id"] != customer_id:
            raise ValueError(
                "Invoice belongs to a different customer"
            )

        if invoice["txn_sim_day"] > sim_day:
            raise ValueError(
                "Payment cannot precede invoice creation"
            )

        # Payment IDs must not be reused,
        # even for different invoices.
        existing_payment = conn.execute(
            """
            SELECT payment_id
            FROM payment_applications
            WHERE payment_id = ?
            LIMIT 1
            """,
            (payment_id,),
        ).fetchone()

        if existing_payment is not None:
            raise ValueError(
                f"Payment ID {payment_id} already exists"
            )

        # Calculate the remaining balance
        # as of this event's simulation day.
        paid_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(amount_cents), 0)
                    AS paid_cents
            FROM payment_applications
            WHERE invoice_id = ?
              AND txn_sim_day <= ?
            """,
            (invoice_id, sim_day),
        ).fetchone()

        remaining_cents = (
            invoice["total_cents"]
            - paid_row["paid_cents"]
        )

        if remaining_cents <= 0:
            raise ValueError(
                "Invoice is already fully paid"
            )

        if amount_cents > remaining_cents:
            raise ValueError(
                "Payment exceeds remaining invoice "
                f"balance of {remaining_cents} cents"
            )

        # Customer state before payment.
        state_before = get_customer_state(
            customer_id,
            sim_day,
            conn=conn,
        )

        # Apply payment to invoice.
        conn.execute(
            """
            INSERT INTO payment_applications (
                payment_id,
                invoice_id,
                customer_id,
                txn_sim_day,
                amount_cents
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payment_id,
                invoice_id,
                customer_id,
                sim_day,
                amount_cents,
            ),
        )

        # Customer state after payment.
        state_after = get_customer_state(
            customer_id,
            sim_day,
            conn=conn,
        )

        save_event_records(
            conn,
            event,
            state_before,
            state_after,
        )

    return build_result(
        event,
        state_before,
        state_after,
        -amount_cents,
    )


def process_financial_event(event):
    """
    Route a financial event to its processor.
    """

    event_type = event.get("event_type")

    if event_type == "invoice_created":
        return process_invoice_event(event)

    if event_type == "payment_received":
        return process_payment_event(event)

    raise ValueError(
        f"Unsupported financial event type: {event_type}"
    )


if __name__ == "__main__":
    import sys

    # Default to the payment demo.
    # You can also supply a JSON event path.
    event_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "data/demo_events/event_003.json"
    )

    with event_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        event = json.load(file)

    result = process_financial_event(event)

    if result is not None:
        before = result["previous_state"]
        after = result["current_state"]

        print("\nFinancial event processed successfully!")
        print(f"Event: {result['event_id']}")
        print(f"Type: {event['event_type']}")
        print(f"Customer: {after['customer_name']}")

        print(
            "Outstanding AR: "
            f"${before['outstanding_ar']:.2f}"
            " -> "
            f"${after['outstanding_ar']:.2f}"
        )

        print(
            "Invoice count: "
            f"{before['invoice_count']}"
            " -> "
            f"{after['invoice_count']}"
        )

        print(
            "Total collected (cents): "
            f"{before['payment_behavior']['total_collected_cents']}"
            " -> "
            f"{after['payment_behavior']['total_collected_cents']}"
        )

        print(
            "Recent 30-day invoiced revenue (cents): "
            f"{before['purchase_behavior']['recent_30d_revenue_cents']}"
            " -> "
            f"{after['purchase_behavior']['recent_30d_revenue_cents']}"
        )
