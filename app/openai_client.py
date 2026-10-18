
import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from app.jev_adapter import build_jev_input
from app.jev_client import load_saved_event_context


load_dotenv()


def generate_owner_notification(context, jev_result):
    """
    Generate an owner alert and a draft customer response.

    Makes ONE paid OpenAI API call only if Jev has
    already marked the event for escalation.

    Does not send emails or customer messages.
    """

    if jev_result["event_id"] != context["event_id"]:
        raise ValueError(
            "Jev result does not match the supplied event"
        )

    if jev_result["customer_id"] != context["customer_id"]:
        raise ValueError(
            "Jev result belongs to a different customer"
        )

    if not jev_result.get("should_escalate", False):
        print("Jev did not escalate this event. Skipping OpenAI.")
        return None

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing from .env"
        )

    state = build_jev_input(context)

    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are QuickBooks Pulse System Two, "
                    "an AI assistant helping a small-business owner "
                    "understand meaningful customer relationship changes. "
                    "Use only the provided event and financial facts. "
                    "Do not invent conversations, invoices, amounts, "
                    "promises, or customer intentions. "
                    "Clearly distinguish direct evidence from inference. "
                    "Provide concise, actionable owner-facing guidance. "
                    "Draft a professional customer message that acknowledges "
                    "the issue without admitting unverified facts or "
                    "promising refunds, discounts, or resolutions. "
                    "The draft requires human approval and must never "
                    "be represented as already sent. "
                    "Return valid JSON with exactly these keys: "
                    "alert_title, severity, owner_summary, "
                    "evidence, recommended_action, "
                    "customer_message_draft. "
                    "severity must be low, medium, or high. "
                    "evidence must be an array of short strings."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "event_context": state,
                        "jev_assessment": {
                            "meaningful_change_score": jev_result[
                                "meaningful_change_score"
                            ],
                            "change_type": jev_result["change_type"],
                            "needs_system_two_score": jev_result[
                                "needs_system_two_score"
                            ],
                        },
                    }
                ),
            },
        ],
    )

    content = response.choices[0].message.content

    if not content:
        raise RuntimeError("OpenAI returned an empty response")

    notification = json.loads(content)

    required_fields = {
        "alert_title",
        "severity",
        "owner_summary",
        "evidence",
        "recommended_action",
        "customer_message_draft",
    }

    if not required_fields.issubset(notification):
        raise ValueError(
            "OpenAI response is missing required fields: "
            f"{required_fields - set(notification)}"
        )

    if notification["severity"] not in {
        "low",
        "medium",
        "high",
    }:
        raise ValueError("Invalid severity returned by OpenAI")

    if not isinstance(notification["evidence"], list):
        raise ValueError("Evidence must be a list")

    return {
        "event_id": context["event_id"],
        "customer_id": context["customer_id"],
        "customer_name": context["current_state"]["customer_name"],
        "requires_human_approval": True,
        "message_sent": False,
        "notification": notification,
    }




if __name__ == "__main__":
    # Local, free preparation check.
    # We do NOT call OpenAI from this block.

    context = load_saved_event_context("demo-event-003")

    print("OpenAI System Two client loaded successfully.")
    print("Saved event:", context["event_id"])
    print("Customer:", context["current_state"]["customer_name"])
    print("OpenAI API call made: False")
