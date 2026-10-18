import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "company003_benchmark_v3"

load_dotenv(PROJECT_ROOT / ".env")

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY is missing from .env")

client = OpenAI(timeout=30.0, max_retries=0)

# Use an API-accessible model.
# We will freeze this model choice for the benchmark.
MODEL = "gpt-5.4-mini"

# Load ONE development event.
with open(DATASET_DIR / "dev_inputs.jsonl", encoding="utf-8") as f:
    event = json.loads(next(f))

SYSTEM_PROMPT = """
You are a customer relationship change detector for a business.

You receive:
- Previous customer event
- New customer event
- Old financial state
- Current financial state
- Financial event impact

Determine:
1. meaningful_change: whether the new event indicates a meaningful
   change in the ongoing customer relationship.
2. direction: positive, negative, or neutral.
3. escalation_needed: whether the event deserves deeper investigation
   by a more capable second-stage reasoning system.

Escalate substantial changes such as customer loss, serious financial
distress, major purchasing changes, or major relationship expansion.

Do not escalate routine administrative activity, ordinary payments,
or small fluctuations without significant relationship implications.

Treat hypothetical financial observations as observations, not as
posted accounting transactions.

Return only the requested classification.
"""

print("========== STEP 67 — FIRST GPT CLASSIFICATION ==========")
print("Model:", MODEL)
print("Event type:", event["new_event"]["event_type"])

start = time.perf_counter()

response = client.responses.create(
    model=MODEL,
    instructions=SYSTEM_PROMPT,
    input=json.dumps(event, ensure_ascii=False),
    text={
        "format": {
            "type": "json_schema",
            "name": "customer_change_classification",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "meaningful_change": {"type": "boolean"},
                    "direction": {
                        "type": "string",
                        "enum": ["positive", "negative", "neutral"]
                    },
                    "escalation_needed": {"type": "boolean"}
                },
                "required": [
                    "meaningful_change",
                    "direction",
                    "escalation_needed"
                ],
                "additionalProperties": False
            }
        }
    }
)

latency_ms = (time.perf_counter() - start) * 1000

prediction = json.loads(response.output_text)

print("\nGPT prediction:")
print(json.dumps(prediction, indent=2))

print(f"\nEnd-to-end API latency: {latency_ms:.2f} ms")

if response.usage:
    print("Input tokens:", response.usage.input_tokens)
    print("Output tokens:", response.usage.output_tokens)

print("\nPASS — First GPT classification completed!")