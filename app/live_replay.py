
"""
Early Bird — Live AI Replay

Evaluates already-processed events using their saved
before/after customer state snapshots.

Jev evaluates every event.
OpenAI is called only for escalated events.

Results are persisted to SQLite.
No emails or messages are sent.
"""

import argparse
import json
from datetime import datetime, timezone

from app.database import get_connection
from app.jev_client import (
    evaluate_event_with_jev,
    load_saved_event_context,
)
from app.openai_client import generate_owner_notification


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def initialize_storage():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS live_ai_replays (
                event_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                status TEXT NOT NULL,
                jev_result_json TEXT,
                openai_result_json TEXT,
                error_message TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )


def get_replay_result(event_id):
    initialize_storage()

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM live_ai_replays
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()

    if row is None:
        return None

    result = dict(row)

    result["jev_result"] = (
        json.loads(result.pop("jev_result_json"))
        if result["jev_result_json"]
        else None
    )

    result["openai_result"] = (
        json.loads(result.pop("openai_result_json"))
        if result["openai_result_json"]
        else None
    )

    return result


def claim_event(event_id, customer_id):
    """
    Claim an event before making a paid API request.

    An already claimed event cannot silently trigger
    another paid request.
    """

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO live_ai_replays (
                event_id,
                customer_id,
                status,
                started_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                event_id,
                customer_id,
                "running_jev",
                now_utc(),
            ),
        )

        return cursor.rowcount == 1


def update_result(
    event_id,
    status,
    jev_result=None,
    openai_result=None,
    error_message=None,
):
    completed_at = (
        now_utc()
        if status in {
            "filtered",
            "attention_needed",
            "failed",
        }
        else None
    )

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE live_ai_replays
            SET
                status = ?,
                jev_result_json = COALESCE(
                    ?, jev_result_json
                ),
                openai_result_json = COALESCE(
                    ?, openai_result_json
                ),
                error_message = ?,
                completed_at = ?
            WHERE event_id = ?
            """,
            (
                status,
                (
                    json.dumps(jev_result)
                    if jev_result is not None
                    else None
                ),
                (
                    json.dumps(openai_result)
                    if openai_result is not None
                    else None
                ),
                error_message,
                completed_at,
                event_id,
            ),
        )


def run_live_replay(event_id):
    """
    Run a real Jev evaluation and conditionally
    a real OpenAI evaluation.

    The accounting event must already be saved.
    """

    initialize_storage()

    context = load_saved_event_context(event_id)

    if not claim_event(
        event_id,
        context["customer_id"],
    ):
        print(
            f"{event_id} was already evaluated or claimed. "
            "Returning saved status."
        )
        return get_replay_result(event_id)

    jev_result = None

    try:
        print(f"\n[JEV] Evaluating {event_id}...")

        jev_result = evaluate_event_with_jev(
            context=context
        )

        update_result(
            event_id,
            status="jev_completed",
            jev_result=jev_result,
        )

        if not jev_result["should_escalate"]:
            print("[JEV] Routine event — filtered.")
            print("[OPENAI] Skipped.")

            update_result(
                event_id,
                status="filtered",
            )

            return get_replay_result(event_id)

        print("[JEV] Escalation required.")
        print("[OPENAI] Generating owner notification...")

        update_result(
            event_id,
            status="running_openai",
        )

        openai_result = generate_owner_notification(
            context=context,
            jev_result=jev_result,
        )

        if openai_result is None:
            raise RuntimeError(
                "OpenAI returned no notification"
            )

        update_result(
            event_id,
            status="attention_needed",
            openai_result=openai_result,
        )

        print("[EARLY BIRD] Attention alert saved.")
        print("[EARLY BIRD] No email sent.")

        return get_replay_result(event_id)

    except Exception as exc:
        update_result(
            event_id,
            status="failed",
            jev_result=jev_result,
            error_message=str(exc),
        )
        raise


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "event_id",
        nargs="?",
    )

    parser.add_argument(
        "--init",
        action="store_true",
        help="Create storage without API calls",
    )

    parser.add_argument(
        "--status",
        metavar="EVENT_ID",
        help="View saved result without API calls",
    )

    args = parser.parse_args()

    if args.init:
        initialize_storage()
        print("Early Bird AI replay storage initialized.")
        print("Paid API calls made: 0")
        return

    if args.status:
        print(
            json.dumps(
                get_replay_result(args.status),
                indent=2,
            )
        )
        return

    if not args.event_id:
        parser.error(
            "Provide an event ID, --init, or --status"
        )

    result = run_live_replay(args.event_id)

    print("\n========== AI RESULT ==========")
    print(json.dumps(result, indent=2))
    print("===============================")


if __name__ == "__main__":
    main()
