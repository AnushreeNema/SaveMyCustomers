
import json
import time

from dotenv import load_dotenv
from typesafe_sdk import Choice, Noul, TypeSafeClient

from app.database import get_connection
from app.event_processor import build_event_context, EVENT_PATH
from app.jev_adapter import build_jev_input


# Load TYPESAFE_API_KEY from .env
load_dotenv()


def load_saved_event_context(event_id):
    """
    Load an already processed event from SQLite.

    Does not modify invoices, payments, or event history.
    """

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                h.event_id,
                h.customer_id,
                h.sim_day,
                h.event_type,
                h.state_before_json,
                h.state_after_json,
                e.description
            FROM customer_state_history h
            JOIN customer_events e
                ON e.event_id = h.event_id
            WHERE h.event_id = ?
            """,
            (event_id,),
        ).fetchone()

    if row is None:
        raise ValueError(
            f"No saved event context found for {event_id}"
        )

    return {
        "event_id": row["event_id"],
        "customer_id": row["customer_id"],
        "sim_day": row["sim_day"],
        "previous_state": json.loads(
            row["state_before_json"]
        ),
        "current_state": json.loads(
            row["state_after_json"]
        ),
        "new_event": {
            "type": row["event_type"],
            "description": row["description"],
        },
    }


def evaluate_event_with_jev(
    event_path=EVENT_PATH,
    context=None,
):
    """
    Evaluate an event using Jev System One.

    If context is supplied, use it directly.

    Otherwise, preserve the original behavior:
    build context from the customer-message event file.

    This function makes ONE paid Jev API call.
    """

    # 1. Build or accept event context.
    if context is None:
        context = build_event_context(event_path)

    # 2. Prepare structured input for Jev.
    state = build_jev_input(context)

    # 3. Define the three Jev questions.
    questions = {
        "meaningful_change": Noul(
            instructions=(
                "The NEW customer event provides meaningful new "
                "information about the future customer relationship. "
                "Evaluate the new event, not just existing financial risk. "
                "Routine accounting activity alone is not evidence "
                "of a meaningful relationship change."
            )
        ),

        "change_type": Choice(
            instructions=(
                "Classify the direction of the relationship change "
                "indicated by the NEW customer event. "
                "Use neutral for ordinary accounting activity "
                "without meaningful relationship evidence."
            ),
            criteria={
                "positive": (
                    "Evidence the customer relationship is improving"
                ),
                "negative": (
                    "Evidence the customer relationship is deteriorating"
                ),
                "neutral": (
                    "Routine activity without a meaningful change"
                ),
                "ambiguous": (
                    "Unclear or conflicting implications"
                ),
            },
        ),

        "needs_system_two": Noul(
            instructions=(
                "The NEW event provides sufficiently novel, "
                "consequential, or contradictory evidence about "
                "the customer relationship to justify an expensive "
                "deeper investigation right now. "
                "Routine invoice creation, ordinary purchases, "
                "and ordinary payments should NOT trigger escalation "
                "by themselves. "
                "Changes in receivables caused solely by new invoices "
                "or payments are not enough to justify escalation. "
                "Existing financial risk alone is not a reason to "
                "escalate unless this event adds materially new evidence."
            )
        ),
    }

    # 4. Make one Jev API call.
    print(
        f"Sending event {context['event_id']} "
        "to Jev System One...\n"
    )

    start_time = time.perf_counter()

    with TypeSafeClient(model="jev-latest") as client:
        response = client.system_one(
            state=json.dumps(state),
            questions=questions,
        )

    latency_ms = (
        time.perf_counter() - start_time
    ) * 1000

    # 5. Extract Jev results.
    meaningful_score = (
        response.nouls["meaningful_change"].noul
    )

    change_type = (
        response.choices["change_type"].choice
    )

    system_two_score = (
        response.nouls["needs_system_two"].noul
    )

    # 6. Apply escalation threshold.
    should_escalate = system_two_score >= 0.5

    return {
        "event_id": context["event_id"],
        "customer_id": context["customer_id"],
        "customer_name": (
            context["current_state"]["customer_name"]
        ),
        "event_type": context["new_event"]["type"],
        "meaningful_change_score": meaningful_score,
        "change_type": change_type,
        "needs_system_two_score": system_two_score,
        "should_escalate": should_escalate,
        "latency_ms": round(latency_ms, 2),
    }


if __name__ == "__main__":
    import sys

    # Usage:
    #
    # python3 -m app.jev_client
    #   Evaluates the original customer-message event.
    #
    # python3 -m app.jev_client demo-event-003
    #   Evaluates the saved payment event.
    #
    # python3 -m app.jev_client demo-event-002
    #   Evaluates the saved invoice event.

    if len(sys.argv) > 1:
        event_id = sys.argv[1]

        context = load_saved_event_context(event_id)

        result = evaluate_event_with_jev(
            context=context
        )
    else:
        result = evaluate_event_with_jev()

    print("========== JEV RESULTS ==========")
    print(json.dumps(result, indent=2))
    print("=================================")
