"""
phase0d_multitimeframe_validation.py — does weekly-trend alignment predict
forward return, independent of the daily squeeze pattern?

Weekly trend proxy: resample each stock's daily close to weekly (W-FRI)
bars, compute a 10-week MA, and measure
  weekly_ma_spread(t) = (weekly_close - weekly_ma10) / weekly_ma10 * 100
mapped back onto daily rows via the last COMPLETED weekly bar (merge_asof
backward, grouped by stock) — no lookahead into an in-progress week.
Positive spread = price above its own 10-week trend ("weekly uptrend").

Same two questions, same discipline as Phase 0b/0c:
  1. STANDALONE: liquid stocks, ALL bars — quintile weekly_ma_spread.
  2. WITHIN-TRIGGER: same, restricted to squeeze-trigger bars — does
     requiring weekly trend alignment improve the daily signal?

Read-only, no Supabase writes, no portfolio simulation.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/phase0d_multitimeframe_validation.py
"""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd
from supabase import create_client

import config as cfg
import data_fetch
from strategy import add_features
from phase0_signal_validation import HORIZONS, attach_forward_returns, find_triggers
from phase0b_foreign_flow_validation import attach_regime, attach_trailing_return, quintile_summary, spearman_report, print_table

START = date.fromisoformat(os.environ.get("PHASE0_START", "2021-01-01"))
END = date.fromisoformat(os.environ.get("PHASE0_END", "2026-06-30"))
WEEKLY_MA_PERIODS = 10


def attach_weekly_trend(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["stock_code", "trade_date"]).copy()
    df["_dt"] = pd.to_datetime(df["trade_date"])

    weekly_frames = []
    for sc, g in df.groupby("stock_code"):
        s = g.set_index("_dt")["close_price"]
        weekly = s.resample("W-FRI").last().dropna()
        weekly_ma = weekly.rolling(WEEKLY_MA_PERIODS, min_periods=WEEKLY_MA_PERIODS).mean()
        spread = (weekly - weekly_ma) / weekly_ma * 100
        wk = spread.dropna().reset_index()
        wk.columns = ["_dt", "weekly_ma_spread"]
        wk["stock_code"] = sc
        weekly_frames.append(wk)
    weekly_all = pd.concat(weekly_frames, ignore_index=True) if weekly_frames else pd.DataFrame(columns=["_dt", "weekly_ma_spread", "stock_code"])

    df = df.sort_values("_dt")
    weekly_all = weekly_all.sort_values("_dt")
    df = pd.merge_asof(df, weekly_all, on="_dt", by="stock_code", direction="backward")
    return df.drop(columns=["_dt"])


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 110)
    print("PHASE 0d — Multi-timeframe (weekly trend alignment): standalone predictive power")
    print(f"Window: {START} .. {END}")
    print("=" * 110)

    print("[FETCH] Downloading data ...")
    df, idx_df = data_fetch.fetch_data(supabase, START, END)

    print("[FEATURE] Computing indicators ...")
    frames = [add_features(df[df["stock_code"] == sc].copy()) for sc in df["stock_code"].unique()]
    df = pd.concat(frames, ignore_index=True)

    print("[WEEKLY] Resampling to weekly trend (10-week MA spread) ...")
    df = attach_weekly_trend(df)

    print("[FORWARD] Computing forward + trailing returns, regime ...")
    df = attach_forward_returns(df)
    df = attach_trailing_return(df, 5)
    df = attach_regime(df, idx_df)

    required = ["avg_vol_20", "weekly_ma_spread"]
    clean = df.dropna(subset=required).copy()
    sleeping = (
        (clean["close_price"] <= cfg.SLEEPING_PRICE)
        & (clean["rolling_min_close"] == cfg.SLEEPING_PRICE)
        & (clean["rolling_max_close"] == cfg.SLEEPING_PRICE)
    )
    illiquid = clean["avg_vol_20"] < cfg.MIN_LIQUIDITY_VOL
    clean = clean[~(sleeping | illiquid)]
    clean["liquidity_tier"] = np.where(clean["adtv_20"] >= cfg.ADTV_MIN, "liquid(>=1B)", "microcap(<1B)")

    liquid = clean[clean["liquidity_tier"] == "liquid(>=1B)"]
    print(f"[POPULATION] {len(clean)} clean bars, {len(liquid)} liquid-tier.")

    print_table("Q1a — LIQUID STOCKS, ALL BARS: weekly_ma_spread quintile -> forward return", quintile_summary(liquid, "weekly_ma_spread", []))
    print_table("Q1b — LIQUID STOCKS, ALL BARS, BY REGIME: weekly_ma_spread quintile -> forward return", quintile_summary(liquid, "weekly_ma_spread", ["regime"]))
    print_table("Q1c — Spearman correlation: weekly_ma_spread vs forward return (liquid, by regime) + vs trailing 5d return (lag/lead check)", spearman_report(liquid, "weekly_ma_spread", ["regime"]))

    triggers = find_triggers(df)
    triggers = triggers.merge(
        clean[["stock_code", "trade_date", "liquidity_tier"]],
        on=["stock_code", "trade_date"], how="inner",
    )
    triggers_liquid = triggers[triggers["liquidity_tier"] == "liquid(>=1B)"]
    print(f"\n[POPULATION] {len(triggers)} squeeze-trigger bars, {len(triggers_liquid)} of those liquid-tier.")
    print_table("Q2 — WITHIN SQUEEZE TRIGGERS, LIQUID STOCKS: weekly_ma_spread quintile -> forward return", quintile_summary(triggers_liquid, "weekly_ma_spread", []))


if __name__ == "__main__":
    main()
