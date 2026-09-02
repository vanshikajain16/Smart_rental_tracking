"""Run Stage 1 and write its outputs.

    python -m scripts.run_stage1          # from the project root
    python scripts/run_stage1.py

Writes:
  data/processed/stage1_rows.csv     - per-rental-cycle anomaly detail
  data/processed/stage1_assets.json  - list of unified per-asset records

Prints row-level evaluation metrics against is_anomaly_ground_truth.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import STAGE1_ASSETS_JSON, STAGE1_ROWS_CSV  # noqa: E402
from src.data_loader import load_rentals  # noqa: E402
from src.schema import validate_record  # noqa: E402
from src.stages.stage1 import evaluate_metrics, run_stage1  # noqa: E402


def main() -> None:
    df = load_rentals()
    assets, rows_df = run_stage1(df)

    for rec in assets:
        validate_record(rec)

    rows_df.to_csv(STAGE1_ROWS_CSV, index=False)
    with open(STAGE1_ASSETS_JSON, "w", encoding="utf-8") as fh:
        json.dump(assets, fh, indent=2)

    metrics = evaluate_metrics(rows_df)

    print(f"Loaded {len(df)} rental cycles across {df['Equipment ID'].nunique()} assets")
    print(f"Wrote {STAGE1_ROWS_CSV.relative_to(Path.cwd()) if STAGE1_ROWS_CSV.is_relative_to(Path.cwd()) else STAGE1_ROWS_CSV}")
    print(f"Wrote {STAGE1_ASSETS_JSON.relative_to(Path.cwd()) if STAGE1_ASSETS_JSON.is_relative_to(Path.cwd()) else STAGE1_ASSETS_JSON}  ({len(assets)} asset records)")

    print("\nRow-level anomaly detection vs is_anomaly_ground_truth")
    print("-" * 56)
    for k in ("n_rows", "tp", "fp", "fn", "tn"):
        print(f"  {k:<10} {metrics[k]}")
    for k in ("precision", "recall", "f1", "accuracy"):
        print(f"  {k:<10} {metrics[k]:.3f}")

    n_realloc = sum(1 for a in assets if a["reallocatable"])
    n_flagged = sum(1 for a in assets if a["reasons"])
    print(f"\nAsset records: {n_flagged}/{len(assets)} carry >=1 reason, "
          f"{n_realloc} flagged reallocatable")

    print("\nSample flagged asset records:")
    shown = 0
    for a in assets:
        if a["reasons"] and shown < 4:
            print(json.dumps(a, indent=2))
            shown += 1


if __name__ == "__main__":
    main()
