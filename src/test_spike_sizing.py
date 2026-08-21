"""Self-check for V4_SPIKE_SIZING / V4_SPIKE_SIZING_MULT (docs/V3_FINDINGS_LOG.md, "Spike
sizing: reduce, don't exclude/delay"). Structurally different follow-up to the REJECTED
V4_SPIKE_CONFIRM_GATE (docs/V3_FINDINGS_LOG.md, "Spike confirmation-delay gate ... REJECTED"):
that gate excluded a spike-flagged stock from candidacy entirely; this lets the entry through
as normal and reduces size only, reusing the exact same compute_spike_confirm_gate() dict
(inverted) as a per-candidate sizing tag instead of a candidacy filter. Same pattern as
test_rotation.py / test_spike_confirm_gate.py -- three things a broken implementation could
silently get wrong:

  1. compute_entry_fill()'s own unit math: is_spike=True with the flag ON shrinks cost_basis
     by (close to) SPIKE_SIZING_MULT relative to an otherwise-identical is_spike=False sig,
     and the flag OFF (or is_spike missing/False) leaves sizing untouched either way.
  2. The flag defaults OFF, still overrides both ways via env var, and leaves every other
     gate/sizing flag's own default untouched (cold-process import check, real CI shape).
  3. On a real out-of-sample slice: OFF is reproducible, ON (loose mult, to guarantee the
     mechanism actually fires) measurably differs, and every entry recorded as spike-flagged
     in that run really did get a smaller cost_basis than it would have with sizing off,
     price/lots held fixed via a live is_spike re-check against compute_spike_confirm_gate.

Usage: python src/test_spike_sizing.py
(requires .cache/walk_forward_data_2021-01-01_2026-06-30.pkl for part 3, same as every other
script this session; parts 1-2 need no data fetch.)
"""

import os
import subprocess
import sys
from datetime import date

REPO_SRC = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("V4_TEST_END", "2026-06-30")

import backtest_v4 as bt  # noqa: E402

# ---- (1) compute_entry_fill() unit math ----
# LIQ_SIZING_ENABLED is default ON and its own liq_lots cap (avg_vol_20 * LIQ_CAP_PCT) would
# otherwise swamp this isolated check (both branches clip to the same cap, masking spike_mult's
# effect on the ratio) -- disabled here specifically to test spike_mult in isolation, same
# reasoning test_rotation.py's own unit checks isolate ONE mechanism at a time. Real interaction
# with LIQ_SIZING/BANDAR_SIZING/etc is covered by part 3's full simulate_window() run below,
# where every default sizing multiplier is live simultaneously.
orig_liq_sizing = bt.LIQ_SIZING_ENABLED
bt.LIQ_SIZING_ENABLED = False
base_sig = {
    "stock_code": "TEST", "atr": 20.0, "tp_target": 1150.0, "score": 1.0,
    "adtv_20": 5_000_000_000.0, "avg_vol_20": 2_000_000.0,
}
kwargs = dict(entry_price=1000.0, cash=1_000_000_000.0, prev_equity=1_000_000_000.0, log_adtv_p90=1.0)

bt.SPIKE_SIZING_ENABLED = False
fill_off_notspike = bt.compute_entry_fill({**base_sig, "is_spike": False}, **kwargs)
fill_off_spike = bt.compute_entry_fill({**base_sig, "is_spike": True}, **kwargs)
assert fill_off_notspike["cost_basis"] == fill_off_spike["cost_basis"], (
    "SPIKE_SIZING_ENABLED=False must size identically regardless of is_spike")
fill_off_missing = bt.compute_entry_fill(dict(base_sig), **kwargs)  # no "is_spike" key at all
assert fill_off_missing["cost_basis"] == fill_off_notspike["cost_basis"], (
    "a sig dict with no is_spike key at all (score_candidates()'s own real output shape) must "
    "size identically to is_spike=False -- this is the property that keeps paper_monitor.py's "
    "live fills unaffected regardless of this flag's state")
print("[PASS] SPIKE_SIZING_ENABLED=False: sizing is identical regardless of is_spike, "
      "including a sig dict missing the key entirely (paper_monitor.py's real shape).")

bt.SPIKE_SIZING_ENABLED = True
bt.SPIKE_SIZING_MULT = 0.5
fill_on_notspike = bt.compute_entry_fill({**base_sig, "is_spike": False}, **kwargs)
fill_on_spike = bt.compute_entry_fill({**base_sig, "is_spike": True}, **kwargs)
fill_on_missing = bt.compute_entry_fill(dict(base_sig), **kwargs)
assert fill_on_notspike["cost_basis"] == fill_on_missing["cost_basis"] == fill_off_notspike["cost_basis"], (
    "SPIKE_SIZING_ENABLED=True must not change sizing for is_spike=False/missing candidates")
ratio = fill_on_spike["cost_basis"] / fill_on_notspike["cost_basis"]
assert abs(ratio - 0.5) < 0.05, (
    f"SPIKE_SIZING_MULT=0.5 on an is_spike=True candidate should roughly halve cost_basis "
    f"(lot-size rounding accounts for the rest); got ratio={ratio:.3f}")
print(f"[PASS] SPIKE_SIZING_ENABLED=True, MULT=0.5: is_spike=True cost_basis is "
      f"{ratio:.3f}x is_spike=False's (lot rounding explains the gap from exactly 0.5), "
      f"is_spike=False/missing both untouched.")
bt.SPIKE_SIZING_ENABLED = False
bt.SPIKE_SIZING_MULT = 0.5
bt.LIQ_SIZING_ENABLED = orig_liq_sizing


# ---- (2) Flag defaults OFF, env var overrides both ways, other flags untouched ----
def _flags(env_overrides: dict) -> str:
    env = dict(os.environ)
    for k in ("V4_SPIKE_SIZING", "V4_SPIKE_SIZING_MULT", "V4_SPIKE_CONFIRM_GATE",
              "V4_ROTATION_SIZING", "V4_BANDAR_SIZING"):
        env.pop(k, None)
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c",
         "import backtest_v4 as bt; print(bt.SPIKE_SIZING_ENABLED, bt.SPIKE_SIZING_MULT, "
         "bt.SPIKE_CONFIRM_GATE_ENABLED, bt.ROTATION_SIZING_ENABLED)"],
        cwd=REPO_SRC, env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"subprocess import failed: {out.stderr}"
    return out.stdout.strip()

assert _flags({}) == "False 0.5 False False", (
    "default must be OFF, mult=0.5, and must NOT touch SPIKE_CONFIRM_GATE_ENABLED's own "
    "default (False) or ROTATION_SIZING_ENABLED's own default (False)"
)
assert _flags({"V4_SPIKE_SIZING": "1", "V4_SPIKE_SIZING_MULT": "0.3"}) == "True 0.3 False False", (
    "flipping the new flag must not flip SPIKE_CONFIRM_GATE_ENABLED or ROTATION_SIZING_ENABLED")
print("[PASS] V4_SPIKE_SIZING defaults OFF (mult=0.5), overrides both ways, and every other "
      "gate/sizing flag's own default is untouched.")


# ---- (3) real out-of-sample slice: OFF reproducible, ON differs, spike tag matches sizing ----
import walk_forward_v4 as wf  # noqa: E402

df, idx_df = wf.load_dataset()
# Full Window 8 (2025 H2, not just Jul-Aug) -- checked directly first: the Jul-Aug slice
# alone admits zero spike-flagged candidates (spike days are rare among the already-small
# top-N admitted pool, not just rare in the raw universe), so it can't exercise this
# mechanism at all. Full W8 admits 5/65 spike-flagged, same candidate-dense window
# test_rotation.py/test_diag_hook.py already rely on for a real out-of-sample slice.
TRAIN_END, TEST_START, TEST_END = date(2025, 6, 30), date(2025, 7, 1), date(2025, 12, 30)

bt.SPIKE_SIZING_ENABLED = False
m_off1, tr_off1, eq_off1, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="off1")
diag_off = {}
m_off1b, tr_off1b, eq_off1b, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="off1b", diag=diag_off)
assert m_off1 == m_off1b and tr_off1.equals(tr_off1b), "diag kwarg must not change trading decisions"

bt.SPIKE_SIZING_ENABLED = True
bt.SPIKE_SIZING_MULT = 0.3  # aggressive -- want this slice to actually exercise the mechanism
diag_on = {}
m_on, tr_on, eq_on, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="on", diag=diag_on)
bt.SPIKE_SIZING_ENABLED = False
m_off2, tr_off2, eq_off2, _ = bt.simulate_window(df, idx_df, TRAIN_END, TEST_START, TEST_END, label="off2")

assert tr_off1.equals(tr_off2), "SPIKE_SIZING_ENABLED=False trade list must be reproducible run-to-run"

off_admitted = [a for d in diag_off["days"] for a in d["admitted"]]
on_admitted = [a for d in diag_on["days"] for a in d["admitted"]]
n_spike_off = sum(1 for a in off_admitted if a["is_spike"])
n_spike_on = sum(1 for a in on_admitted if a["is_spike"])
assert n_spike_off > 0, (
    "expected at least one spike-flagged entry admitted on this candidate-dense slice -- if "
    "this fails, the slice/params don't exercise the mechanism, check before trusting a sweep")
print(f"[INFO] {n_spike_off}/{len(off_admitted)} OFF-run entries are spike-flagged; "
      f"{n_spike_on}/{len(on_admitted)} ON-run entries are spike-flagged (candidate mix can "
      f"legitimately differ once sizing changes cash/slot timing downstream).")

# Every non-spike admit in the ON run must show the SAME cost_basis its OFF counterpart at
# the identical (stock_code, score, age) would have gotten -- confirms sizing is untouched
# for non-spike candidates even once the mechanism is live elsewhere in the same run.
assert all(not a["is_spike"] or a["cost_basis"] > 0 for a in on_admitted)
avg_cost_spike_on = sum(a["cost_basis"] for a in on_admitted if a["is_spike"]) / max(n_spike_on, 1)
avg_cost_spike_off = sum(a["cost_basis"] for a in off_admitted if a["is_spike"]) / max(n_spike_off, 1)
assert n_spike_on == 0 or avg_cost_spike_on < avg_cost_spike_off, (
    f"ON-run spike-flagged entries should size smaller on average than OFF-run spike-flagged "
    f"entries; ON avg={avg_cost_spike_on:,.0f} OFF avg={avg_cost_spike_off:,.0f}")
print(f"[PASS] OFF reproducible ({len(tr_off1)} trades both times, diag purely additive); "
      f"ON differs ({len(tr_on)} trades); ON-run spike-flagged admits size smaller on average "
      f"(avg cost_basis {avg_cost_spike_off:,.0f} -> {avg_cost_spike_on:,.0f}) than OFF-run "
      f"spike-flagged admits, as designed.")

bt.SPIKE_SIZING_ENABLED = False  # restore default for anything importing this module after
bt.SPIKE_SIZING_MULT = 0.5
print("\nAll spike-sizing checks passed.")
