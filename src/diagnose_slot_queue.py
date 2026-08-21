"""
diagnose_slot_queue.py -- Phase 1 diagnostic for the pending_entries queue-reset
mechanism (see backtest_v4.py's simulate_window main day loop, ~line 1822):
pending_entries is a ONE-DAY-AHEAD queue, rebuilt fresh every day from that day's
score_candidates() output. At the top of the NEXT day, positions are filled in
score-rank order until either MAX_POSITIONS or MAX_NEW_ENTRIES_PER_DAY is hit, at
which point the loop `break`s and every remaining ranked candidate for that day is
DROPPED ENTIRELY -- not deferred, not retried tomorrow (the list resets to [] a few
lines later regardless of whether it was exhausted).

Why this diagnostic exists: three independent research passes this session (the
tick-size-rounding fix, the spike-confirm-delay gate, and the VOL_BAND_MULT
re-sweep -- see docs/V3_FINDINGS_LOG.md, most recent first) each found a small,
mechanically-unrelated change producing a large, misleading-looking swing
concentrated almost entirely in Window 8 (2025 H2), traced each time to a
DIFFERENT position's exit timing shifting slightly, freeing (or not freeing) one
of only MAX_POSITIONS=6 slots at a different moment. This script measures how
often/how badly that scarce-slot mechanism actually bites, instead of continuing
to infer it sideways through unrelated parameter research.

Purely additive: uses simulate_window's new `diag` kwarg (default None, no effect
on any existing caller -- see that function's docstring) to record, per candidate-
day, why the entry-queue consumption loop stopped early and which ranked
candidates were admitted vs dropped. Does not change any trading decision.

Usage: SUPABASE_URL=... SUPABASE_KEY=... python src/diagnose_slot_queue.py
(no creds needed if .cache/walk_forward_data_*.pkl already exists, matching
walk_forward_v4.load_dataset's own fetch-once/cache-reuse rule.)
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V4_BANDAR_SIZING", "0")  # matches the reproducible baseline this log has used since the tick-size-bug entry

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt


def run_with_diag(df, idx_df, schedule):
    """Runs each window in `schedule` once, with a fresh diag dict per window.
    Returns a list of dicts: {window, test_start, test_end, metrics, diag, total_days}."""
    out = []
    for i, (tr_end, te_start, te_end) in enumerate(schedule, 1):
        print(f"\n{'-'*100}\nWindow {i}/{len(schedule)} (diag on)\n{'-'*100}")
        diag = {}
        metrics, df_trades, df_equity, _regime = bt.simulate_window(
            df, idx_df, tr_end, te_start, te_end, label=f"W{i}", diag=diag)
        out.append({
            "window": i, "test_start": te_start, "test_end": te_end,
            "metrics": metrics, "diag": diag,
            "total_days": len(df_equity) if df_equity is not None else 0,
        })
    return out


def summarize_window(w):
    """One row of aggregate stats for a window's diag output, plus the raw
    dropped-candidate list (date, stock_code, score) per break reason for
    the trade-level trace."""
    days = w["diag"].get("days", [])
    candidate_days = len(days)
    by_reason = {}
    admitted_scores = []
    dropped_scores = {"max_positions": [], "daily_cap": [], "cluster_cap": []}
    dropped_stocks = {"max_positions": [], "daily_cap": [], "cluster_cap": []}
    for d in days:
        r = d["break_reason"]
        by_reason[r] = by_reason.get(r, 0) + 1
        admitted_scores.extend(a["score"] for a in d["admitted"])
        if r in dropped_scores:
            for s in d["dropped"]:
                dropped_scores[r].append(s["score"])
                dropped_stocks[r].append((d["date"], s["stock_code"], s["score"]))

    def ms(vals):
        s = pd.Series(vals, dtype=float)
        return (s.mean(), s.median()) if len(s) else (float("nan"), float("nan"))

    adm_mean, adm_median = ms(admitted_scores)
    mp_mean, mp_median = ms(dropped_scores["max_positions"])
    dc_mean, dc_median = ms(dropped_scores["daily_cap"])
    row = {
        "window": w["window"], "test_start": w["test_start"], "test_end": w["test_end"],
        "total_trading_days": w["total_days"], "candidate_days": candidate_days,
        "days_break_max_positions": by_reason.get("max_positions", 0),
        "days_break_daily_cap": by_reason.get("daily_cap", 0),
        "days_break_cluster_cap": by_reason.get("cluster_cap", 0),
        "days_no_break": by_reason.get(None, 0),
        "n_admitted": len(admitted_scores),
        "n_dropped_max_positions": len(dropped_scores["max_positions"]),
        "n_dropped_daily_cap": len(dropped_scores["daily_cap"]),
        "admitted_score_mean": adm_mean, "admitted_score_median": adm_median,
        "dropped_mp_score_mean": mp_mean, "dropped_mp_score_median": mp_median,
        "dropped_dc_score_mean": dc_mean, "dropped_dc_score_median": dc_median,
        "alpha_pct": (w["metrics"]["total_return_pct"] - w["metrics"]["bench_ret"]) if w["metrics"] else float("nan"),
    }
    return row, dropped_stocks


if __name__ == "__main__":
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    sb = None
    if url and key:
        from supabase import create_client
        sb = create_client(url, key)

    df, idx_df = wf.load_dataset(sb)
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    results = run_with_diag(df, idx_df, schedule)

    rows = []
    all_dropped = {}
    for w in results:
        row, dropped_stocks = summarize_window(w)
        rows.append(row)
        all_dropped[w["window"]] = dropped_stocks

    res_df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("\n" + "=" * 100)
    print("SLOT-QUEUE DIAGNOSTIC -- one row per window")
    print("=" * 100)
    print(res_df.to_string(index=False))

    res_df.to_csv("D:/Neira/Neira/.claude/worktrees/v2-hmm-screener/.cache/slot_queue_diag_summary.csv", index=False)

    # Full dropped-candidate detail (date, stock, score) for the max_positions
    # reason specifically -- the one the task asks to trace concretely.
    import json
    detail_path = "D:/Neira/Neira/.claude/worktrees/v2-hmm-screener/.cache/slot_queue_diag_dropped_max_positions.csv"
    detail_rows = []
    for wnum, dropped in all_dropped.items():
        for dt, code, score in dropped["max_positions"]:
            detail_rows.append({"window": wnum, "date": dt, "stock_code": code, "score": score})
    pd.DataFrame(detail_rows).to_csv(detail_path, index=False)
    print(f"\n[OK] Saved {detail_path} ({len(detail_rows)} dropped-due-to-full-slots rows)")
    print("[OK] Saved .cache/slot_queue_diag_summary.csv")
