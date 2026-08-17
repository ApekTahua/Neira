"""
trace_w8_slot_swaps.py -- Phase 1, task item 2: concretely trace which candidate
got admitted vs dropped, and why, for the specific already-documented cases where
a small, mechanically-unrelated change produced a large Window 8 (2025 H2) swing:

  (a) tick-size rounding fix (round_to_tick applied to compute_entry_fill's
      tp1_price/sl_price) -- docs/V3_FINDINGS_LOG.md, "tick-size bug found + fixed":
      W8 mean-alpha-dominant delta, "one ticker's entry date shifted by 9 calendar
      days between runs ... the only path is a different position's exit timing
      shifting by sub-tick amounts, freeing/blocking one of only 6 MAX_POSITIONS
      slots differently."
  (b) spike-confirm-delay gate at N=3/giveback=10% -- docs/V3_FINDINGS_LOG.md,
      "Spike confirmation-delay gate": W8 alpha +59.56% (OFF) -> +149.76% (ON),
      +90.20pp, 102% of the whole 9-window schedule's net delta.
  (c) REGIME_CONFIRM_DAYS=2 vs 3 at VOL_BAND_MULT=2.0 -- docs/V3_FINDINGS_LOG.md,
      "VOL_BAND_MULT re-swept": W8 alpha +59.56% (confirm=3) -> +106.65%
      (confirm=2), +47.1pp, more than the whole schedule's net gain.

For each pair, runs Window 8 ONLY (test 2025-07-01..2025-12-30, train<=2025-06-30)
under both configs with `diag` on, diffs the resulting trade list, and walks the
diag day-log from the first diverging trade backwards to find the first day where
the two runs' entry-queue consumption (admitted/dropped, break_reason) actually
differs -- i.e. the mechanical origin of the cascade, not just its downstream
symptom.

Purely additive/diagnostic: monkeypatches module globals on the already-imported
backtest_v4 (same pattern feature_test_harness.py/sweep_vol_band_mult.py already
use), restores them when done. Does not edit backtest_v4.py's own defaults.

Usage: SUPABASE_URL=... SUPABASE_KEY=... python src/trace_w8_slot_swaps.py
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V3_BANDAR_SIZING", "0")

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt

W8_TRAIN_END = date(2025, 6, 30)
W8_TEST_START = date(2025, 7, 1)
W8_TEST_END = date(2025, 12, 31)  # clipped to actual data inside simulate_window


def run_w8(df, idx_df, label):
    diag = {}
    metrics, df_trades, df_equity, _regime = bt.simulate_window(
        df, idx_df, W8_TRAIN_END, W8_TEST_START, W8_TEST_END, label=label, diag=diag)
    alpha = (metrics["total_return_pct"] - metrics["bench_ret"]) if metrics else float("nan")
    trades = df_trades[["stock_code", "entry_date", "exit_date", "exit_reason", "pnl_pct"]].copy() if df_trades is not None else pd.DataFrame()
    return alpha, trades, diag


def first_divergence(trades_a, trades_b):
    """First entry_date where the (stock_code, entry_date) sets of the two runs
    differ -- admits present in one run's trade list but not the other's."""
    set_a = set(zip(trades_a["stock_code"], trades_a["entry_date"])) if not trades_a.empty else set()
    set_b = set(zip(trades_b["stock_code"], trades_b["entry_date"])) if not trades_b.empty else set()
    only_a = sorted(set_a - set_b, key=lambda t: t[1])
    only_b = sorted(set_b - set_a, key=lambda t: t[1])
    first_date = min([d for _, d in only_a] + [d for _, d in only_b], default=None)
    return only_a, only_b, first_date


def diag_around(diag, center_date, window_days=3):
    days = diag.get("days", [])
    dates = sorted(d["date"] for d in days)
    if not dates:
        return []
    near = [d for d in days if abs((d["date"] - center_date).days) <= window_days]
    return sorted(near, key=lambda d: d["date"])


def print_diag_day(d, tag):
    adm = [(a["stock_code"], round(a["score"], 3)) for a in d["admitted"]]
    drop = [(s["stock_code"], round(s["score"], 3)) for s in d["dropped"]]
    print(f"  [{tag}] {d['date']} regime={d['regime']} pos_start={d['positions_start_count']} "
          f"pos_end={d['positions_end_count']} pending={d['pending_count']} break={d['break_reason']} "
          f"admitted={adm} dropped={drop}")


def report_pair(name, alpha_off, trades_off, diag_off, alpha_on, trades_on, diag_on):
    print("\n" + "=" * 100)
    print(f"PAIR: {name}")
    print("=" * 100)
    print(f"  W8 alpha OFF/baseline: {alpha_off:+.2f}%   ON/variant: {alpha_on:+.2f}%   delta: {alpha_on - alpha_off:+.2f}pp")
    only_off, only_on, first_date = first_divergence(trades_off, trades_on)
    print(f"  Trades only in OFF run ({len(only_off)}): {only_off[:10]}{' ...' if len(only_off) > 10 else ''}")
    print(f"  Trades only in ON run  ({len(only_on)}): {only_on[:10]}{' ...' if len(only_on) > 10 else ''}")
    if first_date is None:
        print("  No divergence in entry (stock_code, entry_date) pairs -- trade lists identical.")
        return
    print(f"\n  First diverging entry_date: {first_date} -- diag day-log both runs, +/-3 trading days:")
    print("  -- OFF/baseline --")
    for d in diag_around(diag_off, first_date):
        print_diag_day(d, "OFF")
    print("  -- ON/variant --")
    for d in diag_around(diag_on, first_date):
        print_diag_day(d, "ON ")


if __name__ == "__main__":
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    sb = None
    if url and key:
        from supabase import create_client
        sb = create_client(url, key)

    df, idx_df = wf.load_dataset(sb)

    # ---- Baseline (current defaults: tick rounding ON, spike gate OFF, confirm=3) ----
    print("Running baseline (current defaults) ...")
    alpha_base, trades_base, diag_base = run_w8(df, idx_df, "W8-baseline")

    # ---- (a) tick-size rounding: OFF = pre-fix behavior (identity, no rounding) ----
    print("\nRunning tick-size OFF (pre-fix, unrounded tp1/sl) ...")
    _orig_round = bt.round_to_tick
    bt.round_to_tick = lambda price, direction: price
    try:
        alpha_noround, trades_noround, diag_noround = run_w8(df, idx_df, "W8-no-round")
    finally:
        bt.round_to_tick = _orig_round
    report_pair("tick-size rounding (OFF=unrounded/pre-fix, ON=rounded/current default)",
                alpha_noround, trades_noround, diag_noround, alpha_base, trades_base, diag_base)

    # ---- (b) spike-confirm-gate N=3/giveback=10% ----
    print("\nRunning spike-confirm-gate N=3/giveback=10% ON ...")
    _orig_spike_enabled, _orig_giveback = bt.SPIKE_CONFIRM_GATE_ENABLED, bt.SPIKE_GIVEBACK_PCT
    bt.SPIKE_CONFIRM_GATE_ENABLED, bt.SPIKE_GIVEBACK_PCT = True, 0.10
    try:
        alpha_spike, trades_spike, diag_spike = run_w8(df, idx_df, "W8-spike-on")
    finally:
        bt.SPIKE_CONFIRM_GATE_ENABLED, bt.SPIKE_GIVEBACK_PCT = _orig_spike_enabled, _orig_giveback
    report_pair("spike_confirm_gate (OFF=baseline, ON=N=3/giveback=10%)",
                alpha_base, trades_base, diag_base, alpha_spike, trades_spike, diag_spike)

    # ---- (c) REGIME_CONFIRM_DAYS=2 vs 3 ----
    print("\nRunning REGIME_CONFIRM_DAYS=2 ...")
    _orig_confirm = bt.REGIME_CONFIRM_DAYS
    bt.REGIME_CONFIRM_DAYS = 2
    try:
        alpha_c2, trades_c2, diag_c2 = run_w8(df, idx_df, "W8-confirm2")
    finally:
        bt.REGIME_CONFIRM_DAYS = _orig_confirm
    report_pair("REGIME_CONFIRM_DAYS (OFF=3/default, ON=2)",
                alpha_base, trades_base, diag_base, alpha_c2, trades_c2, diag_c2)
