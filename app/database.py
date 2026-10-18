
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DB_PATH = (
    PROJECT_ROOT / "data" / "company003.sqlite3"
)

DEMO_DB_PATH = (
    PROJECT_ROOT / "data" / "early_bird_demo.sqlite3"
)


def get_database_path():
    """
    Choose the database using an environment variable.

    Default:
        data/company003.sqlite3

    Demo:
        EARLY_BIRD_DB=demo
        -> data/early_bird_demo.sqlite3
    """
    selected = os.environ.get(
        "EARLY_BIRD_DB",
        "",
    ).strip().lower()

    if selected == "demo":
        return DEMO_DB_PATH

    if selected in {"", "main"}:
        return DEFAULT_DB_PATH

    raise ValueError(
        "Invalid EARLY_BIRD_DB value. "
        "Use 'main' or 'demo'."
    )


def get_connection():
    db_path = get_database_path()

    db_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    conn = sqlite3.connect(
        db_path,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


def initialize_database():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                payment_terms_days INTEGER,
                credit_limit_cents INTEGER,
                joined_sim_day INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS invoices (
                id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                txn_sim_day INTEGER NOT NULL,
                due_sim_day INTEGER NOT NULL,
                total_cents INTEGER NOT NULL,
                FOREIGN KEY (customer_id)
                    REFERENCES customers(id)
            );

            CREATE TABLE IF NOT EXISTS payment_applications (
                payment_id TEXT NOT NULL,
                invoice_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                txn_sim_day INTEGER NOT NULL,
                amount_cents INTEGER NOT NULL,
                PRIMARY KEY (payment_id, invoice_id),
                FOREIGN KEY (invoice_id)
                    REFERENCES invoices(id),
                FOREIGN KEY (customer_id)
                    REFERENCES customers(id)
            );

            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                sim_day INTEGER NOT NULL,
                processed_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS customer_state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                sim_day INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                state_before_json TEXT NOT NULL,
                state_after_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(event_id, customer_id),

                FOREIGN KEY (customer_id)
                    REFERENCES customers(id)
            );

            CREATE INDEX IF NOT EXISTS idx_customer_state_history
                ON customer_state_history (
                    customer_id,
                    sim_day
                );

            CREATE TABLE IF NOT EXISTS customer_events (
                event_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                sim_day INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (customer_id)
                    REFERENCES customers(id)
            );

            CREATE INDEX IF NOT EXISTS idx_customer_events_history
                ON customer_events (
                    customer_id,
                    sim_day,
                    event_id
                );
        """)


if __name__ == "__main__":
    initialize_database()

    print(
        f"Database initialized: {get_database_path()}"
    )
