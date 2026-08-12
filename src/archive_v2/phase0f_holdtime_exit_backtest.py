"""
phase0f_holdtime_exit_backtest.py — does an ATR-based adaptive hold-time
checkpoint beat a fixed 20-day hold, on the SAME entries?

Motivated by two live signals (REAL, HDIT, 2026-07-22) that scored high
confidence despite being dead-flat for two months: distance-to-TP was
smaller than the stock's own daily noise, and ATR was near zero. A real
trader sizes how long to wait for a setup to how fast the stock actually
moves; the current system holds every position to a fixed calendar wall
(MAX_HOLD_DAYS=20) regardless.

expected_hold_days = |TP - entry_price| / ATR_14, clipped to
[MIN_CHECKPOINT_DAYS, CHECKPOINT_CAP_DAYS]. Large expected_hold_days
(TP far relative to how fast the stock moves) is exactly the REAL/HDIT
signature — this metric should independently flag those cases.

Two policies simulated on the IDENTICAL entries (squeeze-trigger bars,
liquid tier, same TP/SL the live system already computes via
strategy.add_features -- tp_target = SMC swing-high target, sl_target =
atr_sl = close - 1.5*ATR):
  FIXED:      hold to TP/SL/MAX_HOLD_DAYS(20), whichever first.
  CHECKPOINT: same, but at day=min(expected_hold_days, CHECKPOINT_CAP_DAYS)
              exit early if price hasn't covered PROGRESS_THRESHOLD of the
              distance to TP yet ("thesis not confirming").

This is a single-variable test of the EXIT mechanism, independent of
whether squeeze itself is a good entry (Phase 0 already showed it isn't
on its own) -- whatever wins here applies to any future entry signal too.

Read-only, no Supabase writes.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/phase0f_holdtime_exit_backtest.py
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
from phase0_signal_validation import find_triggers

START = date.fromisoformat(os.environ.get("PHASE0_START", "2021-01-01"))
END = date.fromisoformat(os.environ.get("PHASE0_END", "2026-06-30"))

MAX_HOLD_DAYS = cfg.MAX_HOLD_DAYS  # 20
FORWARD_BUFFER = 25                # simulate a few extra days past MAX_HOLD for safety
MIN_CHECKPOINT_DAYS = 3
CHECKPOINT_CAP_DAYS = 15           # must stay < MAX_HOLD_DAYS to be a genuine early check
PROGRESS_THRESHOLD = 0.40          # must have covered >=40% of the distance to TP by checkpoint
ROUND_TRIP_COST = cfg.BUY_FEE + cfg.SELL_FEE


def simulate_trade(bars: np.ndarray, entry_price: float, tp: float, sl: float,
                    expected_hold_days: float) -> dict:
    """bars: array of (open, close, high, low) for the trading days AFTER entry,
    in order. Returns fixed-hold and checkpoint-hold outcomes for one trade."""
    checkpoint_day = int(np.clip(round(expected_hold_days), MIN_CHECKPOINT_DAYS, CHECKPOINT_CAP_DAYS))
    dist_to_tp = tp - entry_price

    fixed_exit_day, fixed_exit_price, fixed_reason = None, None, None
    chk_exit_day, chk_exit_price, chk_reason = None, None, None

    n = min(len(bars), MAX_HOLD_DAYS)
    for d in range(1, n + 1):
        _, c, h, l = bars[d - 1]
        if fixed_exit_day is None:
            if l <= sl:
                fixed_exit_day, fixed_exit_price, fixed_reason = d, sl, "SL"
            elif h >= tp:
                fixed_exit_day, fixed_exit_price, fixed_reason = d, tp, "TP"
            elif d == n:
                fixed_exit_day, fixed_exit_price, fixed_reason = d, c, "TIME"

        if chk_exit_day is None:
            if l <= sl:
                chk_exit_day, chk_exit_price, chk_reason = d, sl, "SL"
            elif h >= tp:
                chk_exit_day, chk_exit_price, chk_reason = d, tp, "TP"
            elif d == checkpoint_day and dist_to_tp > 0:
                progress = (c - entry_price) / dist_to_tp
                if progress < PROGRESS_THRESHOLD:
                    chk_exit_day, chk_exit_price, chk_reason = d, c, "CHECKPOINT"
            elif d == n:
                chk_exit_day, chk_exit_price, chk_reason = d, c, "TIME"

        if fixed_exit_day is not None and chk_exit_day is not None:
            break

    if fixed_exit_day is None:
        fixed_exit_day, fixed_exit_price, fixed_reason = n, bars[n - 1][1], "TIME"
    if chk_exit_day is None:
        chk_exit_day, chk_exit_price, chk_reason = n, bars[n - 1][1], "TIME"

    return {
        "expected_hold_days": expected_hold_days,
        "checkpoint_day": checkpoint_day,
        "fixed_hold_days": fixed_exit_day, "fixed_ret_pct": (fixed_exit_price / entry_price - 1) * 100 - ROUND_TRIP_COST * 100, "fixed_reason": fixed_reason,
        "chk_hold_days": chk_exit_day, "chk_ret_pct": (chk_exit_price / entry_price - 1) * 100 - ROUND_TRIP_COST * 100, "chk_reason": chk_reason,
    }


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    print("=" * 110)
    print("PHASE 0f — Adaptive hold-time checkpoint exit vs fixed 20-day hold")
    print(f"Window: {START} .. {END}")
    print("=" * 110)

    print("[FETCH] Downloading data ...")
    df, idx_df = data_fetch.fetch_data(supabase, START, END)

    print("[FEATURE] Computing indicators (TP/SL/ATR already live-system logic) ...")
    frames = [add_features(df[df["stock_code"] == sc].copy()) for sc in df["stock_code"].unique()]
    df = pd.concat(frames, ignore_index=True).sort_values(["stock_code", "trade_date"]).reset_index(drop=True)

    print("[TRIGGER] Isolating squeeze triggers, liquid tier ...")
    triggers = find_triggers(df)
    triggers["liquidity_tier"] = np.where(triggers["adtv_20"] >= cfg.ADTV_MIN, "liquid", "microcap")
    triggers = triggers[triggers["liquidity_tier"] == "liquid"].copy()
    triggers = triggers.dropna(subset=["atr_14", "tp_target", "atr_sl"])
    triggers = triggers[triggers["atr_14"] > 0]
    print(f"[TRIGGER] {len(triggers)} liquid-tier squeeze triggers with valid ATR/TP/SL.")

    triggers["expected_hold_days"] = (triggers["tp_target"] - triggers["close_price"]).abs() / triggers["atr_14"]

    print("[SIM] Building per-stock forward OHLC index ...")
    bar_index = {}
    for sc, g in df.groupby("stock_code"):
        bar_index[sc] = (g["trade_date"].to_numpy(), g[["open_price", "close_price", "high", "low"]].to_numpy())

    print("[SIM] Simulating fixed-hold vs checkpoint-hold on each trigger ...")
    results = []
    for row in triggers.itertuples():
        dates, bars = bar_index[row.stock_code]
        idx = np.searchsorted(dates, row.trade_date)
        if idx + 1 >= len(dates):
            continue
        forward_bars = bars[idx + 1: idx + 1 + FORWARD_BUFFER]
        if len(forward_bars) == 0:
            continue
        sim = simulate_trade(forward_bars, row.close_price, row.tp_target, row.atr_sl, row.expected_hold_days)
        sim["stock_code"] = row.stock_code
        sim["trade_date"] = row.trade_date
        results.append(sim)

    res = pd.DataFrame(results)
    print(f"[SIM] {len(res)} trades simulated.")

    print("\n" + "=" * 110)
    print("EXPECTED-HOLD-DAYS DISTRIBUTION (uncapped, raw) — how many triggers look like REAL/HDIT?")
    print("=" * 110)
    raw_expected = triggers["expected_hold_days"]
    print(f"  median={raw_expected.median():.1f}d  p75={raw_expected.quantile(.75):.1f}d  "
          f"p90={raw_expected.quantile(.90):.1f}d  max={raw_expected.max():.1f}d  "
          f"n(>15d, i.e. capped)={  (raw_expected > CHECKPOINT_CAP_DAYS).sum()} / {len(raw_expected)} "
          f"({100*(raw_expected > CHECKPOINT_CAP_DAYS).mean():.1f}%)")

    print("\n" + "=" * 110)
    print("FIXED (20-day hold) vs CHECKPOINT (adaptive early exit) — same entries, same TP/SL")
    print("=" * 110)
    for label, ret_col, hold_col, reason_col in [("FIXED", "fixed_ret_pct", "fixed_hold_days", "fixed_reason"), ("CHECKPOINT", "chk_ret_pct", "chk_hold_days", "chk_reason")]:
        r = res[ret_col]
        print(f"\n--- {label} ---")
        print(f"  n={len(r)}  win_rate={round((r>0).mean()*100,1)}%  mean_ret={round(r.mean(),2)}%  "
              f"median_ret={round(r.median(),2)}%  avg_hold_days={round(res[hold_col].mean(),1)}")
        print(f"  exit reasons: {res[reason_col].value_counts(normalize=True).round(3).to_dict()}")

    print("\n" + "=" * 110)
    print("BUCKETED BY expected_hold_days (raw, uncapped) — does high expected_hold_days predict worse FIXED-hold outcomes?")
    print("=" * 110)
    res["hold_bucket"] = pd.cut(res["expected_hold_days"], bins=[0, 5, 10, 15, np.inf], labels=["<5d", "5-10d", "10-15d", ">15d(REAL/HDIT-like)"])
    bucket_stats = res.groupby("hold_bucket", observed=True).agg(
        n=("fixed_ret_pct", "size"),
        fixed_win_rate=("fixed_ret_pct", lambda x: round((x > 0).mean() * 100, 1)),
        fixed_mean_ret=("fixed_ret_pct", lambda x: round(x.mean(), 2)),
        fixed_median_ret=("fixed_ret_pct", lambda x: round(x.median(), 2)),
        chk_win_rate=("chk_ret_pct", lambda x: round((x > 0).mean() * 100, 1)),
        chk_mean_ret=("chk_ret_pct", lambda x: round(x.mean(), 2)),
        chk_median_ret=("chk_ret_pct", lambda x: round(x.median(), 2)),
    )
    print(bucket_stats.to_string())

    res.to_csv("phase0f_holdtime_trades.csv", index=False)
    print(f"\n[OK] Trade-level results saved to phase0f_holdtime_trades.csv ({len(res)} rows).")


if __name__ == "__main__":
    main()
