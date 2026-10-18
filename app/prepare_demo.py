
"""
Early Bird — Safe Demo Database Preparation

Copies the main SQLite database into a separate demo
database, then removes only the five stream events
and their related AI replay records.

Does not call Jev or OpenAI.
Does not modify the main database.
"""

import json
import sqlite3
from pathlib import Path

from app.database import (
    DEFAULT_DB_PATH,
    DEMO_DB_PATH,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent

STREAM_PATH = (
    PROJECT_ROOT
    / "data"
    / "event_stream"
    / "stream_001.json"
)


def prepare_demo():
    if not DEFAULT_DB_PATH.exists():
        raise FileNotFoundError(
            f"Main database not found: {DEFAULT_DB_PATH}"
        )

    if not STREAM_PATH.exists():
        raise FileNotFoundError(
            f"Event stream not found: {STREAM_PATH}"
        )

    with STREAM_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        stream = json.load(file)

    events = stream["events"]

    event_ids = [
        event["event_id"]
        for event in events
    ]

    invoice_ids = [
        event["invoice"]["id"]
        for event in events
        if event["event_type"] == "invoice_created"
    ]

    payment_ids = [
        event["payment"]["id"]
        for event in events
        if event["event_type"] == "payment_received"
    ]

    print("\nEARLY BIRD — PREPARE DEMO")
    print(f"Source: {DEFAULT_DB_PATH}")
    print(f"Target: {DEMO_DB_PATH}")
    print(f"Stream events: {len(event_ids)}")

    DEMO_DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # SQLite's backup API creates a consistent copy.
    # The main database is never modified.
    with sqlite3.connect(
        f"file:{DEFAULT_DB_PATH.resolve()}?mode=ro",
        uri=True,
    ) as source:
        with sqlite3.connect(
            DEMO_DB_PATH
        ) as destination:
            source.backup(destination)

    with sqlite3.connect(DEMO_DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table'"
            )
        }

        def delete_ids(table, column, ids):
            if table not in tables or not ids:
                return

            placeholders = ",".join(
                "?"
                for _ in ids
            )

            conn.execute(
                f"DELETE FROM {table} "
                f"WHERE {column} IN ({placeholders})",
                ids,
            )

        # Delete dependent payment applications first.
        delete_ids(
            "payment_applications",
            "payment_id",
            payment_ids,
        )

        delete_ids(
            "payment_applications",
            "invoice_id",
            invoice_ids,
        )

        # Delete synthetic invoices.
        delete_ids(
            "invoices",
            "id",
            invoice_ids,
        )

        # Delete saved AI evaluations.
        delete_ids(
            "live_ai_replays",
            "event_id",
            event_ids,
        )

        # Delete synthetic event records and snapshots.
        delete_ids(
            "customer_state_history",
            "event_id",
            event_ids,
        )

        delete_ids(
            "customer_events",
            "event_id",
            event_ids,
        )

        delete_ids(
            "processed_events",
            "event_id",
            event_ids,
        )

        conn.commit()

        # Verify no stream events remain.
        if "customer_state_history" in tables:
            placeholders = ",".join(
                "?"
                for _ in event_ids
            )

            remaining = conn.execute(
                "SELECT COUNT(*) "
                "FROM customer_state_history "
                f"WHERE event_id IN ({placeholders})",
                event_ids,
            ).fetchone()[0]

            if remaining:
                raise RuntimeError(
                    "Demo preparation failed: "
                    "stream events still exist."
                )

    print("\nDemo database ready.")
    print(
        "The five stream events can now "
        "be processed as new events."
    )
    print(
        "Main database was not modified."
    )


if __name__ == "__main__":
    prepare_demo()
