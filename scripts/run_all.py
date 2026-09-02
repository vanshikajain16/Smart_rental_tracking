"""Run the whole pipeline end to end, in order.

    python scripts/run_all.py

Each stage runs in its own fresh Python process (the stages have some
same-named helper modules, e.g. two `feature_builder.py`, so they must not
share an interpreter). Produces every file the API / frontend read:

  data/processed/stage1_output.csv
  data/processed/stage2_demand_model.json
  data/processed/stage3_output.csv          (+ backend/stage3_scoring/model.pkl)
  data/processed/stage4_recommendations.json
  data/processed/stage4_customer_aggregate.json
  data/processed/pipeline_output.json
  data/processed/customers.csv              (Reliability Score / Risk Tier filled)
  data/processed/stage5_customer_scores.csv (+ backend/stage5_customer_score/model.pkl)

Then start the servers yourself:
  python backend/api/main.py
  cd frontend && npm install && npm run dev
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

STEPS = [
    ("Stage 1  rule-based anomaly flags",   "backend/stage1_rules/anomaly_flags.py"),
    ("Stage 2  demand forecasting (train)",  "backend/stage2_forecasting/train_holt_winters.py"),
    ("Stage 3  reallocatable classifier",    "backend/stage3_scoring/train_classifier.py"),
    ("Stage 4  reallocation engine",         "backend/stage4_matching/reallocation_engine.py"),
    ("Pipeline 1->4  per-asset JSON",        "backend/stage4_matching/pipeline.py"),
    ("Stage 5  customer reliability",        "backend/stage5_customer_score/train_classifier.py"),
    ("Stage 5  SMS reminder preview",        "backend/stage5_customer_score/sms_alerts.py"),
]


def main() -> int:
    for i, (label, rel) in enumerate(STEPS, 1):
        print("\n" + "#" * 78)
        print(f"# [{i}/{len(STEPS)}] {label}")
        print(f"#   {rel}")
        print("#" * 78)
        t0 = time.time()
        result = subprocess.run([sys.executable, str(REPO_ROOT / rel)],
                                cwd=REPO_ROOT)
        if result.returncode != 0:
            print(f"\n!! step {i} ({rel}) exited {result.returncode} - stopping")
            return result.returncode
        print(f"\n-- done in {time.time() - t0:.1f}s")

    print("\n" + "=" * 78)
    print("ALL STAGES COMPLETE")
    print("=" * 78)
    print("next:")
    print("  python backend/api/main.py                  # API  http://127.0.0.1:8000")
    print("  cd frontend && npm install && npm run dev   # UI   http://localhost:5173")
    return 0


if __name__ == "__main__":
    sys.exit(main())
