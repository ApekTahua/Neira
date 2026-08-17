"""Self-check for BACKLOG_QUEUE_ENABLED / BACKLOG_EXPIRY_DAYS (docs/V3_FINDINGS_LOG.md,
"bounded backlog/priority queue" entry -- the OTHER candidate direction from the
scarce-MAX_POSITIONS-slot investigation, after Phase 2's widening approach was rejected).

Four things a broken implementation could silently get wrong:

  1. Flag OFF (the default) must be reproducible and byte-identical to the pre-backlog
     baseline. Flag ON must actually differ -- a flag that never fires isn't a null result,
     it's a bug (see the adaptive-hold-time caution in docs/V3_FINDINGS_LOG.md: that feature
     "looked like it changed nothing" once and turned out to be dead code, not a real null).
  2. Expiry is enforced: no admitted position's age (day_idx at fill - origin_day_idx) may
     exceed 1 + BACKLOG_EXPIRY_DAYS.
  3. Regime re-validation is enforced: every admitted position with age > 1 (a genuine
     backlog fill, not the normal one-shot-tomorrow path every fill already had before this
     feature existed) only happens on a day diag itself tagged "BULLISH" -- necessary, not
     sufficient (diag doesn't expose the full multi-part gate), but enough to catch the
     obvious break of a backlog fill sneaking through on a non-bullish day.
  4. The diag hook itself stays purely additive under backlog mode too, not just the
     default off-backlog case test_diag_hook.py already covers.

Same real out-of-sample slice as test_diag_hook.py (2025-07-01..2025-08-31, inside the
already-diagnosed, candidate-dense Window 8) -- fast, no synthetic DataFrame needed.

Usage: python src/test_backlog_queue.py
(requires .cache/walk_forward_data_2021-01-01_2026-06-30.pkl, same as every other script
this session.)
"""

from datetime import date

import walk_forward_v4 as wf

bt = wf.bt

df, idx_df = wf.load_dataset()

TRAIN_END, TEST_START, TEST_END = date(2025, 6, 30), date(2025, 7, 1), date(2025, 8, 31)

# ---- (1) OFF is reproducible, ON actually differs ----
bt.BACKLOG_QUEUE_ENABLED = False
m_off1, tr_off1, eq_off1, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="off1")
bt.BACKLOG_QUEUE_ENABLED = True
bt.BACKLOG_EXPIRY_DAYS = 3
diag_on = {}
m_on, tr_on, eq_on, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="on", diag=diag_on)
bt.BACKLOG_QUEUE_ENABLED = False
m_off2, tr_off2, eq_off2, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="off2")

assert tr_off1.equals(tr_off2), "BACKLOG_QUEUE_ENABLED=False trade list must be reproducible run-to-run"
assert not tr_on.equals(tr_off1), (
    "BACKLOG_QUEUE_ENABLED=True produced a byte-identical trade list to OFF on a real slice -- "
    "the mechanism never actually fired here (dead flag) or this slice doesn't exercise it; "
    "check before trusting a sweep."
)
print(f"[PASS] OFF reproducible ({len(tr_off1)} trades both times), ON differs "
      f"({len(tr_on)} trades) -- the flag actually changes behavior, not a silent no-op.")

# ---- (2)/(3): expiry + regime-gate enforcement, from the diag hook's own bookkeeping ----
backlog_fills = [(d["date"], a) for d in diag_on["days"] for a in (d["admitted"] or []) if a["age"] > 1]
assert len(backlog_fills) > 0, "expected at least one genuine backlog fill (age > 1) on this candidate-dense slice"
max_age = 1 + bt.BACKLOG_EXPIRY_DAYS
for dt, a in backlog_fills:
    assert a["age"] <= max_age, f"{dt} admitted {a['stock_code']} at age {a['age']} > {max_age} -- expiry not enforced"
backlog_fill_dates = {d["date"] for d in diag_on["days"] for a in (d["admitted"] or []) if a["age"] > 1}
for d in diag_on["days"]:
    if d["date"] in backlog_fill_dates:
        assert d["regime"] == "BULLISH", (
            f"{d['date']} admitted a backlog (age>1) fill on a non-BULLISH-tagged day -- regime re-validation not enforced")
print(f"[PASS] {len(backlog_fills)} genuine backlog fills (age 2..{max_age} vs max_age={max_age}), "
      f"all within expiry, all on regime-tagged BULLISH days.")

# ---- (4) diag hook stays purely additive under backlog mode too ----
bt.BACKLOG_QUEUE_ENABLED = True
m_on_nodiag, tr_on_nodiag, eq_on_nodiag, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="on_nodiag")
assert m_on == m_on_nodiag and tr_on.equals(tr_on_nodiag), "diag kwarg must not change trading decisions under backlog mode either"
print("[PASS] diag hook remains purely additive with BACKLOG_QUEUE_ENABLED=True too.")

bt.BACKLOG_QUEUE_ENABLED = False  # restore default for anything importing this module after
print("\nAll backlog-queue checks passed.")
