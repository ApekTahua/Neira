"""
phase0e_ml_combined_model.py — combine the Phase 0 survivors (weekly-trend
alignment, sector RRG relative strength, foreign flow, regime) plus the raw
technical metrics into one gradient-boosted ranking model, walk-forward
validated. None of Phase 0/0b/0c/0d's features showed enough standalone
edge to trade alone, but two of them (sector RRG, weekly trend) are
strongly regime-conditional in OPPOSITE directions — exactly the kind of
interaction a hand-coded AND-gate can't express but a tree model can.

Population: ALL bars for liquid stocks (ADTV>=1B), NOT pre-filtered by the
squeeze trigger — Phase 0 showed that gate carries no edge, so pre-
filtering on a dead gate would hide whatever the model could find on its
own initiative. The squeeze metrics are still passed in as raw continuous
features; if they're truly useless the model just won't split on them.

Label: net_ret_20 = 20-trading-day forward return minus round-trip fees
(BUY_FEE + SELL_FEE from config) — "would this actually make money after
realistic cost", not raw return. hit = net_ret_20 > 0.

Validation: expanding-window walk-forward, 3 chronological folds, with a
30-calendar-day embargo between train end and test start so the 20-day
forward-return label never leaks test-period price data into training.

Model: sklearn HistGradientBoostingClassifier (tree ensemble, handles
missing values and interactions natively) vs LogisticRegression baseline
side by side — the complexity only earns its keep if HGB beats logistic
by a real margin.

Every fold reports win rate / mean / median of the TOP-QUINTILE-by-score
picks vs the full liquid baseline, PLUS the top-5-ticker concentration
check that caught V1/V2b's fake edge. A result is only trusted if it
clears both.

Read-only, no Supabase writes, no portfolio simulation — still Phase 0
discipline, just multivariate instead of univariate.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/phase0e_ml_combined_model.py
"""

import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
from supabase import create_client
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

import config as cfg
import data_fetch
from strategy import add_features
from phase0_signal_validation import attach_forward_returns
from phase0b_foreign_flow_validation import attach_regime, attach_trailing_return
from phase0c_rrg_validation import fetch_sector_indices, fetch_sector_map, compute_rs_momentum
from phase0d_multitimeframe_validation import attach_weekly_trend

START = date.fromisoformat(os.environ.get("PHASE0_START", "2021-01-01"))
END = date.fromisoformat(os.environ.get("PHASE0_END", "2026-06-30"))
LABEL_HORIZON = 20
EMBARGO_DAYS = 30
ROUND_TRIP_COST = cfg.BUY_FEE + cfg.SELL_FEE

FEATURE_COLS = [
    "ma_spread", "bb_bandwidth", "vol_ratio", "daily_return",
    "rsi", "adx", "foreign_net_ma", "sector_rs_momentum",
    "weekly_ma_spread", "adtv_20", "is_bullish", "is_bearish",
]

FOLDS = [
    # (train_start, train_end, test_start, test_end)
    (date(2021, 1, 1), date(2023, 6, 30), date(2023, 7, 31), date(2024, 6, 30)),
    (date(2021, 1, 1), date(2024, 6, 30), date(2024, 7, 31), date(2025, 6, 30)),
    (date(2021, 1, 1), date(2025, 6, 30), date(2025, 7, 31), date(2026, 6, 30)),
]


def build_dataset(supabase) -> pd.DataFrame:
    print("[FETCH] Downloading stock + index data ...")
    df, idx_df = data_fetch.fetch_data(supabase, START, END)

    print("[FETCH] Downloading sector indices + stock->sector map ...")
    sector_wide = fetch_sector_indices(supabase, START, END)
    sector_map = fetch_sector_map(supabase)

    print("[FEATURE] Computing indicators ...")
    frames = [add_features(df[df["stock_code"] == sc].copy()) for sc in df["stock_code"].unique()]
    df = pd.concat(frames, ignore_index=True)

    print("[FEATURE] Sector RS-momentum + weekly trend ...")
    rs_long = compute_rs_momentum(sector_wide)
    df["index_code"] = df["stock_code"].map(sector_map)
    df = df.merge(rs_long, on=["trade_date", "index_code"], how="left")
    df = attach_weekly_trend(df)

    print("[FEATURE] Squeeze continuous metrics ...")
    ma_spread = (
        df[["ma10", "ma20", "ma50"]].max(axis=1) - df[["ma10", "ma20", "ma50"]].min(axis=1)
    ) / df["ma50"] * 100
    df["ma_spread"] = ma_spread
    df["vol_ratio"] = (df["volume"] / df["avg_vol_20_prev"]).replace([np.inf, -np.inf], np.nan)

    print("[FORWARD] Computing forward/trailing returns, regime ...")
    df = attach_forward_returns(df)
    df = attach_trailing_return(df, 5)
    df = attach_regime(df, idx_df)
    df["is_bullish"] = (df["regime"] == "BULLISH").astype(int)
    df["is_bearish"] = (df["regime"] == "BEARISH").astype(int)

    required = ["avg_vol_20", "fwd_ret_20"] + [c for c in FEATURE_COLS if c not in ("is_bullish", "is_bearish")]
    clean = df.dropna(subset=required).copy()
    sleeping = (
        (clean["close_price"] <= cfg.SLEEPING_PRICE)
        & (clean["rolling_min_close"] == cfg.SLEEPING_PRICE)
        & (clean["rolling_max_close"] == cfg.SLEEPING_PRICE)
    )
    illiquid = clean["avg_vol_20"] < cfg.MIN_LIQUIDITY_VOL
    clean = clean[~(sleeping | illiquid)]
    clean = clean[clean["adtv_20"] >= cfg.ADTV_MIN].copy()

    clean["net_ret_20"] = clean["fwd_ret_20"] - ROUND_TRIP_COST
    clean["hit"] = (clean["net_ret_20"] > 0).astype(int)
    return clean


def concentration_check(picks: pd.DataFrame) -> str:
    """% of total positive net_ret_20 (equal-weighted, one unit per pick)
    coming from the top-5 tickers by contribution — the same check that
    caught V1/V2b faking a distributed edge."""
    contrib = picks.groupby("stock_code")["net_ret_20"].sum().sort_values(ascending=False)
    total = contrib[contrib > 0].sum()
    if total <= 0:
        return "n/a (no net positive contribution)"
    top5 = contrib.head(5).clip(lower=0).sum()
    names = ", ".join(contrib.head(5).index.tolist())
    return f"top-5 tickers ({names}) = {100 * top5 / total:.1f}% of total positive contribution"


def evaluate_fold(train: pd.DataFrame, test: pd.DataFrame, fold_label: str):
    X_train, y_train = train[FEATURE_COLS], train["hit"]
    X_test, y_test = test[FEATURE_COLS], test["hit"]

    hgb = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=200, random_state=42)
    hgb.fit(X_train, y_train)

    logit = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    logit.fit(X_train.fillna(X_train.median()), y_train)

    print(f"\n{'=' * 110}\nFOLD {fold_label} — train {train['trade_date'].min()}..{train['trade_date'].max()} "
          f"({len(train)} rows) -> test {test['trade_date'].min()}..{test['trade_date'].max()} ({len(test)} rows)\n{'=' * 110}")

    for name, model, X_te in [("HistGradientBoosting", hgb, X_test), ("LogisticRegression", logit, X_test.fillna(X_test.median()))]:
        proba = model.predict_proba(X_te)[:, 1]
        auc = roc_auc_score(y_test, proba)
        scored = test.copy()
        scored["score"] = proba
        scored["quintile"] = pd.qcut(scored["score"], 5, labels=["Q1(low)", "Q2", "Q3", "Q4", "Q5(high)"], duplicates="drop")

        print(f"\n--- {name} (test AUC={auc:.3f}) ---")
        rows = []
        for q, g in scored.groupby("quintile", observed=True):
            rows.append({
                "quintile": q, "n": len(g),
                "win_rate": round((g["net_ret_20"] > 0).mean() * 100, 1),
                "mean_net_ret_20": round(g["net_ret_20"].mean() * 100, 2),
                "median_net_ret_20": round(g["net_ret_20"].median() * 100, 2),
            })
        print(pd.DataFrame(rows).to_string(index=False))

        baseline_win = round((test["net_ret_20"] > 0).mean() * 100, 1)
        baseline_mean = round(test["net_ret_20"].mean() * 100, 2)
        print(f"Full liquid baseline (no model): win_rate={baseline_win}%, mean_net_ret_20={baseline_mean}%")

        top_q = scored[scored["quintile"] == "Q5(high)"]
        print(f"Q5 concentration check: {concentration_check(top_q)}")


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 110)
    print("PHASE 0e — Combined gradient-boosted ranking model, walk-forward validated")
    print(f"Window: {START} .. {END} | label horizon {LABEL_HORIZON}d net of {ROUND_TRIP_COST*100:.2f}% round-trip cost")
    print("=" * 110)

    data = build_dataset(supabase)
    print(f"\n[POPULATION] {len(data)} liquid-tier bars, {data['stock_code'].nunique()} stocks, "
          f"base hit rate {data['hit'].mean()*100:.1f}%")

    last_fold_test = None
    last_fold_model = None
    for i, (tr_start, tr_end, te_start, te_end) in enumerate(FOLDS, 1):
        train = data[(data["trade_date"] >= tr_start) & (data["trade_date"] <= tr_end)]
        test = data[(data["trade_date"] >= te_start) & (data["trade_date"] <= te_end)]
        if train.empty or test.empty:
            print(f"[SKIP] Fold {i}: insufficient data.")
            continue
        evaluate_fold(train, test, str(i))
        if i == len(FOLDS):
            last_fold_test = test
            hgb = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=200, random_state=42)
            hgb.fit(train[FEATURE_COLS], train["hit"])
            last_fold_model = hgb

    if last_fold_model is not None:
        print(f"\n{'=' * 110}\nFEATURE IMPORTANCE (permutation, held-out final fold) — sanity check against gorengan re-discovery\n{'=' * 110}")
        r = permutation_importance(last_fold_model, last_fold_test[FEATURE_COLS], last_fold_test["hit"], n_repeats=5, random_state=42, scoring="roc_auc")
        imp = pd.DataFrame({"feature": FEATURE_COLS, "importance_mean": r.importances_mean, "importance_std": r.importances_std}).sort_values("importance_mean", ascending=False)
        print(imp.to_string(index=False))


if __name__ == "__main__":
    main()
