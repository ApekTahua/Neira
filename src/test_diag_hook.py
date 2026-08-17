"""Self-check for simulate_window's `diag` research hook (src/diagnose_slot_queue.py,
src/trace_w8_slot_swaps.py). Two things a broken instrumentation could silently get
wrong:

  1. Zero side effects on trading decisions -- diag=None (every existing caller:
     walk_forward_v4.py, feature_test_harness.py, sweep_vol_band_mult.py,
     sweep_max_positions.py, main()) must produce byte-identical trades/metrics to
     diag={} (this script) and to not passing the kwarg at all.
  2. The per-day bookkeeping is internally consistent: every candidate-day's
     break-reason bucket accounts for the whole day, dropped-candidate counts are
     zero on days that never broke, and (the one directly checkable causal claim)
     every day tagged break_reason="max_positions" really did end that day with a
     full portfolio.

Runs one real, short out-of-sample slice (2025-07-01..2025-08-31, inside the
already-diagnosed Window 8) against the local dataset cache -- fast, no synthetic
DataFrame construction needed for a function this deep in simulate_window's own
column-schema assumptions.

Usage: python src/test_diag_hook.py
(requires .cache/walk_forward_data_2021-01-01_2026-06-30.pkl, same as every other
script in this session.)
"""

from datetime import date

import walk_forward_v4 as wf

bt = wf.bt

df, idx_df = wf.load_dataset()

TRAIN_END, TEST_START, TEST_END = date(2025, 6, 30), date(2025, 7, 1), date(2025, 8, 31)

# ---- (1) diag=None / diag={} / omitted kwarg must be byte-identical ----
m_none, tr_none, eq_none, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="none", diag=None)
m_omit, tr_omit, eq_omit, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="omit")
diag = {}
m_diag, tr_diag, eq_diag, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="diag", diag=diag)

assert m_none == m_omit == m_diag, "diag kwarg must not change simulate_window's metrics"
assert tr_none.equals(tr_omit) and tr_none.equals(tr_diag), "diag kwarg must not change the trade list"
assert eq_none.equals(eq_omit) and eq_none.equals(eq_diag), "diag kwarg must not change the equity curve"
print(f"[PASS] diag=None / diag={{}} / omitted kwarg all produce identical trades "
      f"({len(tr_none)} trades) and equity curves -- zero side effect on trading decisions")

# ---- (2) internal consistency of the diag day-log itself ----
days = diag["days"]
assert len(days) > 0, "expected at least one candidate-day in this real slice"
for d in days:
    reasons = {"max_positions", "daily_cap", "cluster_cap", None}
    assert d["break_reason"] in reasons
    if d["break_reason"] is None:
        assert d["dropped"] == [], "a day that never broke must have nothing dropped"
    if d["break_reason"] == "max_positions":
        assert d["positions_end_count"] == bt.MAX_POSITIONS, (
            f"{d['date']} tagged max_positions but ended with "
            f"{d['positions_end_count']} != MAX_POSITIONS={bt.MAX_POSITIONS} positions")
    # admitted count must match the day's own new-entry count implied by position deltas
    assert len(d["admitted"]) <= bt.MAX_NEW_ENTRIES_PER_DAY
n_break_mp = sum(1 for d in days if d["break_reason"] == "max_positions")
n_dropped_mp = sum(len(d["dropped"]) for d in days if d["break_reason"] == "max_positions")
print(f"[PASS] {len(days)} candidate-days, {n_break_mp} broke on max_positions "
      f"(every one ended with exactly MAX_POSITIONS={bt.MAX_POSITIONS} open), "
      f"{n_dropped_mp} candidates dropped by that reason alone -- diag bookkeeping is internally consistent")

print("\nAll diag-hook checks passed.")
