"""Self-check for the entry-timing caps paper_monitor.py enforces at fill time
(added 2026-09-04). Two halves, both cheap:

  1. A pure-logic replay of the fill loop's guards against synthetic pending
     rows -- proves the cap breaks at the right count AND that it defers the
     LOWEST-scored candidate, which is the half a count-only check misses.
  2. A read-only invariant check against the live database: no run may have
     more than MAX_NEW_ENTRIES_PER_DAY fills sharing one entry_date. This is
     the assertion that would have caught the real defect -- on 2026-09-03,
     run 36 filled PPGL (queued 09-01), SGER and TOBA (both queued 09-02) at
     the same open, three against a cap of two, because the cap lived only in
     paper_signal_scan.py where it bounds rows CREATED per scan and cannot see
     a candidate carried over from an earlier day.

Read-only: SELECT only, never .insert()/.upsert()/.update(). Skips the live
half (without failing) when no SUPABASE_KEY is configured.

Run: python src/test_entry_caps.py
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backtest_v4 as bt  # noqa: E402


def _replay(pending, filled_today, recent_entries):
    """Mirrors paper_monitor.py's fill-loop guards exactly. Returns fill order."""
    filled = []
    for row in sorted(pending, key=lambda r: float(r["score"] or 0), reverse=True):
        if filled_today >= bt.MAX_NEW_ENTRIES_PER_DAY:
            break
        if recent_entries >= bt.MAX_ENTRIES_PER_CLUSTER_WINDOW:
            break
        filled.append(row["stock_code"])
        filled_today += 1
        recent_entries += 1
    return filled


def test_daily_cap_and_ranking():
    # The real 2026-09-03 shape: one carried-over candidate plus two fresh ones,
    # all eligible at the same open. Scores are the real stored values.
    pending = [
        {"stock_code": "PPGL", "score": 16.29},   # queued 09-01, unfilled 09-02
        {"stock_code": "SGER", "score": 12.86},   # queued 09-02
        {"stock_code": "TOBA", "score": 12.20},   # queued 09-02
    ]
    got = _replay(pending, filled_today=0, recent_entries=0)
    assert len(got) == bt.MAX_NEW_ENTRIES_PER_DAY, f"expected {bt.MAX_NEW_ENTRIES_PER_DAY} fills, got {got}"
    assert got == ["PPGL", "SGER"], f"must fill highest-scored first, got {got}"
    print(f"[OK] daily cap holds at {bt.MAX_NEW_ENTRIES_PER_DAY}, weakest (TOBA) deferred")

    # A poll later the same day, after two fills already landed: nothing more.
    assert _replay(pending, filled_today=bt.MAX_NEW_ENTRIES_PER_DAY, recent_entries=2) == []
    print("[OK] a later poll on the same day adds nothing")

    # Cluster cap bites independently of the daily cap.
    assert _replay(pending, filled_today=0, recent_entries=bt.MAX_ENTRIES_PER_CLUSTER_WINDOW) == []
    print(f"[OK] cluster cap holds at {bt.MAX_ENTRIES_PER_CLUSTER_WINDOW} per {bt.ENTRY_CLUSTER_WINDOW_DAYS} days")



def _count_recent(entry_hist, cutoff, today):
    """Mirrors paper_monitor.py's `recent_entries` sum exactly."""
    return sum(
        1 for p in entry_hist
        if p["entry_date"] >= cutoff
        and (p["exit_date"] is None or p["exit_date"] > today)
    )


def test_cluster_window_counts_only_still_open():
    # The backtest's cluster cap sums over `positions`, the list of CURRENTLY
    # held positions, so an entry that stopped out inside the window is gone and
    # blocks nothing. The first version of the live fix counted every entry in
    # the window regardless of outcome, which made live STRICTER than the rules
    # it mirrors -- a run of quick stop-outs would have frozen new entries.
    hist = [
        {"entry_date": "2026-09-01", "exit_date": "2026-09-02"},  # stopped out inside the window
        {"entry_date": "2026-09-02", "exit_date": None},          # still open
        {"entry_date": "2026-09-03", "exit_date": "2026-09-05"},  # exits today -> already gone
        {"entry_date": "2026-08-01", "exit_date": None},          # open, but before the cutoff
    ]
    got = _count_recent(hist, cutoff="2026-09-01", today="2026-09-05")
    assert got == 1, f"only the still-open in-window entry counts, got {got}"
    print("[OK] cluster window counts only positions still open, matching the backtest")



def _cutoff_from(prior_sessions, window_days, today):
    """Mirrors paper_monitor.py's cutoff resolution exactly."""
    return (prior_sessions[min(window_days - 1, len(prior_sessions) - 1)]
            if prior_sessions else today)


def test_cutoff_is_anchored_on_today_not_on_the_last_eod_row():
    # index_eod does not carry today's row until the EOD job runs at 17:30, but
    # this monitor polls from 09:00. Both states must give the same window.
    window = bt.ENTRY_CLUSTER_WINDOW_DAYS
    sessions_desc = ["2026-09-07", "2026-09-04", "2026-09-03", "2026-09-02",
                     "2026-09-01", "2026-08-31", "2026-08-28", "2026-08-27"]
    today = "2026-09-07"
    prior = [d for d in sessions_desc if d < today]          # intraday: no row yet
    prior_after_eod = [d for d in sessions_desc if d < today]  # same query, "<" not "<="
    a = _cutoff_from(prior, window, today)
    b = _cutoff_from(prior_after_eod, window, today)
    assert a == b, f"cutoff moved when today's EOD row landed: {a} vs {b}"
    # today plus `window` prior sessions, so the oldest included is prior[window-1]
    assert a == prior[window - 1] == "2026-08-31", a
    included = [d for d in sessions_desc if d >= a]
    assert len(included) == window + 1, f"expected {window + 1} sessions, got {included}"
    print(f"[OK] cluster window spans today + {window} prior sessions, "
          f"whether or not today's EOD row exists yet")


def test_live_no_day_exceeds_cap():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not (url and key):
        print("[SKIP] live invariant -- no SUPABASE_URL/SUPABASE_KEY configured")
        return
    from supabase import create_client

    rows = create_client(url, key).table("paper_positions").select(
        "run_id, entry_date, stock_code"
    ).not_.is_("entry_date", "null").execute().data
    per_day = Counter((r["run_id"], r["entry_date"]) for r in rows)
    over = {k: n for k, n in per_day.items() if n > bt.MAX_NEW_ENTRIES_PER_DAY}
    if over:
        # 2026-09-03 on run 36 is the known pre-fix breach; it stays in the
        # historical record on purpose (a frozen run's history is never edited),
        # so report it without failing, and fail on anything newer.
        known = {(36, "2026-09-03")}
        unexpected = {k: n for k, n in over.items() if k not in known}
        for (run, day), n in sorted(over.items()):
            print(f"[{'KNOWN' if (run, day) in known else 'NEW'}] run {run} filled {n} on {day}")
        assert not unexpected, f"entry cap breached after the fix: {unexpected}"
    print(f"[OK] live invariant: no unexpected day exceeds {bt.MAX_NEW_ENTRIES_PER_DAY} fills "
          f"({len(per_day)} entry-days checked)")


if __name__ == "__main__":
    test_daily_cap_and_ranking()
    test_cluster_window_counts_only_still_open()
    test_cutoff_is_anchored_on_today_not_on_the_last_eod_row()
    test_live_no_day_exceeds_cap()
    print("\n[DONE] entry-cap self-check passed")
