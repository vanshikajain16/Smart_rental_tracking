"""Stage 5 - train the customer-reliability classifier and score every customer.

    python backend/stage5_customer_score/train_classifier.py

Flow
----
1. build the point-in-time panel (feature_builder.build_panel)
2. train rows = panel rows that have a full 5-rental future window (a real label)
3. RandomForest; evaluate with
     - a stratified hold-out  -> classification_report (headline)
     - GroupKFold(5) by customer -> the honest number (no customer spans folds,
       so a customer's overlapping cutoff rows can't leak between train/test)
4. TWO-SIDED quality gate:
     - "suspiciously perfect"  : hold-out acc >= 0.97 or AUC >= 0.98  -> leakage
     - "no real signal"        : grouped AUC < 0.58 or grouped acc <= majority
                                 baseline  -> the model is not usable
   If the model is not usable, the Reliability Score falls back to a transparent
   rule from the observed behaviour rates (documented below). The model + its
   metrics are still saved for the record.
5. score every customer (full-history snapshot) -> Reliability Score (0-100) and
   Risk Tier (Low/Medium/High), written into data/processed/customers.csv.
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
    FUTURE_WINDOW,
    INPUT_CSV,
    build_panel,
    customer_snapshot,
)

REPO_ROOT = HERE.parents[1]
CUSTOMERS_CSV = REPO_ROOT / "data" / "processed" / "customers.csv"
SCORES_CSV = REPO_ROOT / "data" / "processed" / "stage5_customer_scores.csv"
MODEL_PKL = HERE / "model.pkl"
MODEL_META = HERE / "model_meta.json"

RANDOM_STATE = 42
TEST_SIZE = 0.25

# quality-gate thresholds
LEAK_ACC, LEAK_AUC = 0.97, 0.98
MIN_USEFUL_AUC = 0.58

# model-path tier cutoffs on P(bad within next 5)
MODEL_TIER_HIGH = 0.35
MODEL_TIER_MED = 0.18
# rule-path tier cutoffs on reliability score
RULE_TIER_LOW_MIN = 75      # >= 75  -> Low risk
RULE_TIER_MED_MIN = 55      # 55..74 -> Medium ; < 55 -> High


def make_pipeline() -> Pipeline:
    return Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("rf", RandomForestClassifier(
            n_estimators=400, max_depth=5, min_samples_leaf=10,
            class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1)),
    ])


# --------------------------------------------------------------------------- #
# transparent fallback reliability score
# --------------------------------------------------------------------------- #
def rule_based_reliability(row: pd.Series) -> float:
    """100 minus demerits for observed bad behaviour. Fully interpretable;
    used when the trained model shows no real signal."""
    demerit = (
        250.0 * row["overdue_freq"]                       # career overdue share
        + 120.0 * row["recent_overdue_freq"]              # recent overdue share
        + 25.0 * row["unpaid_penalty_rate"]               # share of penalties unpaid
        + 40.0 * max(0.0, row["avg_idle_ratio"] - 0.65)   # chronic idling proxy
    )
    return float(np.clip(100.0 - demerit, 0.0, 100.0))


def tier_from_score(score: float) -> str:
    if score >= RULE_TIER_LOW_MIN:
        return "Low"
    if score >= RULE_TIER_MED_MIN:
        return "Medium"
    return "High"


def tier_from_pbad(p: float) -> str:
    if p >= MODEL_TIER_HIGH:
        return "High"
    if p >= MODEL_TIER_MED:
        return "Medium"
    return "Low"


# --------------------------------------------------------------------------- #
def main() -> None:
    panel = build_panel(pd.read_csv(INPUT_CSV))
    train = panel[panel["has_future_window"]].copy()
    train["label"] = train["label"].astype(int)

    X = train[FEATURE_COLUMNS]
    y = train["label"].to_numpy()
    groups = train["customer_id"].to_numpy()
    baseline = max(y.mean(), 1 - y.mean())

    print("=" * 78)
    print("STAGE 5 - customer reliability classifier")
    print("=" * 78)
    print(f"label rule     : any overdue / unpaid-penalty rental in the next "
          f"{FUTURE_WINDOW} rentals")
    print(f"trainable rows : {len(train)} over {train['customer_id'].nunique()} "
          f"customers   positives {y.mean():.3f}")
    print(f"features       : {FEATURE_COLUMNS}")

    # ---- hold-out ------------------------------------------------- #
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=TEST_SIZE, stratify=y, random_state=RANDOM_STATE)
    pipe = make_pipeline().fit(X_tr, y_tr)
    p_te = pipe.predict_proba(X_te)[:, 1]
    pred_te = (p_te >= 0.5).astype(int)
    acc = accuracy_score(y_te, pred_te)
    auc = roc_auc_score(y_te, p_te)

    print("\n" + "-" * 78)
    print(f"HELD-OUT TEST ({len(y_te)} rows)")
    print("-" * 78)
    print(classification_report(y_te, pred_te,
                                target_names=["reliable (0)", "at-risk (1)"],
                                digits=3, zero_division=0))
    print("confusion matrix [rows=true, cols=pred]:")
    print(confusion_matrix(y_te, pred_te))
    print(f"\naccuracy = {acc:.3f}   ROC-AUC = {auc:.3f}   "
          f"(majority baseline {baseline:.3f})")

    importances = (pd.Series(pipe.named_steps["rf"].feature_importances_,
                             index=FEATURE_COLUMNS).sort_values(ascending=False))
    print("\nfeature importances:")
    for n_, v in importances.items():
        print(f"  {n_:<22} {v:.3f}")

    # ---- grouped cross-check ------------------------------------ #
    oof = cross_val_predict(make_pipeline(), X, y, groups=groups,
                            cv=GroupKFold(5), method="predict_proba",
                            n_jobs=-1)[:, 1]
    oof_pred = (oof >= 0.5).astype(int)
    g_acc = accuracy_score(y, oof_pred)
    g_f1 = f1_score(y, oof_pred, average="macro")
    g_auc = roc_auc_score(y, oof)
    print("\n" + "-" * 78)
    print("GroupKFold(5) by Customer ID")
    print("-" * 78)
    print(f"accuracy = {g_acc:.3f}   macro-F1 = {g_f1:.3f}   ROC-AUC = {g_auc:.3f}"
          f"   (baseline {baseline:.3f})")

    # ---- quality gate ----------------------------------------- #
    too_perfect = acc >= LEAK_ACC or auc >= LEAK_AUC
    no_signal = (g_auc < MIN_USEFUL_AUC) or (g_acc <= baseline)
    if too_perfect:
        print("\n" + "!" * 78)
        print("SUSPICIOUSLY PERFECT - held-out acc/AUC implausibly high.")
        print("A future-window label should not be this predictable from past-")
        print("behaviour rates. Check for a feature that restates the label.")
        print("!" * 78)
        sys.exit(1)

    model_usable = not no_signal
    if no_signal:
        print("\n" + "*" * 78)
        print("NO REAL SIGNAL - grouped ROC-AUC {:.3f} < {:.2f} and/or grouped "
              "accuracy {:.3f} <= baseline {:.3f}.".format(
                  g_auc, MIN_USEFUL_AUC, g_acc, baseline))
        print("In this synthetic dataset overdue/penalty events are sprinkled")
        print("~randomly across customers with no persistent per-customer")
        print("propensity, so the classifier cannot beat guessing. Reliability")
        print("Score falls back to a transparent rule on observed behaviour.")
        print("Model + metrics are still saved for the record.")
        print("*" * 78)
    else:
        print(f"\nquality gate: PASS (grouped AUC {g_auc:.3f} >= {MIN_USEFUL_AUC}, "
              f"grouped acc {g_acc:.3f} > baseline {baseline:.3f}).")

    # ---- fit final model + save ------------------------------ #
    final = make_pipeline().fit(X, y)
    joblib.dump({"pipeline": final, "features": FEATURE_COLUMNS,
                 "model_usable": model_usable,
                 "future_window": FUTURE_WINDOW}, MODEL_PKL)

    # ---- score every customer ------------------------------- #
    snap = customer_snapshot(panel)
    p_bad_model = final.predict_proba(snap[FEATURE_COLUMNS])[:, 1]
    snap["p_bad_model"] = p_bad_model.round(4)
    snap["reliability_rule"] = snap.apply(rule_based_reliability, axis=1).round(1)

    if model_usable:
        snap["reliability_score"] = (100 * (1 - p_bad_model)).round().astype(int)
        snap["risk_tier"] = [tier_from_pbad(p) for p in p_bad_model]
        snap["score_method"] = "model"
    else:
        snap["reliability_score"] = snap["reliability_rule"].round().astype(int)
        snap["risk_tier"] = [tier_from_score(s) for s in snap["reliability_score"]]
        snap["score_method"] = "rule_fallback"

    # ---- write customers.csv (fill the null columns) -------- #
    # dtype=str so "+91..." phone numbers are not coerced to int (drops the '+').
    cust = pd.read_csv(CUSTOMERS_CSV, dtype=str)
    score_map = snap.set_index("customer_id")["reliability_score"].to_dict()
    tier_map = snap.set_index("customer_id")["risk_tier"].to_dict()
    cust["Reliability Score"] = cust["Customer ID"].map(score_map).astype("Int64")
    cust["Risk Tier"] = cust["Customer ID"].map(tier_map)
    cust.to_csv(CUSTOMERS_CSV, index=False)

    cols = ["customer_id", *FEATURE_COLUMNS, "p_bad_model",
            "reliability_rule", "reliability_score", "risk_tier", "score_method"]
    snap[cols].to_csv(SCORES_CSV, index=False)

    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "features": FEATURE_COLUMNS,
        "label_rule": f"any overdue/unpaid-penalty rental in next {FUTURE_WINDOW}",
        "n_trainable_rows": int(len(train)),
        "positive_rate": round(float(y.mean()), 4),
        "holdout": {"accuracy": round(acc, 4), "roc_auc": round(auc, 4)},
        "groupkfold": {"accuracy": round(g_acc, 4), "macro_f1": round(g_f1, 4),
                       "roc_auc": round(g_auc, 4)},
        "majority_baseline": round(float(baseline), 4),
        "model_usable": model_usable,
        "score_method": snap["score_method"].iloc[0],
        "feature_importances": {k: round(float(v), 4)
                                for k, v in importances.items()},
    }
    MODEL_META.write_text(json.dumps(meta, indent=2))

    print("\n" + "=" * 78)
    print(f"PER-CUSTOMER SCORES  (method: {snap['score_method'].iloc[0]})")
    print("=" * 78)
    show = snap[["customer_id", "n_rentals", "overdue_freq", "penalty_rate",
                 "unpaid_penalty_rate", "recent_overdue_freq", "p_bad_model",
                 "reliability_score", "risk_tier"]].copy()
    print(show.to_string(index=False))
    print("\nrisk tier counts:", snap["risk_tier"].value_counts().to_dict())
    print(f"\nwrote {CUSTOMERS_CSV.relative_to(REPO_ROOT)} "
          f"(Reliability Score + Risk Tier filled for {len(snap)} customers)")
    print(f"wrote {SCORES_CSV.relative_to(REPO_ROOT)}")
    print(f"saved {MODEL_PKL.relative_to(REPO_ROOT)} (+ model_meta.json)")


if __name__ == "__main__":
    main()
