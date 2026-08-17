"""backfill_qualifying_signals.py -- one-off backfill of daily_qualifying_signals
for V4_PAPER's first three live trading days (2026-08-12..2026-08-14).

Context: the write path for this table was only wired into
src/paper_signal_scan.py in commit 43bd749 (shipped 2026-08-17), so it only
writes going forward from then -- the table was 100% empty despite V4_PAPER
trading live since 2026-08-12 (docs/MASTERPLAN.md), and daily_gate_summary
already has real rows for 2026-08-12/13/14 from those live runs. This
replays paper_signal_scan.py's own `scored` computation for those three
dates only, using its exact functions (no reimplemented scoring logic):
bt.build_full_dataset, bt.compute_regime_with_hysteresis, the same
train_liquid_bullish / weekly_cut / sector_cut / weekly_comp_abs_cap
threshold recompute, bt.score_candidates. Dates before 2026-08-12 are out of
scope -- V4_PAPER's filter configuration wasn't the live one before then.

Walk-forward discipline: df/idx_df are truncated to <= each trade_date
before any regime/threshold computation, so a date is scored using only
data that existed as of that date's own EOD close -- matching
paper_signal_scan.py's own expanding-window train mask (`trade_date <=
today`, inclusive of today's own cross-section: the scan runs AFTER that
day's EOD close, so today's own bar is real, already-known information,
not lookahead). compute_regime_with_hysteresis is a pure left-to-right
scan over trailing-only rolling stats, so truncating the input at the end
cannot change any date's computed regime/streak/trend_strength -- the same
reason paper_signal_scan.py itself is safe recomputing this fresh every
day over an ever-growing history.

Cross-checked per date against the real daily_gate_summary row already on
record (same deterministic pipeline -- must match). Stops before writing
anything for a date whose cross-check fails.

data/bandarmology_history is LOCAL-ONLY (gitignored, confirmed 0 files
tracked) and stops at 2026-08-11 -- one day short of the first backfill
date. GH Actions (the environment that actually produced these three
days' real daily_gate_summary rows) never has this directory at all, so
attach_bandarmology() there always takes its DB2-fallback branch. Left in
place here, bf.load_raw() would instead succeed (files exist for *other*
dates) and silently return NaN concentration for 2026-08-12+ via a
merge-miss -- a different code path than production actually ran, not
just a missing value. Renamed out of the way for the duration of this
script (restored in `finally`) so build_full_dataset takes the identical
DB2 branch production took.

Writes ONLY to daily_qualifying_signals (delete-then-upsert per
trade_date, same shape as paper_signal_scan.py's own write block). Never
touches paper_positions/paper_account/backtest_runs/backtest_equity --
display data only, no simulated trades, no live-run side effects.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/backfill_qualifying_signals.py
"""

import os
import sys
from datetime import date

os.environ.setdefault("V3_TEST_END", "2026-08-14")
# Matches V4_PAPER's own live workflow env exactly (.github/workflows/
# paper_signal_scan_v4_trigger.yml on main) -- doesn't affect score_candidates'
# output (BANDAR_SIZING_ENABLED only feeds compute_entry_fill's sizing, not
# the entry gate), set anyway so nothing about this run's config differs
# from what actually produced 2026-08-12/13/14 live.
os.environ.setdefault("V3_BANDAR_SIZING", "1")

import numpy as np  # noqa: E402

import backtest_v4 as bt  # noqa: E402
import bandarmology_features as bf  # noqa: E402
import config as cfg  # noqa: E402
from db_retry import retry as _retry  # noqa: E402
from supabase import create_client  # noqa: E402

BACKFILL_DATES = [date(2026, 8, 12), date(2026, 8, 13), date(2026, 8, 14)]


def score_one_day(df, idx_df, trade_date):
    """Exact replay of paper_signal_scan.py's threshold-recompute +
    score_candidates() call, against data truncated to <= trade_date."""
    df_t = df[df["trade_date"] <= trade_date]
    idx_t = idx_df[idx_df["trade_date"] <= trade_date]
    regime_by_date, bullish_streak_by_date, trend_strength_by_date = bt.compute_regime_with_hysteresis(idx_t)
    regime = regime_by_date.get(trade_date, "NEUTRAL")
    bullish_streak = bullish_streak_by_date.get(trade_date, 0)
    trend_strength = trend_strength_by_date.get(trade_date, 0.0)

    train_liquid_bullish = df_t[
        (df_t["adtv_20"] >= cfg.ADTV_MIN)
        & df_t["weekly_ma_spread"].notna() & df_t["sector_rs_momentum"].notna()
        & (df_t["trade_date"].map(regime_by_date).fillna("NEUTRAL") == "BULLISH")
        & (df_t["trade_date"].map(bullish_streak_by_date).fillna(0) >= bt.REGIME_CONFIRM_DAYS)
        & (df_t["trade_date"].map(trend_strength_by_date).fillna(0.0) >= bt.TREND_STRENGTH_MIN)
        & df_t["atr_14"].notna() & (df_t["atr_14"] > 0)
        & ((df_t["atr_14"] / df_t["close_price"]) <= bt.ATR_PRICE_RATIO_MAX)
    ]
    weekly_cut = train_liquid_bullish["weekly_ma_spread"].quantile(bt.QUANTILE_CUT)
    sector_cut = train_liquid_bullish["sector_rs_momentum"].quantile(bt.QUANTILE_CUT)
    weekly_comp_abs_cap = None
    if bt.SCORE_WEEKLY_COMP_ABS_CAP_Q is not None:
        train_w_comp = (train_liquid_bullish["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
        if len(train_w_comp) > 0:
            weekly_comp_abs_cap = train_w_comp.quantile(bt.SCORE_WEEKLY_COMP_ABS_CAP_Q)

    train_scores = (
        (train_liquid_bullish["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
        + (train_liquid_bullish["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
    )
    score_p90 = train_scores.quantile(0.90) if len(train_scores) > 0 else 1.0
    if not np.isfinite(score_p90) or score_p90 <= 0:
        score_p90 = 1.0

    regime_ok = (regime == "BULLISH" and bullish_streak >= bt.REGIME_CONFIRM_DAYS
                 and trend_strength >= bt.TREND_STRENGTH_MIN)

    scored = []
    if regime_ok:
        day_data = df_t[df_t["trade_date"] == trade_date]
        scored = bt.score_candidates(day_data, weekly_cut, sector_cut, top_n=15,
                                      weekly_comp_abs_cap=weekly_comp_abs_cap)

    gate = {
        "regime": regime, "bullish_streak": int(bullish_streak), "regime_ok": bool(regime_ok),
        "trend_strength": float(trend_strength), "weekly_cut": float(weekly_cut),
        "sector_cut": float(sector_cut), "score_p90": float(score_p90),
    }
    return scored, gate


def cross_check(supabase, trade_date, gate):
    """Compares the recomputed gate against daily_gate_summary's already-live
    row for trade_date. Returns None on a clean match, else a description of
    the mismatch."""
    live_res = _retry(lambda: supabase.table("daily_gate_summary").select("*")
                       .eq("trade_date", trade_date.isoformat()).limit(1).execute())
    if not live_res.data:
        return f"no daily_gate_summary row exists for {trade_date} (expected one from the live run)"
    live = live_res.data[0]
    mismatches = []
    for field, tol in [("regime", None), ("bullish_streak", None), ("regime_ok", None),
                        ("trend_strength", 1e-6), ("weekly_cut", 1e-6),
                        ("sector_cut", 1e-6), ("score_p90", 1e-6)]:
        live_v, computed_v = live[field], gate[field]
        mismatch = (live_v != computed_v) if tol is None else (abs(float(live_v) - float(computed_v)) > tol)
        if mismatch:
            mismatches.append(f"{field}: live={live_v!r} computed={computed_v!r}")
    return "; ".join(mismatches) if mismatches else None


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    # Force attach_bandarmology()'s DB2-fallback branch -- see module
    # docstring. Only ever touches this local-only, gitignored directory.
    disabled_path = str(bf.DATA_DIR) + "_disabled_for_backfill"
    moved = False
    if bf.DATA_DIR.exists():
        if os.path.exists(disabled_path):
            sys.exit(f"{disabled_path} already exists (leftover from an interrupted prior run) -- "
                      f"resolve manually before rerunning.")
        os.rename(bf.DATA_DIR, disabled_path)
        moved = True
    try:
        print(f"[FETCH] building full dataset through {os.environ['V3_TEST_END']} "
              f"(same call paper_signal_scan.py makes) ...")
        df, idx_df = bt.build_full_dataset(supabase)
    finally:
        if moved:
            os.rename(disabled_path, bf.DATA_DIR)

    for trade_date in BACKFILL_DATES:
        scored, gate = score_one_day(df, idx_df, trade_date)
        print(f"\n[{trade_date}] regime={gate['regime']} streak={gate['bullish_streak']} "
              f"regime_ok={gate['regime_ok']} trend_strength={gate['trend_strength']:.4f} "
              f"weekly_cut={gate['weekly_cut']:.4f} sector_cut={gate['sector_cut']:.4f} "
              f"score_p90={gate['score_p90']:.4f} -- {len(scored)} qualifying candidate(s)")

        mismatch = cross_check(supabase, trade_date, gate)
        if mismatch:
            sys.exit(f"[MISMATCH] {trade_date}: {mismatch}\n"
                     f"Stopping before any writes -- see module docstring.")
        print(f"[CROSS-CHECK OK] {trade_date} matches daily_gate_summary")

        rows = [{
            "trade_date": trade_date.isoformat(), "stock_code": sig["stock_code"], "rank": i + 1,
            "score": sig["score"], "trigger": sig["trigger"], "adtv_20": sig["adtv_20"],
            "avg_vol_20": sig["avg_vol_20"], "atr": sig["atr"], "signal_close": sig["signal_close"],
            "tp_target": sig["tp_target"], "concentration": sig.get("concentration"),
        } for i, sig in enumerate(scored)]
        try:
            _retry(lambda: supabase.table("daily_qualifying_signals").delete()
                   .eq("trade_date", trade_date.isoformat()).execute())
            if rows:
                _retry(lambda: supabase.table("daily_qualifying_signals").upsert(
                    rows, on_conflict="trade_date,stock_code").execute())
            print(f"[WRITE OK] {trade_date}: {len(rows)} row(s)")
        except Exception as e:
            print(f"[WRITE FAILED] {trade_date}: {e}\nRow payload that would have been written:")
            for r in rows:
                print(f"  {r}")


if __name__ == "__main__":
    main()
