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
    test_live_no_day_exceeds_cap()
    print("\n[DONE] entry-cap self-check passed")
