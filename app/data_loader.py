
from pathlib import Path
from decimal import Decimal

import yaml

from app.database import get_connection, initialize_database


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = (
    PROJECT_ROOT
    / "data"
    / "company-003"
    / "rwm-v4"
    / "world-05d64e2d010225ca"
)


def to_cents(value):
    if value is None:
        return None

    return int(Decimal(str(value)) * 100)


def load_customers():
    path = DATA_DIR / "customers.yaml"

    with path.open("r", encoding="utf-8") as file:
        customers = yaml.safe_load(file)

    initialize_database()

    with get_connection() as conn:
        for customer in customers:
            conn.execute(
                """
                INSERT OR IGNORE INTO customers (
                    id,
                    display_name,
                    email,
                    phone,
                    payment_terms_days,
                    credit_limit_cents,
                    joined_sim_day
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer["id"],
                    customer["display_name"],
                    customer.get("email"),
                    customer.get("phone"),
                    customer.get("payment_terms_days"),
                    to_cents(customer.get("credit_limit_amount")),
                    customer["joined_sim_day"],
                ),
            )

        count = conn.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0]

    print(f"Customers in database: {count}")


def load_invoices():
    path = DATA_DIR / "invoices.yaml"

    with path.open("r", encoding="utf-8") as file:
        invoices = yaml.safe_load(file) or []

    inserted = 0

    with get_connection() as conn:
        for invoice in invoices:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO invoices (
                    id,
                    customer_id,
                    txn_sim_day,
                    due_sim_day,
                    total_cents
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    invoice["id"],
                    invoice["customer_id"],
                    invoice["txn_sim_day"],
                    invoice["due_sim_day"],
                    to_cents(invoice["total_amount"]),
                ),
            )
            inserted += cursor.rowcount

        count = conn.execute(
            "SELECT COUNT(*) FROM invoices"
        ).fetchone()[0]

    print(f"New invoices imported: {inserted}")
    print(f"Total invoices in database: {count}")

def load_payments():
    path = DATA_DIR / "customer_payments.yaml"

    with path.open("r", encoding="utf-8") as file:
        payments = yaml.safe_load(file) or []

    inserted = 0

    with get_connection() as conn:
        for payment in payments:
            for application in payment.get("applications", []):
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO payment_applications (
                        payment_id,
                        invoice_id,
                        customer_id,
                        txn_sim_day,
                        amount_cents
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        payment["id"],
                        application["document_id"],
                        payment["customer_id"],
                        payment["txn_sim_day"],
                        to_cents(application["amount"]),
                    ),
                )
                inserted += cursor.rowcount

        total = conn.execute(
            "SELECT COUNT(*) FROM payment_applications"
        ).fetchone()[0]

    print(f"New payment applications imported: {inserted}")
    print(f"Total payment applications in database: {total}")




if __name__ == "__main__":
    load_customers()
    load_invoices()
    load_payments()
