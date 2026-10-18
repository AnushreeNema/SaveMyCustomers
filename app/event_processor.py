
import json
from pathlib import Path

from app.database import get_connection
from app.state_engine import get_customer_state


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVENT_PATH = PROJECT_ROOT / "data" / "demo_events" / "event_001.json"


def build_event_context(event_path):
    with open(event_path, "r", encoding="utf-8") as file:
        event = json.load(file)

    required_fields = [
        "event_id",
        "customer_id",
        "sim_day",
        "event_type",
        "description",
    ]

    for field in required_fields:
        if field not in event:
            raise ValueError(f"Missing event field: {field}")

    if event["event_type"] != "customer_message":
        raise ValueError(
            "Only customer_message events are supported for now"
        )

    customer_id = event["customer_id"]
    sim_day = event["sim_day"]

    # Customer messages do not modify accounting balances.
    state_before = get_customer_state(customer_id, sim_day)
    state_after = get_customer_state(customer_id, sim_day)

    context = {
        "event_id": event["event_id"],
        "customer_id": customer_id,
        "sim_day": sim_day,
        "previous_state": state_before,
        "new_event": {
            "type": event["event_type"],
            "description": event["description"],
        },
        "current_state": state_after,
        "financial_change_cents": 0,
    }

    return context



def save_event_context(context):
    event_id = context["event_id"]
    customer_id = context["customer_id"]

    with get_connection() as conn:
        # Check whether this exact event was already recorded.
        existing = conn.execute(
            """
            SELECT event_id
            FROM customer_events
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()

        if existing:
            print(f"Event {event_id} already saved.")
            return False

        # Both inserts happen in one transaction.
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
                context["sim_day"],
                context["new_event"]["type"],
                context["new_event"]["description"],
            ),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO customer_state_history (
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
                context["sim_day"],
                context["new_event"]["type"],
                json.dumps(context["previous_state"]),
                json.dumps(context["current_state"]),
            ),
        )

    return True



if __name__ == "__main__":
    context = build_event_context(EVENT_PATH)

    saved = save_event_context(context)

    print(json.dumps(context, indent=2))
    print(f"\nNew event saved: {saved}")
