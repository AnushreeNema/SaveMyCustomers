
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from sklearn.metrics import (
    precision_recall_fscore_support,
    accuracy_score,
    confusion_matrix,
)

# ============================================================
# CONFIGURATION — FROZEN GENERALIZATION BENCHMARK
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent

DATASET_DIR = PROJECT_ROOT / "cross_company_benchmark"

RESULTS_DIR = (
    PROJECT_ROOT / "outputs" / "gpt_generalization_v3"
)

load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT.parent / ".env")

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY is missing")

MODEL = "gpt-5.4-mini"
BATCH_SIZE = 20
TOTAL_EXAMPLES = 1302

# USD per 1 million tokens.
# These are standard API prices, NOT Batch API prices.
INPUT_PRICE_PER_M = 0.75
CACHED_INPUT_PRICE_PER_M = 0.075
OUTPUT_PRICE_PER_M = 4.50

INPUTS = DATASET_DIR / "multi_signal_model_inputs_v3.jsonl"
LABELS = DATASET_DIR / "multi_signal_reference_labels_v3.jsonl"

PREDICTIONS = RESULTS_DIR / "gpt_predictions.jsonl"
REQUESTS = RESULTS_DIR / "gpt_requests.jsonl"
PROGRESS = RESULTS_DIR / "gpt_progress.json"
SUMMARY = RESULTS_DIR / "gpt_summary.json"
PENDING = RESULTS_DIR / "gpt_pending_request.json"

# ============================================================
# FROZEN GPT PROMPT — SAME AS COMPANY 003
# ============================================================

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

# ============================================================
# STRUCTURED OUTPUT SCHEMA
# ============================================================

SCHEMA = {
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
                        "enum": [
                            "positive",
                            "negative",
                            "neutral",
                        ],
                    },
                    "escalation_needed": {"type": "boolean"},
                },
                "required": [
                    "event_index",
                    "meaningful_change",
                    "direction",
                    "escalation_needed",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["predictions"],
    "additionalProperties": False,
}

# ============================================================
# FILE HELPERS
# ============================================================

def read_jsonl(path):
    if not path.exists():
        return []

    with path.open(encoding="utf-8") as f:
        return [
            json.loads(line)
            for line in f
            if line.strip()
        ]


def write_json(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")

    temp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    temp.replace(path)


def append_jsonl(path, records):
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )

        f.flush()
        os.fsync(f.fileno())


# ============================================================
# METRICS
# ============================================================

def binary_metrics(labels, predictions, field):
    truth = [int(row[field]) for row in labels]
    predicted = [int(row[field]) for row in predictions]

    precision, recall, f1, _ = (
        precision_recall_fscore_support(
            truth,
            predicted,
            average="binary",
            zero_division=0,
        )
    )

    tn, fp, fn, tp = confusion_matrix(
        truth,
        predicted,
        labels=[0, 1],
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
        "false_positive_rate": (
            float(fp / (fp + tn))
            if fp + tn
            else 0.0
        ),
    }


# ============================================================
# MAIN — ONE API REQUEST PER EXECUTION
# ============================================================

def main():
    print("=" * 55)
    print("GPT GENERALIZATION BENCHMARK")
    print("=" * 55)

    # --------------------------------------------------------
    # 1. Validate frozen inputs
    # --------------------------------------------------------

    events = read_jsonl(INPUTS)
    labels = read_jsonl(LABELS)

    assert len(events) == TOTAL_EXAMPLES, (
        f"Expected {TOTAL_EXAMPLES} inputs, got {len(events)}"
    )

    assert len(labels) == TOTAL_EXAMPLES, (
        f"Expected {TOTAL_EXAMPLES} labels, got {len(labels)}"
    )

    event_ids = [row["example_id"] for row in events]
    label_by_id = {
        row["example_id"]: row
        for row in labels
    }

    assert len(set(event_ids)) == TOTAL_EXAMPLES
    assert len(label_by_id) == TOTAL_EXAMPLES
    assert set(event_ids) == set(label_by_id)

    # Align labels by example_id, not file position.
    aligned_labels = [
        label_by_id[eid]
        for eid in event_ids
    ]

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # 2. Inspect checkpoints
    # --------------------------------------------------------

    saved = read_jsonl(PREDICTIONS)
    history = read_jsonl(REQUESTS)

    saved_indices = [
        row["event_index"]
        for row in saved
    ]

    assert saved_indices == list(range(len(saved))), (
        "Prediction checkpoint indices are inconsistent."
    )

    assert len(saved) <= TOTAL_EXAMPLES

    completed_in_history = sum(
        row["events_completed"]
        for row in history
    )

    assert completed_in_history == len(saved), (
        "Request history and prediction checkpoint disagree. "
        "Inspect files before continuing."
    )

    if PENDING.exists():
        raise RuntimeError(
            f"Unresolved pending request: {PENDING}\n"
            "Do NOT rerun automatically. Inspect the raw "
            "response and checkpoints first."
        )

    start_index = len(saved)

    if start_index == TOTAL_EXAMPLES:
        print("PASS — All 1302 examples already completed.")
        print("No API request sent.")
        return

    end_index = min(
        start_index + BATCH_SIZE,
        TOTAL_EXAMPLES,
    )

    # --------------------------------------------------------
    # 3. Prepare exactly 20 financial inputs
    # --------------------------------------------------------

    batch = [
        {
            "event_index": i,
            "event": events[i]["input"],
        }
        for i in range(start_index, end_index)
    ]

    assert len(batch) <= BATCH_SIZE
    assert all(
        "example_id" not in item
        for item in batch
    )

    print("Model:", MODEL)
    print("Total benchmark examples:", TOTAL_EXAMPLES)
    print("Previously completed:", start_index)
    print("Current batch size:", len(batch))
    print(
        "Event indices:",
        start_index,
        "through",
        end_index - 1,
    )
    print("Scenario IDs sent: NO")
    print("Reference labels sent: NO")
    print("Automatic retries: DISABLED")
    print("Requests this execution: MAXIMUM ONE")

    # --------------------------------------------------------
    # 4. Mark request as pending BEFORE API call
    # --------------------------------------------------------

    write_json(
        PENDING,
        {
            "model": MODEL,
            "start_index": start_index,
            "end_index": end_index,
            "status": "request_may_have_been_sent",
            "note": (
                "Do not retry until this pending "
                "request has been reconciled."
            ),
        },
    )

    # --------------------------------------------------------
    # 5. Make ONE billable GPT request
    # --------------------------------------------------------

    client = OpenAI(
        timeout=120.0,
        max_retries=0,
    )

    print("\nSending ONE GPT request...")

    start_time = time.perf_counter()

    response = client.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT,
        input=json.dumps(
            batch,
            ensure_ascii=False,
        ),
        text={
            "format": {
                "type": "json_schema",
                "name": "customer_batch_classification",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    )

    latency_seconds = (
        time.perf_counter() - start_time
    )

    # --------------------------------------------------------
    # 6. Save raw response BEFORE validation
    # --------------------------------------------------------

    raw_path = (
        RESULTS_DIR
        / f"gpt_raw_batch_{start_index:04d}.json"
    )

    usage = response.usage

    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens

    input_details = getattr(
        usage,
        "input_tokens_details",
        None,
    )

    cached_tokens = (
        getattr(
            input_details,
            "cached_tokens",
            0,
        )
        or 0
    )

    write_json(
        raw_path,
        {
            "response_id": response.id,
            "model": MODEL,
            "start_index": start_index,
            "end_index": end_index,
            "output_text": response.output_text,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "output_tokens": output_tokens,
            "latency_seconds": latency_seconds,
        },
    )

    # --------------------------------------------------------
    # 7. Validate all predictions
    # --------------------------------------------------------

    parsed = json.loads(response.output_text)
    predictions = parsed["predictions"]

    expected_indices = list(
        range(start_index, end_index)
    )

    actual_indices = [
        row["event_index"]
        for row in predictions
    ]

    assert len(predictions) == len(batch), (
        "Incomplete batch output."
    )

    assert actual_indices == expected_indices, (
        f"Unexpected prediction indices: {actual_indices}"
    )

    # --------------------------------------------------------
    # 8. Calculate batch cost
    # --------------------------------------------------------

    uncached_tokens = (
        input_tokens - cached_tokens
    )

    batch_cost = (
        uncached_tokens * INPUT_PRICE_PER_M
        + cached_tokens * CACHED_INPUT_PRICE_PER_M
        + output_tokens * OUTPUT_PRICE_PER_M
    ) / 1_000_000

    request_record = {
        "batch_number": len(history) + 1,
        "model": MODEL,
        "start_index": start_index,
        "end_index_exclusive": end_index,
        "events_completed": len(predictions),
        "response_id": response.id,
        "latency_seconds": latency_seconds,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": batch_cost,
    }

    # --------------------------------------------------------
    # 9. Save predictions and request statistics
    # --------------------------------------------------------

    # First save request metadata, then predictions.
    # If interrupted between writes, the next run stops
    # at the checkpoint consistency check.
    append_jsonl(
        REQUESTS,
        [request_record],
    )

    append_jsonl(
        PREDICTIONS,
        predictions,
    )

    # --------------------------------------------------------
    # 10. Calculate cumulative statistics
    # --------------------------------------------------------

    all_predictions = read_jsonl(PREDICTIONS)
    all_requests = read_jsonl(REQUESTS)

    completed = len(all_predictions)

    total_latency = sum(
        row["latency_seconds"]
        for row in all_requests
    )

    total_cost = sum(
        row["estimated_cost_usd"]
        for row in all_requests
    )

    total_input_tokens = sum(
        row["input_tokens"]
        for row in all_requests
    )

    total_cached_tokens = sum(
        row["cached_input_tokens"]
        for row in all_requests
    )

    total_output_tokens = sum(
        row["output_tokens"]
        for row in all_requests
    )

    evaluated_labels = aligned_labels[:completed]

    meaningful = binary_metrics(
        evaluated_labels,
        all_predictions,
        "meaningful_change",
    )

    escalation = binary_metrics(
        evaluated_labels,
        all_predictions,
        "escalation_needed",
    )

    direction_accuracy = float(
        accuracy_score(
            [
                row["direction"]
                for row in evaluated_labels
            ],
            [
                row["direction"]
                for row in all_predictions
            ],
        )
    )

    summary = {
        "model": MODEL,
        "benchmark": "cross_company_multi_signal_v3",
        "examples_completed": completed,
        "total_examples": TOTAL_EXAMPLES,
        "requests_completed": len(all_requests),
        "batch_size": BATCH_SIZE,
        "total_api_latency_seconds": total_latency,
        "amortized_latency_ms_per_event": (
            1000 * total_latency / completed
        ),
        "total_estimated_api_cost_usd": total_cost,
        "estimated_cost_per_1000_events_usd": (
            1000 * total_cost / completed
        ),
        "total_input_tokens": total_input_tokens,
        "total_cached_input_tokens": total_cached_tokens,
        "total_output_tokens": total_output_tokens,
        "meaningful_change": meaningful,
        "escalation_needed": escalation,
        "direction_accuracy": direction_accuracy,
    }

    write_json(
        SUMMARY,
        summary,
    )

    write_json(
        PROGRESS,
        {
            "completed": completed,
            "remaining": TOTAL_EXAMPLES - completed,
            "next_event_index": completed,
            "requests_completed": len(all_requests),
            "total_estimated_cost_usd": total_cost,
            "total_api_latency_seconds": total_latency,
        },
    )

    # All required outputs are saved.
    PENDING.unlink()

    # --------------------------------------------------------
    # 11. Print batch results
    # --------------------------------------------------------

    print("\n" + "=" * 55)
    print("BATCH RESULTS")
    print("=" * 55)

    print("Events classified:", len(predictions))
    print(
        f"API latency: {latency_seconds:.3f} seconds"
    )
    print("Input tokens:", input_tokens)
    print("Cached input tokens:", cached_tokens)
    print("Output tokens:", output_tokens)
    print(
        f"Estimated batch cost: ${batch_cost:.6f}"
    )

    # --------------------------------------------------------
    # 12. Print cumulative results
    # --------------------------------------------------------

    print("\n" + "=" * 55)
    print("CUMULATIVE RESULTS")
    print("=" * 55)

    print(
        f"Progress: {completed}/{TOTAL_EXAMPLES}"
    )
    print("Requests completed:", len(all_requests))
    print(
        f"Total API latency: {total_latency:.3f} seconds"
    )
    print(
        f"Total estimated cost: ${total_cost:.6f}"
    )
    print(
        "Amortized latency:",
        f"{summary['amortized_latency_ms_per_event']:.2f}",
        "ms/event",
    )
    print(
        "Estimated cost per 1000 events:",
        f"${summary['estimated_cost_per_1000_events_usd']:.6f}",
    )

    print(
        f"Meaningful F1: {meaningful['f1']:.4f}"
    )
    print(
        f"Escalation F1: {escalation['f1']:.4f}"
    )
    print(
        f"Direction accuracy: {direction_accuracy:.4f}"
    )
    print(
        "False escalations:",
        escalation["FP"],
    )

    print("\nSaved predictions:", PREDICTIONS)
    print("Saved request statistics:", REQUESTS)
    print("Saved progress:", PROGRESS)
    print("Saved summary:", SUMMARY)

    print(
        "\nPASS — One GPT batch completed. "
        "Script stopped."
    )


if __name__ == "__main__":
    main()
