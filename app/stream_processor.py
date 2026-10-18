
"""
Early Bird — Sequential Event Stream Processor

Processes synthetic events in order, applies accounting
changes, and saves customer event history.

Default mode: local only, no paid API calls.

After local verification, live AI can be enabled
with --live-ai.
"""

import argparse
import json
from pathlib import Path

from app.database import get_connection
from app.event_processor import save_event_context
from app.financial_event_processor import process_financial_event
from app.state_engine import get_customer_state


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STREAM = (
    PROJECT_ROOT / "data" / "event_stream" / "stream_001.json"
)


def load_stream(path):
    with Path(path).open("r", encoding="utf-8") as file:
        stream = json.load(file)

    events = stream["events"]

    if not isinstance(events, list):
        raise ValueError("Stream events must be a list")

    previous_day = -1
    seen_ids = set()

    for event in events:
        event_id = event["event_id"]
        sim_day = event["sim_day"]

        if event_id in seen_ids:
            raise ValueError(
                f"Duplicate event ID in stream: {event_id}"
            )

        if type(sim_day) is not int or sim_day < previous_day:
            raise ValueError(
                "Events must be ordered by nondecreasing sim_day"
            )

        seen_ids.add(event_id)
        previous_day = sim_day

    return stream


def load_existing_context(event_id):
    """Reconstruct a previously saved event without modifying it."""

    from app.jev_client import load_saved_event_context

    return load_saved_event_context(event_id)


def process_customer_message(event):
    """Record a customer message without changing accounting balances."""

    customer_id = event["customer_id"]
    sim_day = event["sim_day"]

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            """
            SELECT event_id
            FROM customer_events
            WHERE event_id = ?
            """,
            (event["event_id"],),
        ).fetchone()

        if existing:
            return None

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
                "Backdated customer message rejected"
            )

        state = get_customer_state(
            customer_id,
            sim_day,
            conn=conn,
        )

        context = {
            "event_id": event["event_id"],
            "customer_id": customer_id,
            "sim_day": sim_day,
            "previous_state": state,
            "new_event": {
                "type": "customer_message",
                "description": event["description"],
            },
            "current_state": state,
            "financial_change_cents": 0,
        }

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
                event["event_id"],
                customer_id,
                sim_day,
                "customer_message",
                event["description"],
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
                event["event_id"],
                customer_id,
                sim_day,
                "customer_message",
                json.dumps(state),
                json.dumps(state),
            ),
        )

    return context


def apply_event(event):
    """Apply an event once, or reuse its saved context."""

    event_id = event["event_id"]

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT event_id
            FROM customer_state_history
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()

    if existing:
        return load_existing_context(event_id), False

    event_type = event["event_type"]

    if event_type in {"invoice_created", "payment_received"}:
        context = process_financial_event(event)
    elif event_type == "customer_message":
        context = process_customer_message(event)
    else:
        raise ValueError(
            f"Unsupported event type: {event_type}"
        )

    if context is None:
        return load_existing_context(event_id), False

    return context, True


def run_stream(stream_path=DEFAULT_STREAM, live_ai=False, limit=None):
    stream = load_stream(stream_path)
    events = stream["events"]

    if limit is not None:
        events = events[:limit]

    if live_ai:
        from app.live_replay import run_live_replay

    print(f"\nEARLY BIRD — {stream['stream_id']}")
    print(f"Events selected: {len(events)}")
    print(f"Live AI enabled: {live_ai}")

    for index, event in enumerate(events, start=1):
        print(
            f"\n[{index}/{len(events)}] "
            f"{event['event_id']} — {event['event_type']}"
        )

        context, newly_applied = apply_event(event)

        print(
            "Database: "
            + ("updated" if newly_applied else "already processed")
        )

        before = context["previous_state"]
        after = context["current_state"]

        print(
            "Outstanding AR: "
            f"${before['outstanding_ar']:.2f}"
            " -> "
            f"${after['outstanding_ar']:.2f}"
        )

        if live_ai:
            result = run_live_replay(event["event_id"])
            print(f"AI status: {result['status']}")

            if result["status"] not in {"filtered", "attention_needed"}:
                raise RuntimeError(
                    f"AI evaluation did not finish for "
                    f"{event['event_id']}: {result['status']}"
                )
        else:
            print("AI: skipped (local-only mode)")

    print("\nStream processing complete.")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--stream",
        default=str(DEFAULT_STREAM),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    parser.add_argument(
        "--live-ai",
        action="store_true",
        help="Enable paid Jev and conditional OpenAI calls",
    )

    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    run_stream(
        stream_path=args.stream,
        live_ai=args.live_ai,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
