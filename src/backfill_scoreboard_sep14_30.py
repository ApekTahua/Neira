"""backfill_scoreboard_sep14_30.py -- one-off backfill of daily_scoreboard +
re-verification of daily_gate_summary for 2026-09-14..2026-09-30, the window
F-023's n8n index_eod outage silently defaulted every day to regime=NEUTRAL/
regime_ok=False (see audit/FINDINGS.md F-023/F-024, docs/HOLDOUT_PROTOCOL.md
Rule 5).

Context: index_eod itself has since been backfilled for all 13 dates (see
audit/FINDINGS.md), so paper_signal_scan.py's own compute_regime_with_hysteresis
can now compute the REAL regime for this window instead of the NEUTRAL default
it silently fell back to during the live outage. That means the daily_gate_summary
rows already on record for these 13 dates may themselves be WRONG (not just
daily_scoreboard being empty) -- this script recomputes both honestly and reports
whether they actually match before anything gets written.

Deliberately does NOT need Neira/.env: unlike backfill_qualifying_signals.py
(which this is modeled on), every Supabase table this script reads has an
`anon` SELECT RLS policy (ihsg_eod, index_eod, stock_profiles -- confirmed via
pg_policies), the SAME access level the public frontend already uses. The
local bandarmology Parquet archive doesn't exist on this machine either
(confirmed, Test-Path false) -- so attach_bandarmology()/attach_mover_signal()/
attach_accdist_signal() all take their documented graceful-degrade path
(DB2 fallback or NaN), which is the IDENTICAL path GitHub Actions takes in
production (that environment never has the local Parquet directory either --
see attach_bandarmology's own docstring). This is not a workaround; it is
production's real code path.

Writes NOTHING to Supabase. Outputs a JSON report (gate recompute + mismatch
vs the live daily_gate_summary row, plus the full scoreboard for each date)
to the path given on the command line, for a human (or a separate, explicitly
authorized write step) to review before any table is touched.

Usage:
    python src/backfill_scoreboard_sep14_30.py <output.json>
"""

import json
import os
import sys
from datetime import date

os.environ.setdefault("V4_BANDAR_SIZING", "1")
os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")
# Matches V4_PAPER's own live workflow env exactly (.github/workflows/
# paper_signal_scan_v4_trigger.yml, checked out on worktree-v2-hmm-screener) --
# BANDAR_SIZING only feeds compute_entry_fill's sizing (not scoring/gating
# here), ATR_PRICE_RATIO_MAX DOES feed score_full_universe's liquidity filter,
# so it must match V4_PAPER's real value, not backtest_v4.py's own 0.10 default.
os.environ.setdefault("V4_TEST_END", date(2026, 9, 30).isoformat())

import numpy as np  # noqa: E402
from supabase import create_client  # noqa: E402
from supabase.lib.client_options import SyncClientOptions  # noqa: E402

import data_fetch  # noqa: E402
# The `anon` Postgres role (what this script uses -- see ANON_KEY below) has
# a 3-second statement_timeout (confirmed via `select current_setting(
# 'statement_timeout')` run as anon: 3s, vs authenticated=8s, service_role=
# unlimited -- a deliberate public-read guardrail, not a bug). data_fetch.
# fetch_data()'s own FETCH_CONCURRENCY=12 was tuned against the service_role
# key's 2-minute budget production actually runs under; under anon's 3s cap
# and 12-way concurrency, a 50-stock/1-month chunk measured consistently
# landing at 2.5-3.3s wall time (benchmarked directly against this project
# before writing this script) -- right at or over the timeout, which is
# exactly the 57014 "canceling statement due to statement timeout" crash the
# first version of this script hit repeatedly. Lowered here to 4 (same
# benchmark: 4 workers against the same chunk shape landed at 0.2-0.9s,
# comfortable headroom under 3s) -- this is the only change; fetch_data()'s
# own code/batch_size is edited temporarily and reverted immediately after
# this run (see the diff this commit does NOT include -- not shipped to any
# branch, anon-tuning has no reason to persist in production code that
# normally runs under service_role).
data_fetch.FETCH_CONCURRENCY = 4

import backtest_v4 as bt  # noqa: E402
import config as cfg  # noqa: E402
from db_retry import retry as _retry  # noqa: E402

# Public anon key for DB1 (soddgoonjnfclabrijtn) -- same key the frontend
# ships to browsers (NEXT_PUBLIC_SUPABASE_ANON_KEY), read-only via RLS.
# Not a secret: this is the exact value `mcp_supabase_1_get_publishable_keys`
# returned, itself designed to be public.
ANON_URL = "https://soddgoonjnfclabrijtn.supabase.co"
ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNvZGRnb29uam5mY2xhYnJpanRuIiwi"
    "cm9sZSI6ImFub24iLCJpYXQiOjE3NzkwMjI3NzksImV4cCI6MjA5NDU5ODc3OX0.5Sxn0uY8TCOdFbcOPF8vxUIgezBrD-bejKuKplDF9uo"
)

BACKFILL_DATES = [
    date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17),
    date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23),
    date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29),
    date(2026, 9, 30),
]
# Known-good anchor: the last date before the outage, already has a correct
# live daily_gate_summary/daily_scoreboard row (regime=BULLISH confirmed
# earlier this session). Recomputed here too and cross-checked -- if THIS
# date doesn't match, the recompute methodology itself is wrong and nothing
# past it can be trusted either.
ANCHOR_DATE = date(2026, 9, 11)


def recompute_gate_and_scoreboard(df, idx_df, trade_date):
    """Exact replay of paper_signal_scan.py's threshold-recompute +
    score_full_universe() call, against data truncated to <= trade_date
    (walk-forward: a date is scored using only data that existed as of
    that date's own EOD close -- same reasoning backfill_qualifying_signals.py
    documents for compute_regime_with_hysteresis's pure left-to-right scan)."""
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

    train_scores = (
        (train_liquid_bullish["weekly_ma_spread"] - weekly_cut) / max(abs(weekly_cut), 1e-6)
        + (train_liquid_bullish["sector_rs_momentum"] - sector_cut) / max(abs(sector_cut), 1e-6)
    )
    score_p90 = train_scores.quantile(0.90) if len(train_scores) > 0 else 1.0
    if not np.isfinite(score_p90) or score_p90 <= 0:
        score_p90 = 1.0

    regime_ok = (regime == "BULLISH" and bullish_streak >= bt.REGIME_CONFIRM_DAYS
                 and trend_strength >= bt.TREND_STRENGTH_MIN)

    day_data = df_t[df_t["trade_date"] == trade_date]
    scoreboard = bt.score_full_universe(day_data, weekly_cut, sector_cut, score_p90, regime_ok)

    scored = []
    if regime_ok:
        scored = bt.score_candidates(day_data, weekly_cut, sector_cut, top_n=15)

    gate = {
        "regime": regime, "bullish_streak": int(bullish_streak), "regime_ok": bool(regime_ok),
        "trend_strength": float(trend_strength), "weekly_cut": float(weekly_cut),
        "sector_cut": float(sector_cut), "score_p90": float(score_p90),
        "atr_ratio_max": float(bt.ATR_PRICE_RATIO_MAX), "adtv_min": float(cfg.ADTV_MIN),
    }
    return gate, scoreboard, scored


def cross_check(supabase, trade_date, gate):
    live_res = _retry(lambda: supabase.table("daily_gate_summary").select("*")
                       .eq("trade_date", trade_date.isoformat()).limit(1).execute())
    if not live_res.data:
        return {"status": "no_live_row", "detail": f"no daily_gate_summary row exists for {trade_date}"}
    live = live_res.data[0]
    mismatches = []
    for field, tol in [("regime", None), ("bullish_streak", None), ("regime_ok", None),
                        ("trend_strength", 1e-6), ("weekly_cut", 1e-6),
                        ("sector_cut", 1e-6), ("score_p90", 1e-6)]:
        live_v, computed_v = live[field], gate[field]
        mismatch = (live_v != computed_v) if tol is None else (abs(float(live_v) - float(computed_v)) > tol)
        if mismatch:
            mismatches.append({"field": field, "live": live_v, "computed": computed_v})
    if mismatches:
        return {"status": "mismatch", "detail": mismatches}
    return {"status": "match"}


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python src/backfill_scoreboard_sep14_30.py <output.json>")
    out_path = sys.argv[1]

    # Default postgrest_client_timeout is 120s -- combined with data_fetch.py's
    # 12-way concurrent ThreadPoolExecutor and db_retry.retry()'s 4 attempts,
    # a handful of slow/throttled requests against the anon key (likely a
    # tighter rate limit than the service-role key production normally uses)
    # can leave every worker blocked in socket recv() for minutes before the
    # existing retry/backoff logic even gets a chance to run. Shortened here
    # so a slow call fails fast and retry() (already production-proven, see
    # db_retry.py's own docstring) gets more cycles to actually succeed --
    # this changes nothing about what data gets fetched, only how quickly a
    # stalled attempt gives up and retries.
    supabase = create_client(ANON_URL, ANON_KEY, options=SyncClientOptions(postgrest_client_timeout=20))

    print(f"[FETCH] building full dataset through {os.environ['V4_TEST_END']} "
          f"(same call paper_signal_scan.py makes, anon key, read-only) ...")
    df, idx_df = bt.build_full_dataset(supabase)

    report = {"anchor_check": None, "dates": {}}

    print(f"\n[ANCHOR CHECK] {ANCHOR_DATE} (known-good, pre-outage) ...")
    anchor_gate, anchor_scoreboard, _ = recompute_gate_and_scoreboard(df, idx_df, ANCHOR_DATE)
    anchor_check = cross_check(supabase, ANCHOR_DATE, anchor_gate)
    report["anchor_check"] = {"gate": anchor_gate, "scoreboard_count": len(anchor_scoreboard),
                               "cross_check": anchor_check}
    print(f"  regime={anchor_gate['regime']} regime_ok={anchor_gate['regime_ok']} "
          f"scoreboard={len(anchor_scoreboard)} tickers -- cross_check={anchor_check['status']}")
    if anchor_check["status"] != "match":
        print(f"  [WARNING] anchor date does not match live daily_gate_summary -- "
              f"methodology may not reproduce production exactly:\n  {anchor_check['detail']}")

    for trade_date in BACKFILL_DATES:
        gate, scoreboard, scored = recompute_gate_and_scoreboard(df, idx_df, trade_date)
        check = cross_check(supabase, trade_date, gate)
        print(f"\n[{trade_date}] regime={gate['regime']} streak={gate['bullish_streak']} "
              f"regime_ok={gate['regime_ok']} trend_strength={gate['trend_strength']:.4f} "
              f"-- scoreboard={len(scoreboard)} tickers, qualifying={len(scored)} "
              f"-- live_row={check['status']}")
        if check["status"] == "mismatch":
            print(f"  [DIFFERS FROM LIVE] {check['detail']}")
        report["dates"][trade_date.isoformat()] = {
            "gate": gate, "scoreboard": scoreboard, "qualifying_signals": scored,
            "cross_check_vs_live_daily_gate_summary": check,
        }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n[DONE] wrote report to {out_path} -- no Supabase writes performed.")


if __name__ == "__main__":
    main()
