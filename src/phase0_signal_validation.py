"""
phase0_signal_validation.py — V3 Phase 0: isolate and test the CORE SIGNAL
(MA squeeze + BB squeeze + volume spike) before any architecture.

Pure statistics, no portfolio simulation, no position sizing, no exits,
no slot/cash competition. Every historical bar where the three squeeze/
spike conditions from strategy.get_signals() fire (same thresholds
already live in config.py) is a "trigger", independent of whether a
backtest would have had capital free to take it. For each trigger we
measure forward return at +5/+10/+20 trading days, split by:
  - liquidity tier: ADTV >= cfg.ADTV_MIN ("liquid") vs below ("microcap")
  - macro regime (IHSG vs its own MA50, via strategy.get_regime)

This deliberately skips the mandatory Lorentzian filters (RSI/ADX/SMA200/
foreign flow), the sideways/flat-price condition, HMM gating, and ADTV
gating that get_signals() also applies — those are wrapper hypotheses to
test separately in later phases. Here we want the rawest possible read
on whether "squeeze + volume spike" alone predicts anything.

Read-only: no Supabase writes. New, isolated file — does not touch
strategy.py/backtest.py/screener.py or any *_v2*.py file.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/phase0_signal_validation.py
"""

import os
import sys
from datetime import date

import numpy as np
import pandas as pd
from supabase import create_client

import config as cfg
import data_fetch
from strategy import add_features, get_regime

START = date.fromisoformat(os.environ.get("PHASE0_START", "2021-01-01"))
END = date.fromisoformat(os.environ.get("PHASE0_END", "2026-06-30"))
HORIZONS = (5, 10, 20)
HIT_THRESHOLD = 0.05  # nominal +5% target for "hit rate" distinct from raw win rate
OUT_CSV = os.environ.get("PHASE0_OUT_CSV", "phase0_triggers.csv")


def find_triggers(df: pd.DataFrame) -> pd.DataFrame:
    """Every bar where MA squeeze + BB squeeze + volume spike all fire,
    after only the same data-hygiene red flags get_signals() applies
    (dead/sleeping tickers, near-zero raw volume) — no other gate."""
    required = ["ma10", "ma20", "ma50", "std20", "avg_vol_20", "avg_vol_20_prev"]
    clean = df.dropna(subset=required).copy()

    sleeping = (
        (clean["close_price"] <= cfg.SLEEPING_PRICE)
        & (clean["rolling_min_close"] == cfg.SLEEPING_PRICE)
        & (clean["rolling_max_close"] == cfg.SLEEPING_PRICE)
    )
    illiquid = clean["avg_vol_20"] < cfg.MIN_LIQUIDITY_VOL
    clean = clean[~(sleeping | illiquid)]

    ma_spread = (
        clean[["ma10", "ma20", "ma50"]].max(axis=1)
        - clean[["ma10", "ma20", "ma50"]].min(axis=1)
    ) / clean["ma50"] * 100
    cond_ma = ma_spread < cfg.MA_SQUEEZE_THRESHOLD
    cond_bb = clean["bb_bandwidth"] < cfg.BB_SQUEEZE_THRESHOLD
    cond_vol = (clean["volume"] / clean["avg_vol_20_prev"]) > cfg.VOL_SPIKE_MULT

    return clean[cond_ma & cond_bb & cond_vol].copy()


def attach_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    g = df.groupby("stock_code")["close_price"]
    for h in HORIZONS:
        df[f"fwd_ret_{h}"] = g.shift(-h) / df["close_price"] - 1
    return df


def summarize(triggers: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows = []
    groups = triggers.groupby(group_cols) if group_cols else [((), triggers)]
    for key, sub in groups:
        key = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_cols, key))
        row["n_triggers"] = len(sub)
        for h in HORIZONS:
            r = sub[f"fwd_ret_{h}"].dropna()
            if r.empty:
                continue
            row[f"n_{h}d"] = len(r)
            row[f"win_rate_{h}d"] = round((r > 0).mean() * 100, 1)
            row[f"hit_rate5pct_{h}d"] = round((r >= HIT_THRESHOLD).mean() * 100, 1)
            row[f"mean_ret_{h}d"] = round(r.mean() * 100, 2)
            row[f"median_ret_{h}d"] = round(r.median() * 100, 2)
        rows.append(row)
    return pd.DataFrame(rows)


def print_table(title: str, table: pd.DataFrame):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    if table.empty:
        print("(no triggers)")
        return
    print(table.to_string(index=False))


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 100)
    print("PHASE 0 — Core signal validation (MA squeeze + BB squeeze + volume spike)")
    print(f"Window: {START} .. {END}")
    print("No portfolio simulation. No position sizing. No exits. Raw forward returns only.")
    print("=" * 100)

    print("[FETCH] Downloading data ...")
    df, idx_df = data_fetch.fetch_data(supabase, START, END)

    print("[FEATURE] Computing indicators ...")
    frames = [add_features(df[df["stock_code"] == sc].copy()) for sc in df["stock_code"].unique()]
    df = pd.concat(frames, ignore_index=True)

    print("[FORWARD] Computing +5/+10/+20-day forward returns ...")
    df = attach_forward_returns(df)

    print("[TRIGGER] Isolating core-signal triggers ...")
    triggers = find_triggers(df)
    if triggers.empty:
        sys.exit("No triggers found in this window — nothing to validate.")

    triggers["liquidity_tier"] = np.where(
        triggers["adtv_20"] >= cfg.ADTV_MIN, "liquid(>=1B)", "microcap(<1B)"
    )
    triggers["regime"] = [get_regime(idx_df, d) for d in triggers["trade_date"]]

    print(f"[TRIGGER] {len(triggers)} raw trigger bars across {triggers['stock_code'].nunique()} stocks.")

    print_table("OVERALL (no split)", summarize(triggers, []))
    print_table("BY LIQUIDITY TIER", summarize(triggers, ["liquidity_tier"]))
    print_table("BY REGIME", summarize(triggers, ["regime"]))
    print_table("BY LIQUIDITY TIER x REGIME", summarize(triggers, ["liquidity_tier", "regime"]))

    keep_cols = [
        "stock_code", "trade_date", "close_price", "adtv_20", "liquidity_tier", "regime",
        *[f"fwd_ret_{h}" for h in HORIZONS],
    ]
    triggers[keep_cols].to_csv(OUT_CSV, index=False)
    print(f"\n[OK] Raw trigger-level data saved to {OUT_CSV} ({len(triggers)} rows) for further slicing.")


if __name__ == "__main__":
    main()
