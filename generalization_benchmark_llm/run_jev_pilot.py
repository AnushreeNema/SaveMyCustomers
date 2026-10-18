
import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv
from typesafe_sdk import Choice, Noul, TypeSafeClient


# ============================================================
# CONFIGURATION
# ============================================================

BASE = Path(__file__).resolve().parent
DATA = BASE / "data" / "cross_company_benchmark"
OUTPUT = BASE / "outputs" / "multi_signal_pilot"
OUTPUT.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE / ".env")

MODEL = "jev-latest"
THRESHOLD = 0.50

# Original user-provided estimate; not verified current pricing.
INPUT_USD_PER_MILLION = 0.042

INPUTS = DATA / "multi_signal_jev_pilot_inputs.jsonl"
METADATA = DATA / "multi_signal_jev_pilot_metadata.csv"
MANIFEST = DATA / "multi_signal_jev_pilot_manifest.json"

PREDICTIONS = OUTPUT / "jev_predictions.jsonl"
REQUESTS = OUTPUT / "jev_requests.jsonl"
PENDING = OUTPUT / "jev_pending_request.json"
SUMMARY = OUTPUT / "jev_summary.json"


# ============================================================
# ORIGINAL JEV QUESTIONS — UNCHANGED
# ============================================================

QUESTIONS = {
    "meaningful_change": Noul(
        instructions=(
            "Does the NEW event provide meaningful new "
            "information about the future customer relationship? "
            "Compare the new event with the previous event and "
            "financial states. Do not treat existing financial "
            "risk alone as a new relationship change."
        )
    ),
    "change_type": Choice(
        instructions=(
            "Classify the direction of the relationship "
            "change indicated by the NEW event."
        ),
        criteria={
            "positive": "Evidence the relationship is improving",
            "negative": "Evidence the relationship is deteriorating",
            "neutral": "Routine activity without a meaningful change",
            "ambiguous": "Unclear or conflicting implications",
        },
    ),
    "needs_system_two": Noul(
        instructions=(
            "Does the NEW event provide sufficiently novel, "
            "consequential, or contradictory evidence about "
            "the customer relationship to justify deeper "
            "System Two investigation? Do not escalate "
            "routine invoices, ordinary purchases, or "
            "existing risk without new evidence."
        )
    ),
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


def append_jsonl(path, obj):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def write_json_atomic(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    tmp.replace(path)


def raw_path(index):
    return OUTPUT / f"jev_raw_event_{index:04d}.json"


# ============================================================
# DATASET VALIDATION
# ============================================================

def load_dataset():
    for path in (INPUTS, METADATA, MANIFEST):
        if not path.exists():
            raise FileNotFoundError(
                f"Missing dataset file: {path}"
            )

    manifest = json.loads(
        MANIFEST.read_text(encoding="utf-8")
    )

    digest = hashlib.sha256(
        INPUTS.read_bytes()
    ).hexdigest()

    if digest != manifest["inputs_sha256"]:
        raise RuntimeError(
            "Dataset SHA-256 mismatch. "
            "The frozen inputs have changed."
        )

    inputs = read_jsonl(INPUTS)

    with METADATA.open(
        encoding="utf-8",
        newline=""
    ) as f:
        metadata = list(csv.DictReader(f))

    if not (
        len(inputs)
        == len(metadata)
        == manifest["examples"]
    ):
        raise RuntimeError(
            "Dataset, metadata, and manifest counts differ."
        )

    ids = [row["example_id"] for row in metadata]

    if len(set(ids)) != len(ids):
        raise RuntimeError("Duplicate example IDs.")

    return inputs, metadata, manifest


# ============================================================
# CHECKPOINT VALIDATION
# ============================================================

def validate_prefix(rows, metadata, name):
    if len(rows) > len(metadata):
        raise RuntimeError(
            f"{name} has more rows than the dataset."
        )

    for index, row in enumerate(rows):
        if (
            row.get("event_index") != index
            or row.get("example_id")
            != metadata[index]["example_id"]
        ):
            raise RuntimeError(
                f"{name} checkpoint mismatch at index {index}."
            )


def validate_logs(metadata):
    predictions = read_jsonl(PREDICTIONS)
    requests = read_jsonl(REQUESTS)

    validate_prefix(predictions, metadata, "Predictions")
    validate_prefix(requests, metadata, "Requests")

    if len(predictions) != len(requests):
        raise RuntimeError(
            "Prediction and request counts differ. "
            "Inspect the logs before continuing."
        )

    return predictions, requests


# ============================================================
# CRASH RECOVERY
# ============================================================

def recover_pending(metadata):
    if not PENDING.exists():
        return False

    pending = json.loads(
        PENDING.read_text(encoding="utf-8")
    )

    index = pending["event_index"]
    example_id = pending["example_id"]
    saved_raw = raw_path(index)

    if (
        index < 0
        or index >= len(metadata)
        or metadata[index]["example_id"] != example_id
    ):
        raise RuntimeError(
            "Pending request does not match dataset."
        )

    if not saved_raw.exists():
        raise RuntimeError(
            f"Event {index} is pending, but no saved response "
            "exists. The API call may have been billed. "
            "Stopping to avoid an automatic duplicate request."
        )

    raw = json.loads(
        saved_raw.read_text(encoding="utf-8")
    )

    prediction = raw["prediction"]
    request = raw["request"]

    predictions = read_jsonl(PREDICTIONS)
    requests = read_jsonl(REQUESTS)

    validate_prefix(predictions, metadata, "Predictions")
    validate_prefix(requests, metadata, "Requests")

    for name, rows, expected, path in (
        ("Predictions", predictions, prediction, PREDICTIONS),
        ("Requests", requests, request, REQUESTS),
    ):
        if len(rows) == index:
            append_jsonl(path, expected)
        elif (
            len(rows) == index + 1
            and rows[index] == expected
        ):
            pass
        else:
            raise RuntimeError(
                f"{name} conflict during recovery."
            )

    validate_logs(metadata)
    PENDING.unlink()

    print(
        f"Recovered event {index + 1} "
        "without another API call."
    )
    return True


# ============================================================
# SUMMARY
# ============================================================

def update_summary(metadata):
    predictions, requests = validate_logs(metadata)

    latencies = [
        float(r["latency_ms"])
        for r in requests
    ]

    known_costs = [
        float(r["estimated_cost_usd"])
        for r in requests
        if r.get("estimated_cost_usd") is not None
    ]

    completed = len(predictions)

    summary = {
        "model": MODEL,
        "completed": completed,
        "total": len(metadata),
        "remaining": len(metadata) - completed,
        "average_latency_ms": (
            statistics.mean(latencies)
            if latencies else None
        ),
        "total_latency_seconds": sum(latencies) / 1000,
        "known_cost_subtotal_usd": sum(known_costs),
        "cost_estimate_complete": (
            len(known_costs) == completed
        ),
        "estimated_total_cost_usd": (
            sum(known_costs)
            if len(known_costs) == completed
            else None
        ),
    }

    write_json_atomic(SUMMARY, summary)
    return summary


# ============================================================
# ONE SEQUENTIAL JEV REQUEST
# ============================================================

def run_one(index, record, example_id):
    # Mark the request as potentially sent before calling API.
    write_json_atomic(
        PENDING,
        {
            "event_index": index,
            "example_id": example_id,
            "model": MODEL,
            "status": "request_may_have_been_sent",
        },
    )

    start = time.perf_counter()

    with TypeSafeClient(model=MODEL) as client:
        response = client.system_one(
            state=json.dumps(
                record,
                ensure_ascii=False
            ),
            questions=QUESTIONS,
        )

    latency_ms = (
        time.perf_counter() - start
    ) * 1000

    meaningful_score = float(
        response.nouls["meaningful_change"].noul
    )
    escalation_score = float(
        response.nouls["needs_system_two"].noul
    )
    direction = response.choices["change_type"].choice

    if not all(
        math.isfinite(s) and 0 <= s <= 1
        for s in (meaningful_score, escalation_score)
    ):
        raise ValueError(
            "Invalid Jev score. Inspect pending request."
        )

    if direction not in {
        "positive",
        "negative",
        "neutral",
        "ambiguous",
    }:
        raise ValueError(
            "Unexpected Jev direction. Inspect pending request."
        )

    usage = getattr(response, "usage", None)

    input_tokens = (
        getattr(usage, "input_tokens", None)
        if usage is not None else None
    )
    output_tokens = (
        getattr(usage, "output_tokens", None)
        if usage is not None else None
    )

    if (
        not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or input_tokens < 0
    ):
        input_tokens = None

    if (
        not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
        or output_tokens < 0
    ):
        output_tokens = None

    estimated_cost = (
        input_tokens
        * INPUT_USD_PER_MILLION
        / 1_000_000
        if input_tokens is not None
        else None
    )

    prediction = {
        "event_index": index,
        "example_id": example_id,
        "model": MODEL,
        "meaningful_change": (
            meaningful_score >= THRESHOLD
        ),
        "direction": direction,
        "escalation_needed": (
            escalation_score >= THRESHOLD
        ),
        "meaningful_score": meaningful_score,
        "escalation_score": escalation_score,
    }

    request = {
        "event_index": index,
        "example_id": example_id,
        "model": MODEL,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimated_cost,
    }

    # Save response before appending logs.
    write_json_atomic(
        raw_path(index),
        {
            "prediction": prediction,
            "request": request,
        },
    )

    append_jsonl(PREDICTIONS, prediction)
    append_jsonl(REQUESTS, request)

    PENDING.unlink()

    return prediction, request


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum new requests this run (default: 10)."
    )

    args = parser.parse_args()

    if args.limit < 0:
        raise ValueError(
            "--limit must be zero or positive."
        )

    inputs, metadata, manifest = load_dataset()

    # Resolve pending requests before validating paired logs.
    recovered = recover_pending(metadata)

    summary = update_summary(metadata)
    start_index = summary["completed"]

    print("\n========== JEV GENERALIZATION BENCHMARK ==========")
    print("Model:", MODEL)
    print("Dataset examples:", len(inputs))
    print("Dataset SHA-256:", manifest["inputs_sha256"])
    print("Already completed:", start_index)
    print("New API calls allowed:", args.limit)
    print("Execution mode: SEQUENTIAL")

    if recovered:
        print(
            "Recovered a previously saved response."
        )

    if args.limit == 0:
        print("\nValidation only. No API requests made.")
        return

    if not os.getenv("TYPESAFE_API_KEY"):
        raise RuntimeError(
            "TYPESAFE_API_KEY missing from .env"
        )

    stop_index = min(
        start_index + args.limit,
        len(inputs)
    )

    for index in range(start_index, stop_index):
        example_id = metadata[index]["example_id"]

        print(
            f"\n[{index + 1}/{len(inputs)}] "
            f"Sending: {example_id}",
            flush=True
        )

        # This call BLOCKS until the response arrives.
        prediction, request = run_one(
            index,
            inputs[index]["input"],
            example_id,
        )

        # Response has been saved before reaching here.
        summary = update_summary(metadata)

        print(
            "Saved | Meaningful:",
            prediction["meaningful_change"],
            "| Direction:",
            prediction["direction"],
            "| Escalation:",
            prediction["escalation_needed"],
            flush=True
        )

        print(
            f"Latency: {request['latency_ms']:.0f} ms "
            f"| Completed: {summary['completed']}",
            flush=True
        )

    print("\n========== RUN COMPLETE ==========")
    print("Completed:", summary["completed"])
    print("Remaining:", summary["remaining"])
    print(
        "Known estimated cost:",
        f"${summary['known_cost_subtotal_usd']:.8f}"
    )
    print("Predictions:", PREDICTIONS)


if __name__ == "__main__":
    main()
