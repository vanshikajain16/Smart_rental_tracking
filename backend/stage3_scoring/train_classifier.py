"""Stage 3 - train the "truly reallocatable" RandomForest and score every cycle.

    python backend/stage3_scoring/train_classifier.py

Pipeline
--------
1. build point-in-time features (feature_builder.build_features)
2. drop each asset's last cycle (no known future -> no label)
3. stratified 75/25 split -> classification_report on the held-out test rows
4. GroupKFold(5) by Equipment ID -> a stricter cross-check where no asset spans
   train and test folds
5. LEAKAGE GUARD: if held-out accuracy >= 0.90 or ROC-AUC >= 0.93, stop, print
   feature importances, and exit WITHOUT saving or scoring. The signal here
   (idle history -> future rental gap) is genuinely weak; a near-perfect score
   means a feature is the label in disguise, which is the bug a prior version
   shipped.
6. otherwise refit on all labelled rows, save model.pkl (+ model_meta.json),
   and score all 826 cycles into data/processed/stage3_output.csv.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupKFold, cross_val_predict, train_test_split
from sklearn.pipeline import Pipeline

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from feature_builder import (  # noqa: E402
    FEATURE_COLUMNS,
    INPUT_CSV,
    LABEL_THRESHOLD_DAYS,
    build_features,
)

REPO_ROOT = HERE.parents[1]
MODEL_PKL = HERE / "model.pkl"
MODEL_META = HERE / "model_meta.json"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "stage3_output.csv"

RANDOM_STATE = 42
TEST_SIZE = 0.25
REALLOC_THRESHOLD = 0.5

# Leakage tripwires. A weak-but-real model should land well under these.
LEAK_ACC = 0.90
LEAK_AUC = 0.93


def make_pipeline() -> Pipeline:
    return Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("rf", RandomForestClassifier(
            n_estimators=400,
            max_depth=6,
            min_samples_leaf=5,
            class_weight="balanced_subsample",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )),
    ])


def main() -> None:
    feats = build_features(pd.read_csv(INPUT_CSV))
    train = feats[~feats["is_last_cycle"]].copy()
    train["label"] = train["label"].astype(int)

    X = train[FEATURE_COLUMNS]
    y = train["label"].to_numpy()
    groups = train["Equipment ID"].to_numpy()

    print("=" * 78)
    print("STAGE 3 - 'truly reallocatable' classifier")
    print("=" * 78)
    print(f"label rule            : gap_days_to_next_checkout >= "
          f"{LABEL_THRESHOLD_DAYS}  ->  1")
    print(f"trainable rows        : {len(train)}  "
          f"(dropped {int(feats['is_last_cycle'].sum())} last-cycle rows)")
    print(f"positives             : {y.mean():.3f}")
    print(f"features ({len(FEATURE_COLUMNS)})        : {FEATURE_COLUMNS}")

    # ---- 1. stratified hold-out ------------------------------------- #
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
    pipe = make_pipeline()
    pipe.fit(X_tr, y_tr)
    proba_te = pipe.predict_proba(X_te)[:, 1]
    pred_te = (proba_te >= REALLOC_THRESHOLD).astype(int)

    acc = accuracy_score(y_te, pred_te)
    auc = roc_auc_score(y_te, proba_te)

    print("\n" + "-" * 78)
    print(f"HELD-OUT TEST ({len(y_te)} rows)")
    print("-" * 78)
    print(classification_report(y_te, pred_te,
                                target_names=["quiet (0)", "reallocatable (1)"],
                                digits=3))
    print("confusion matrix [rows=true, cols=pred]:")
    print(confusion_matrix(y_te, pred_te))
    print(f"\naccuracy = {acc:.3f}    ROC-AUC = {auc:.3f}")

    importances = (pd.Series(pipe.named_steps["rf"].feature_importances_,
                             index=FEATURE_COLUMNS)
                   .sort_values(ascending=False))
    print("\nfeature importances:")
    for name, val in importances.items():
        print(f"  {name:<26} {val:.3f}")

    # ---- 2. grouped cross-check ----------------------------------- #
    gkf = GroupKFold(n_splits=5)
    oof = cross_val_predict(make_pipeline(), X, y, groups=groups, cv=gkf,
                            method="predict_proba", n_jobs=-1)[:, 1]
    oof_pred = (oof >= REALLOC_THRESHOLD).astype(int)
    g_acc = accuracy_score(y, oof_pred)
    g_f1 = f1_score(y, oof_pred, average="macro")
    g_auc = roc_auc_score(y, oof)
    print("\n" + "-" * 78)
    print("GroupKFold(5) by Equipment ID  (no asset spans folds)")
    print("-" * 78)
    print(f"accuracy = {g_acc:.3f}    macro-F1 = {g_f1:.3f}    ROC-AUC = {g_auc:.3f}")
    print(f"baseline (predict majority) accuracy = {max(y.mean(), 1 - y.mean()):.3f}")

    # ---- 3. leakage guard --------------------------------------- #
    if acc >= LEAK_ACC or auc >= LEAK_AUC or g_auc >= LEAK_AUC:
        print("\n" + "!" * 78)
        print("SUSPECTED LABEL LEAKAGE - held-out performance is implausibly high")
        print(f"  held-out accuracy {acc:.3f} (trip >= {LEAK_ACC})")
        print(f"  held-out ROC-AUC  {auc:.3f} (trip >= {LEAK_AUC})")
        print(f"  grouped ROC-AUC   {g_auc:.3f}")
        print("  Predicting a ~14-day-out rental gap from prior usage is a weak")
        print("  signal; ~perfect scores mean a feature encodes the label.")
        print("  Inspect the top feature importances above against the label")
        print("  definition. NOT saving model.pkl and NOT writing stage3_output.csv.")
        print("!" * 78)
        sys.exit(1)

    print("\nleakage guard: PASS "
          f"(held-out acc {acc:.3f} < {LEAK_ACC}, AUC {auc:.3f} < {LEAK_AUC};"
          f" grouped AUC {g_auc:.3f}) - weak but real signal, as expected.")

    # ---- 4. refit on all labelled rows, save --------------------- #
    final = make_pipeline().fit(X, y)
    joblib.dump({"pipeline": final, "features": FEATURE_COLUMNS,
                 "threshold": REALLOC_THRESHOLD,
                 "label_threshold_days": LABEL_THRESHOLD_DAYS}, MODEL_PKL)
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "features": FEATURE_COLUMNS,
        "label_rule": f"gap_days_to_next_checkout >= {LABEL_THRESHOLD_DAYS}",
        "n_trainable_rows": int(len(train)),
        "positive_rate": round(float(y.mean()), 4),
        "holdout": {"accuracy": round(acc, 4), "roc_auc": round(auc, 4)},
        "groupkfold": {"accuracy": round(g_acc, 4), "macro_f1": round(g_f1, 4),
                       "roc_auc": round(g_auc, 4)},
        "feature_importances": {k: round(float(v), 4)
                                for k, v in importances.items()},
        "reallocatable_threshold": REALLOC_THRESHOLD,
    }
    MODEL_META.write_text(json.dumps(meta, indent=2))
    print(f"\nsaved {MODEL_PKL.relative_to(REPO_ROOT)}  (+ model_meta.json)")

    # ---- 5. score every cycle ---------------------------------- #
    raw = pd.read_csv(INPUT_CSV)
    merge_cols = ["Equipment ID", "cycle_number", "is_last_cycle", "label"]
    merge_cols += [c for c in FEATURE_COLUMNS if c not in merge_cols]
    scored = raw.merge(
        feats[merge_cols],
        on=["Equipment ID", "cycle_number"], how="left", validate="one_to_one",
    )
    scored["reallocatable_probability"] = final.predict_proba(
        scored[FEATURE_COLUMNS])[:, 1].round(4)
    scored["reallocatable_flag"] = (
        scored["reallocatable_probability"] >= REALLOC_THRESHOLD)
    scored.to_csv(OUTPUT_CSV, index=False)

    flagged = scored["reallocatable_flag"].mean()
    print(f"\nwrote {OUTPUT_CSV.relative_to(REPO_ROOT)}  ({len(scored)} rows)")
    print(f"flagged reallocatable : {int(scored['reallocatable_flag'].sum())} "
          f"({flagged:.1%})")
    by_type = (scored.groupby("Type")["reallocatable_flag"]
               .agg(["mean", "sum", "count"]).round(3))
    print("\nby Type:")
    print(by_type)
    last = scored[scored["is_last_cycle"]]
    print(f"\nlast-cycle rows (scored, not trained): {len(last)}  "
          f"flagged {last['reallocatable_flag'].mean():.1%}")


if __name__ == "__main__":
    main()
