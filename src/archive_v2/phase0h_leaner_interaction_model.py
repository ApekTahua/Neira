"""
phase0h_leaner_interaction_model.py — redo of Phase 0e addressing its two
suspicious symptoms: (1) AUC ~0.50 in 2 of 3 folds, (2) the two features
with real standalone edge (weekly_ma_spread, sector_rs_momentum) got
NEGATIVE permutation importance in the combined model. Two candidate
causes, both testable: the 8-feature kitchen sink (including foreign
flow, squeeze metrics, daily_return -- all shown to carry ~zero standalone
edge in Phase 0/0b) drowns the two real signals in noise dimensionality;
and/or a depth-4 tree with 200 boosting rounds isn't finding the
BULLISH x weekly_trend / BULLISH x sector_RRG interaction on its own from
raw regime dummies + raw features.

This version: (a) prunes to the features that showed ANY standalone edge
plus RSI/ADX/ADTV (cheap, plausible, cost nothing to include), (b) adds
the regime interaction terms EXPLICITLY (weekly_ma_spread*is_bullish,
sector_rs_momentum*is_bullish) instead of hoping the tree finds them, and
(c) tests THREE separate label horizons (5/10/20d) instead of committing
to 20d only -- weekly_ma_spread's forward correlation did not decay
across horizons in Phase 0d, so a shorter, less noise-accumulated window
may validate better than 20d did in Phase 0e.

Same walk-forward folds, same concentration-check discipline as Phase 0e.

Read-only, no Supabase writes, no portfolio simulation.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/phase0h_leaner_interaction_model.py
"""

import os
import sys

import pandas as pd
from supabase import create_client
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

from phase0e_ml_combined_model import build_dataset, FOLDS, ROUND_TRIP_COST, concentration_check

FEATURE_COLS = [
    "weekly_ma_spread", "sector_rs_momentum", "is_bullish", "is_bearish",
    "rsi", "adx", "adtv_20", "weekly_x_bull", "sector_x_bull",
]
HORIZONS = (5, 10, 20)


def add_interactions(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    data["weekly_x_bull"] = data["weekly_ma_spread"] * data["is_bullish"]
    data["sector_x_bull"] = data["sector_rs_momentum"] * data["is_bullish"]
    return data


def evaluate_horizon(data: pd.DataFrame, horizon: int):
    ret_col = f"fwd_ret_{horizon}"
    d = data.dropna(subset=[ret_col]).copy()
    d["net_ret"] = d[ret_col] - ROUND_TRIP_COST
    d["hit"] = (d["net_ret"] > 0).astype(int)

    print(f"\n{'#' * 110}\nHORIZON = {horizon} DAYS (base hit rate {d['hit'].mean()*100:.1f}%, n={len(d)})\n{'#' * 110}")

    last_test, last_model = None, None
    for i, (tr_start, tr_end, te_start, te_end) in enumerate(FOLDS, 1):
        train = d[(d["trade_date"] >= tr_start) & (d["trade_date"] <= tr_end)]
        test = d[(d["trade_date"] >= te_start) & (d["trade_date"] <= te_end)]
        if train.empty or test.empty:
            continue

        hgb = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, random_state=42)
        hgb.fit(train[FEATURE_COLS], train["hit"])
        proba = hgb.predict_proba(test[FEATURE_COLS])[:, 1]
        auc = roc_auc_score(test["hit"], proba)

        scored = test.copy()
        scored["score"] = proba
        scored["quintile"] = pd.qcut(scored["score"], 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5(high)"], duplicates="drop")

        print(f"\n--- Fold {i}: train {train['trade_date'].min()}..{train['trade_date'].max()} ({len(train)}) "
              f"-> test {test['trade_date'].min()}..{test['trade_date'].max()} ({len(test)}) | AUC={auc:.3f} ---")
        rows = []
        for q, g in scored.groupby("quintile", observed=True):
            rows.append({"quintile": q, "n": len(g), "win_rate": round((g["net_ret"] > 0).mean() * 100, 1),
                         "mean_net_ret": round(g["net_ret"].mean() * 100, 2), "median_net_ret": round(g["net_ret"].median() * 100, 2)})
        print(pd.DataFrame(rows).to_string(index=False))
        print(f"Baseline (no model): win_rate={round((test['net_ret']>0).mean()*100,1)}%, mean_net_ret={round(test['net_ret'].mean()*100,2)}%")
        top_q = scored[scored["quintile"] == "Q5(high)"]
        print(f"Q5 concentration: {concentration_check(top_q.assign(net_ret_20=top_q['net_ret']))}")

        if i == len(FOLDS):
            last_test, last_model = test, hgb

    if last_model is not None:
        r = permutation_importance(last_model, last_test[FEATURE_COLS], last_test["hit"], n_repeats=8, random_state=42, scoring="roc_auc")
        imp = pd.DataFrame({"feature": FEATURE_COLS, "importance_mean": r.importances_mean}).sort_values("importance_mean", ascending=False)
        print(f"\nPermutation importance (held-out final fold, horizon={horizon}d):")
        print(imp.to_string(index=False))


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 110)
    print("PHASE 0h — Leaner interaction-explicit model, multiple horizons (fixing Phase 0e's noise-drowning)")
    print("=" * 110)

    data = build_dataset(supabase)
    data = add_interactions(data)
    print(f"[POPULATION] {len(data)} liquid-tier bars, {data['stock_code'].nunique()} stocks.")

    for h in HORIZONS:
        evaluate_horizon(data, h)


if __name__ == "__main__":
    main()
