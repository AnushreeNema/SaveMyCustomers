import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEV_PATH = PROJECT_ROOT / "company003_benchmark_v3" / "dev_inputs.jsonl"

with DEV_PATH.open(encoding="utf-8") as f:
    first_event = json.loads(next(f))

print("========== STEP 75 — JEV INPUT INSPECTION ==========")
print("Top-level fields:", list(first_event.keys()))

for key, value in first_event.items():
    print(f"{key}: {type(value).__name__}")

print("\nNo API requests made.")
print("PASS — Development input inspected!")