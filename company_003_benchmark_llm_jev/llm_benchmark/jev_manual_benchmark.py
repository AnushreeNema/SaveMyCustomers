
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

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "company003_benchmark_v3"
RESULTS_DIR = ROOT / "llm_benchmark" / "results" / "jev"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(ROOT / ".env")

MODEL = "jev-latest"
THRESHOLD = 0.50

# User-provided pricing, not independently verified
INPUT_USD_PER_MILLION = 0.042
OUTPUT_USD_PER_MILLION = 0.0

INPUTS = DATA_DIR / "dev_inputs.jsonl"
LABELS = DATA_DIR / "dev_labels.jsonl"

PREDICTIONS = RESULTS_DIR / "jev_predictions.jsonl"
REQUESTS = RESULTS_DIR / "jev_requests.jsonl"
PROGRESS = RESULTS_DIR / "jev_progress.json"
SUMMARY = RESULTS_DIR / "jev_summary.json"
PENDING = RESULTS_DIR / "jev_pending_request.json"


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


def write_json(path, obj):
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())

    temporary.replace(path)


def append_jsonl(path, obj):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def raw_path(index):
    return RESULTS_DIR / f"jev_raw_event_{index:04d}.json"


def validate(predictions, requests):
    for name, rows in (
        ("predictions", predictions),
        ("requests", requests),
    ):
        indices = [row["event_index"] for row in rows]

        if indices != list(range(len(rows))):
            raise RuntimeError(
                f"{name} indices are not consecutive from zero."
            )

    if len(predictions) != len(requests):
        raise RuntimeError(
            "Prediction and request counts differ. "
            "Stop and reconcile before making another API call."
        )


# ============================================================
# CRASH RECOVERY
# ============================================================

def recover_if_needed():
    if not PENDING.exists():
        return False

    pending = json.loads(
        PENDING.read_text(encoding="utf-8")
    )

    index = pending["event_index"]
    saved_raw = raw_path(index)

    if not saved_raw.exists():
        raise RuntimeError(
            f"Pending event {index + 1} has no saved response. "
            "The request may already have been billed. "
            "Do not retry automatically."
        )

    raw = json.loads(
        saved_raw.read_text(encoding="utf-8")
    )

    prediction = raw["prediction"]
    request = raw["request"]

    if (
        prediction["event_index"] != index
        or request["event_index"] != index
    ):
        raise RuntimeError("Raw response index mismatch.")

    predictions = read_jsonl(PREDICTIONS)
    requests = read_jsonl(REQUESTS)

    for name, rows in (
        ("predictions", predictions),
        ("requests", requests),
    ):
        if [r["event_index"] for r in rows] != list(range(len(rows))):
            raise RuntimeError(f"{name} log is inconsistent.")

    # Append only missing records.
    if len(predictions) == index:
        append_jsonl(PREDICTIONS, prediction)
    elif (
        len(predictions) != index + 1
        or predictions[index] != prediction
    ):
        raise RuntimeError(
            "Prediction log conflicts with saved raw response."
        )

    if len(requests) == index:
        append_jsonl(REQUESTS, request)
    elif (
        len(requests) != index + 1
        or requests[index] != request
    ):
        raise RuntimeError(
            "Request log conflicts with saved raw response."
        )

    PENDING.unlink()

    print(
        f"Recovered event {index + 1} "
        "without another API request."
    )

    return True


# ============================================================
# METRICS
# ============================================================

def binary_metrics(labels, predictions, field):
    tp = fp = fn = tn = 0

    for label, prediction in zip(labels, predictions):
        actual = bool(label[field])
        predicted = bool(prediction[field])

        if actual and predicted:
            tp += 1
        elif not actual and predicted:
            fp += 1
        elif actual and not predicted:
            fn += 1
        else:
            tn += 1

    n = len(predictions)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0

    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )

    return {
        "accuracy": (tp + tn) / n if n else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "TN": tn,
        "false_positive_rate": (
            fp / (fp + tn) if fp + tn else 0.0
        ),
    }


def percentile(values, percent):
    if not values:
        return None

    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100

    lower = math.floor(position)
    upper = math.ceil(position)

    return (
        ordered[lower]
        + (ordered[upper] - ordered[lower])
        * (position - lower)
    )


def update_summary(events, labels):
    predictions = read_jsonl(PREDICTIONS)
    requests = read_jsonl(REQUESTS)

    validate(predictions, requests)

    completed = len(predictions)

    latencies = [
        float(request["latency_ms"])
        for request in requests
    ]

    known_costs = [
        request["estimated_cost_usd"]
        for request in requests
        if request.get("estimated_cost_usd") is not None
    ]

    known_tokens = [
        request["input_tokens"]
        for request in requests
        if request.get("input_tokens") is not None
    ]

    all_costs_known = len(known_costs) == completed

    summary = {
        "model": MODEL,
        "split": "dev",
        "threshold": THRESHOLD,
        "events_completed": completed,
        "total_events": len(events),
        "next_event_index": completed,
        "requests_completed": len(requests),

        "total_api_latency_seconds": sum(latencies) / 1000,

        "average_latency_ms_per_event": (
            statistics.mean(latencies)
            if latencies else None
        ),

        "median_latency_ms": (
            statistics.median(latencies)
            if latencies else None
        ),

        "p95_latency_ms": percentile(latencies, 95),
        "p99_latency_ms": percentile(latencies, 99),

        "total_input_tokens_known": sum(known_tokens),

        "events_with_known_input_tokens": len(known_tokens),

        "known_cost_subtotal_usd": sum(known_costs),

        "total_estimated_api_cost_usd": (
            sum(known_costs)
            if all_costs_known
            else None
        ),

        "estimated_cost_per_1000_events_usd": (
            1000 * sum(known_costs) / completed
            if all_costs_known and completed
            else None
        ),

        "meaningful_change": (
            binary_metrics(
                labels[:completed],
                predictions,
                "meaningful_change",
            )
            if completed else None
        ),

        "escalation_needed": (
            binary_metrics(
                labels[:completed],
                predictions,
                "escalation_needed",
            )
            if completed else None
        ),

        "direction_accuracy": (
            sum(
                prediction["direction"] == label["direction"]
                for prediction, label in zip(
                    predictions, labels[:completed]
                )
            ) / completed
            if completed else None
        ),

        "pricing": {
            "input_usd_per_million": INPUT_USD_PER_MILLION,
            "output_usd_per_million": OUTPUT_USD_PER_MILLION,
            "source": "User-provided, not independently verified",
        },
    }

    write_json(SUMMARY, summary)

    write_json(
        PROGRESS,
        {
            "completed": completed,
            "remaining": len(events) - completed,
            "next_event_index": completed,
            "total_api_latency_seconds": (
                summary["total_api_latency_seconds"]
            ),
            "total_estimated_api_cost_usd": (
                summary["total_estimated_api_cost_usd"]
            ),
            "known_cost_subtotal_usd": (
                summary["known_cost_subtotal_usd"]
            ),
        },
    )

    return summary


# ============================================================
# FIXED JEV QUESTIONS
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
            "positive": (
                "Evidence the relationship is improving"
            ),
            "negative": (
                "Evidence the relationship is deteriorating"
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
# MAIN — ONE JEV REQUEST PER MANUAL RUN
# ============================================================

def main():
    events = read_jsonl(INPUTS)
    labels = read_jsonl(LABELS)

    if len(events) != 690 or len(labels) != 690:
        raise RuntimeError(
            "Expected exactly 690 DEV inputs and labels."
        )

    # Recover interrupted saving, if possible.
    # Recovery runs do not send another API request.
    recovered = recover_if_needed()

    summary = update_summary(events, labels)
    index = summary["events_completed"]

    print("========== JEV MANUAL BENCHMARK ==========")
    print("Model:", MODEL)
    print(f"Completed: {index}/{len(events)}")
    print("Maximum SDK calls this execution: 1")

    if recovered:
        print(
            "Recovery complete. No API request made. "
            "Run again manually for the next event."
        )
        return

    if index == len(events):
        print("\nAll 690 Jev events are complete.")
        print("Final summary:", SUMMARY)
        return

    if not os.getenv("TYPESAFE_API_KEY"):
        raise RuntimeError(
            "TYPESAFE_API_KEY missing from project .env"
        )

    print(f"\nSending event {index + 1} of {len(events)}")

    # Mark request pending before making the API call.
    write_json(
        PENDING,
        {
            "event_index": index,
            "model": MODEL,
            "status": "request_may_have_been_sent",
        },
    )

    start_time = time.perf_counter()

    with TypeSafeClient(model=MODEL) as client:
        response = client.system_one(
            state=json.dumps(
                events[index],
                ensure_ascii=False,
            ),
            questions=QUESTIONS,
        )

    latency_ms = (
        time.perf_counter() - start_time
    ) * 1000

    meaningful_score = float(
        response.nouls["meaningful_change"].noul
    )

    escalation_score = float(
        response.nouls["needs_system_two"].noul
    )

    direction = response.choices["change_type"].choice

    if not all(
        math.isfinite(score) and 0 <= score <= 1
        for score in (
            meaningful_score,
            escalation_score,
        )
    ):
        raise ValueError(
            "Invalid Noul score. Inspect pending request "
            "before retrying."
        )

    if direction not in (
        "positive",
        "negative",
        "neutral",
        "ambiguous",
    ):
        raise ValueError(
            "Unexpected direction. Inspect pending request "
            "before retrying."
        )

    # --------------------------------------------------------
    # TOKEN USAGE AND COST
    # --------------------------------------------------------

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

    estimated_cost = (
        input_tokens * INPUT_USD_PER_MILLION / 1_000_000
        if input_tokens is not None
        else None
    )

    # --------------------------------------------------------
    # PREDICTION AND REQUEST RECORD
    # --------------------------------------------------------

    prediction = {
        "event_index": index,
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
        "model": MODEL,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimated_cost,
    }

    # Save raw result before updating append-only logs.
    write_json(
        raw_path(index),
        {
            "prediction": prediction,
            "request": request,
        },
    )

    append_jsonl(PREDICTIONS, prediction)
    append_jsonl(REQUESTS, request)

    summary = update_summary(events, labels)

    # Clear pending only after everything was saved.
    PENDING.unlink()

    # --------------------------------------------------------
    # DISPLAY RESULTS
    # --------------------------------------------------------

    print("\n========== EVENT RESULT ==========")

    print("Meaningful score:", meaningful_score)
    print(
        "Meaningful change:",
        prediction["meaningful_change"],
    )

    print("Direction:", direction)

    print("Escalation score:", escalation_score)
    print(
        "Escalation needed:",
        prediction["escalation_needed"],
    )

    print(f"Latency: {latency_ms:.2f} ms")

    print(
        "Input tokens:",
        input_tokens
        if input_tokens is not None
        else "unavailable",
    )

    if estimated_cost is not None:
        print(f"Estimated event cost: ${estimated_cost:.8f}")
    else:
        print("Estimated event cost: unavailable")

    print("\n========== CUMULATIVE METRICS ==========")

    print(
        f"Progress: {summary['events_completed']}/690"
    )

    print(
        f"Meaningful F1: "
        f"{summary['meaningful_change']['f1']:.3f}"
    )

    print(
        f"Escalation F1: "
        f"{summary['escalation_needed']['f1']:.3f}"
    )

    print(
        "False escalations:",
        summary["escalation_needed"]["FP"],
    )

    print(
        f"Direction accuracy: "
        f"{summary['direction_accuracy']:.3f}"
    )

    print(
        f"Mean event latency: "
        f"{summary['average_latency_ms_per_event']:.2f} ms"
    )

    print(
        f"Total API latency: "
        f"{summary['total_api_latency_seconds']:.3f} s"
    )

    print(
        f"Known cost subtotal: "
        f"${summary['known_cost_subtotal_usd']:.8f}"
    )

    print(
        "Cost available for:",
        f"{summary['events_with_known_input_tokens']}/"
        f"{summary['events_completed']} events",
    )

    if summary["total_estimated_api_cost_usd"] is None:
        print(
            "Complete estimated cost: unavailable "
            "(one or more events lack token usage)"
        )
    else:
        print(
            "Complete estimated cost:",
            f"${summary['total_estimated_api_cost_usd']:.8f}",
        )

    print("\nSummary saved:", SUMMARY)
    print("Next event:", summary["next_event_index"] + 1)

    print("\nPASS — One Jev event saved. Script stopped.")


if __name__ == "__main__":
    main()
