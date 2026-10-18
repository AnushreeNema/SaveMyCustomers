
import json
import os
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from sklearn.metrics import precision_recall_fscore_support, accuracy_score, confusion_matrix

# ---------- Configuration ----------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "company003_benchmark_v3"
RESULTS_DIR = PROJECT_ROOT / "llm_benchmark" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(PROJECT_ROOT / ".env")

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY is missing")

MODEL = "gpt-5.4-mini"
BATCH_SIZE = 20

# Verify these rates against current OpenAI pricing before running.
INPUT_PRICE_PER_M = 0.75
CACHED_INPUT_PRICE_PER_M = 0.075
OUTPUT_PRICE_PER_M = 4.50

DEV_INPUTS = DATASET_DIR / "dev_inputs.jsonl"
DEV_LABELS = DATASET_DIR / "dev_labels.jsonl"

PREDICTIONS = RESULTS_DIR / "gpt_predictions.jsonl"
REQUESTS = RESULTS_DIR / "gpt_requests.jsonl"
PROGRESS = RESULTS_DIR / "gpt_progress.json"
SUMMARY = RESULTS_DIR / "gpt_summary.json"
PENDING = RESULTS_DIR / "gpt_pending_request.json"

def read_jsonl(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )
    temporary.replace(path)

def append_jsonl(path, records):
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

def get_metrics(labels, predictions, field):
    truth = [int(y[field]) for y in labels]
    predicted = [int(p[field]) for p in predictions]

    precision, recall, f1, _ = precision_recall_fscore_support(
        truth, predicted, average="binary", zero_division=0
    )
    tn, fp, fn, tp = confusion_matrix(
        truth, predicted, labels=[0, 1]
    ).ravel()

    return {
        "accuracy": float(accuracy_score(truth, predicted)),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "TP": int(tp),
        "FP": int(fp),
        "FN": int(fn),
        "TN": int(tn),
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
    }

events = read_jsonl(DEV_INPUTS)
labels = read_jsonl(DEV_LABELS)

assert len(events) == len(labels) == 690

saved = read_jsonl(PREDICTIONS)
request_history = read_jsonl(REQUESTS)

indices = [p["event_index"] for p in saved]
assert indices == list(range(len(saved))), "Prediction checkpoint is inconsistent"

if PENDING.exists():
    raise RuntimeError(
        f"Pending request found: {PENDING}\n"
        "Do not retry automatically. Inspect whether the previous "
        "request succeeded and whether results were saved."
    )

# Ensure request history and saved predictions agree.
assert sum(r["events_completed"] for r in request_history) == len(saved), (
    "Request history and prediction count disagree. Inspect files."
)

start_index = len(saved)
end_index = min(start_index + BATCH_SIZE, len(events))

if start_index == len(events):
    print("All 690 development events are already complete.")
    raise SystemExit(0)

batch = [
    {"event_index": i, "event": events[i]}
    for i in range(start_index, end_index)
]

print("========== STEP 71 — MANUAL GPT REQUEST ==========")
print("Model:", MODEL)
print("Events:", start_index + 1, "through", end_index)
print("Previously completed:", start_index)
print("Requests this run: MAXIMUM ONE")
print("Automatic retries: DISABLED")

# Structured output: exactly one classification per input index.
schema = {
    "type": "object",
    "properties": {
        "predictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_index": {"type": "integer"},
                    "meaningful_change": {"type": "boolean"},
                    "direction": {
                        "type": "string",
                        "enum": ["positive", "negative", "neutral"]
                    },
                    "escalation_needed": {"type": "boolean"}
                },
                "required": [
                    "event_index",
                    "meaningful_change",
                    "direction",
                    "escalation_needed"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["predictions"],
    "additionalProperties": False
}

SYSTEM_PROMPT = """
You are a customer relationship change detector.

For EACH supplied customer event, independently classify:
1. meaningful_change: Does this event indicate a meaningful change
   in the ongoing customer relationship?
2. direction: positive, negative, or neutral.
3. escalation_needed: Does this event warrant deeper investigation
   by a second-stage reasoning system?

Escalate major relationship losses, financial distress, major purchasing
changes, or substantial relationship expansion.

Do not escalate routine administration, ordinary payments, or minor
fluctuations without meaningful relationship implications.

Hypothetical financial observations are reports, not posted accounting
transactions. Use their observed trends as evidence while distinguishing
them from historical accounting state.

Return exactly one prediction for each event_index.
Keep each event's classification independent of other events.
Return only the requested JSON.
"""

# Record intent BEFORE sending a billable request.
write_json(PENDING, {
    "model": MODEL,
    "start_index": start_index,
    "end_index": end_index,
    "status": "request_may_have_been_sent",
    "note": "Do not rerun until this file is reconciled."
})

client = OpenAI(timeout=120.0, max_retries=0)

start_time = time.perf_counter()

response = client.responses.create(
    model=MODEL,
    instructions=SYSTEM_PROMPT,
    input=json.dumps(batch, ensure_ascii=False),
    text={
        "format": {
            "type": "json_schema",
            "name": "customer_batch_classification",
            "strict": True,
            "schema": schema
        }
    }
)

latency_seconds = time.perf_counter() - start_time

# Save raw response immediately for recovery.
raw_path = RESULTS_DIR / f"gpt_raw_batch_{start_index:04d}.json"
write_json(raw_path, {
    "response_id": response.id,
    "output_text": response.output_text,
    "input_tokens": response.usage.input_tokens,
    "output_tokens": response.usage.output_tokens,
    "latency_seconds": latency_seconds,
})

parsed = json.loads(response.output_text)
predictions = parsed["predictions"]

expected_indices = list(range(start_index, end_index))
actual_indices = [p["event_index"] for p in predictions]

assert len(predictions) == len(batch), "Incomplete batch output"
assert actual_indices == expected_indices, (
    f"Unexpected event indices: {actual_indices}"
)

usage = response.usage
input_tokens = usage.input_tokens
output_tokens = usage.output_tokens

input_details = getattr(usage, "input_tokens_details", None)
cached_tokens = getattr(input_details, "cached_tokens", 0) or 0

cost = (
    (input_tokens - cached_tokens) * INPUT_PRICE_PER_M
    + cached_tokens * CACHED_INPUT_PRICE_PER_M
    + output_tokens * OUTPUT_PRICE_PER_M
) / 1_000_000

request_record = {
    "batch_number": len(request_history) + 1,
    "model": MODEL,
    "start_index": start_index,
    "end_index_exclusive": end_index,
    "events_completed": len(predictions),
    "response_id": response.id,
    "latency_seconds": latency_seconds,
    "input_tokens": input_tokens,
    "cached_input_tokens": cached_tokens,
    "output_tokens": output_tokens,
    "estimated_cost_usd": cost,
}

# Save predictions and request statistics.
append_jsonl(PREDICTIONS, predictions)
append_jsonl(REQUESTS, [request_record])

# Update cumulative statistics.
all_predictions = read_jsonl(PREDICTIONS)
all_requests = read_jsonl(REQUESTS)

completed = len(all_predictions)
evaluated_labels = labels[:completed]

total_cost = sum(r["estimated_cost_usd"] for r in all_requests)
total_latency = sum(r["latency_seconds"] for r in all_requests)

summary = {
    "model": MODEL,
    "split": "dev",
    "events_completed": completed,
    "total_events": len(events),
    "next_event_index": completed,
    "requests_completed": len(all_requests),
    "total_api_latency_seconds": total_latency,
    "amortized_latency_ms_per_event": (
        1000 * total_latency / completed
    ),
    "total_estimated_api_cost_usd": total_cost,
    "estimated_cost_per_1000_events_usd": (
        1000 * total_cost / completed
    ),
    "meaningful_change": get_metrics(
        evaluated_labels, all_predictions, "meaningful_change"
    ),
    "escalation_needed": get_metrics(
        evaluated_labels, all_predictions, "escalation_needed"
    ),
    "direction_accuracy": float(
        np.mean([
            y["direction"] == p["direction"]
            for y, p in zip(evaluated_labels, all_predictions)
        ])
    ),
}

write_json(SUMMARY, summary)
write_json(PROGRESS, {
    "completed": completed,
    "remaining": len(events) - completed,
    "next_event_index": completed,
    "total_cost_usd": total_cost,
    "total_api_latency_seconds": total_latency,
})

# All durable output files saved.
PENDING.unlink()

print("\nBATCH RESULTS")
print("Events classified:", len(predictions))
print(f"API latency: {latency_seconds:.3f} seconds")
print("Input tokens:", input_tokens)
print("Output tokens:", output_tokens)
print(f"Estimated batch cost: ${cost:.6f}")

print("\nCUMULATIVE RESULTS")
print(f"Progress: {completed}/{len(events)}")
print(f"Total API latency: {total_latency:.3f} seconds")
print(f"Total estimated cost: ${total_cost:.6f}")
print(f"Amortized latency: {summary['amortized_latency_ms_per_event']:.2f} ms/event")
print(f"Meaningful F1: {summary['meaningful_change']['f1']:.3f}")
print(f"Escalation F1: {summary['escalation_needed']['f1']:.3f}")
print(f"False escalations: {summary['escalation_needed']['FP']}")
print(f"Direction accuracy: {summary['direction_accuracy']:.3f}")

print("\nSaved predictions:", PREDICTIONS)
print("Saved request stats:", REQUESTS)
print("Saved summary:", SUMMARY)
print("\nPASS — One manual batch completed. Script stopped.")
