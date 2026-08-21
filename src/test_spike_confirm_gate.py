"""Self-check for V4_SPIKE_CONFIRM_GATE (docs/V3_FINDINGS_LOG.md, "Spike
confirmation-delay gate ..."). Follow-up to the "TEBE gorengan base-rate
research" entry -- gates candidacy on a PER-STOCK breakout-spike/confirmation
pattern, structurally unrelated to the rejected TREND_DURATION_GATE (index-
level trend_strength persistence) or PARTICIPATION_GATE (market-wide daily
turnover). Two things a broken implementation could silently get wrong:

  1. compute_spike_confirm_gate()'s state machine: blackout for
     confirm_days after a spike, then a single pass/fail checkpoint that
     decides the whole episode (not re-checked daily afterward), and a
     newer spike restarting the blackout even mid-episode.
  2. The flag defaults OFF, still overrides both ways via env var, and
     leaves every other gate's own default untouched -- this is a NEW,
     separate, isolated gate.

Usage: python src/test_spike_confirm_gate.py
"""

import os
import subprocess
import sys
from datetime import date, timedelta

import pandas as pd

os.environ.setdefault("V4_TEST_END", "2026-06-30")

REPO_SRC = os.path.dirname(os.path.abspath(__file__))

import backtest_v4 as bt  # noqa: E402

# ---- compute_spike_confirm_gate: blackout -> single checkpoint -> permanent-until-next-spike ----
dates = [date(2023, 1, 2) + timedelta(days=i) for i in range(12)]

# Stock AAA: spikes on day 2 (close 100 -> 130, +30%, volume 20x). confirm_days=3,
# giveback_pct=0.15 -> floor = 130*0.85 = 110.5. Blackout = days 2,3,4 (days_since 0,1,2).
# Checkpoint at day 5 (days_since=3): close=115 >= 110.5 -> PASSES -> gate open from day 5 on,
# permanently, even though day 8 dips to 108 (below the floor) -- no re-checking.
aaa_close = [100, 100, 130, 128, 120, 115, 118, 120, 108, 112, 116, 120]
aaa_vol =   [1,   1,   20,  1,   1,   1,   1,   1,   1,   1,   1,   1]
# Stock BBB: same spike shape but the checkpoint FAILS (day 5 close way below floor) ->
# stays excluded for the rest of the episode, even though it recovers later.
bbb_close = [100, 100, 130, 90,  85,  90,  95,  140, 145, 150, 155, 160]
bbb_vol =   [1,   1,   20,  1,   1,   1,   1,   1,   1,   1,   1,   1]

rows = []
for stock, closes, vols in (("AAA", aaa_close, aaa_vol), ("BBB", bbb_close, bbb_vol)):
    prev = closes[0]
    for i, (c, v) in enumerate(zip(closes, vols)):
        rows.append({
            "stock_code": stock, "trade_date": dates[i], "close_price": float(c),
            "volume": float(v), "avg_vol_20_prev": 1.0,
            "daily_return": (c / prev - 1) if prev else 0.0,
        })
        prev = c
df = pd.DataFrame(rows)

gate = bt.compute_spike_confirm_gate(df, vol_mult=10.0, move_pct=0.20, confirm_days=3, giveback_pct=0.15)

expected_aaa = [True, True, False, False, False, True, True, True, True, True, True, True]
got_aaa = [gate[("AAA", d)] for d in dates]
assert got_aaa == expected_aaa, f"AAA gate mismatch: {got_aaa} != {expected_aaa}"
print("[PASS] compute_spike_confirm_gate: blackout for confirm_days, checkpoint passes, "
      "gate stays open afterward even through a later dip below the floor (no re-checking)")

expected_bbb = [True, True, False, False, False, False, False, False, False, False, False, False]
got_bbb = [gate[("BBB", d)] for d in dates]
assert got_bbb == expected_bbb, f"BBB gate mismatch: {got_bbb} != {expected_bbb}"
print("[PASS] compute_spike_confirm_gate: failed checkpoint excludes for the rest of the "
      "episode even though price recovers well past the floor later")

# A stock that never spikes should read True on every row (no-op).
ccc_rows = [{"stock_code": "CCC", "trade_date": dates[i], "close_price": 100.0, "volume": 1.0,
             "avg_vol_20_prev": 1.0, "daily_return": 0.0} for i in range(len(dates))]
df_ccc = pd.DataFrame(rows + ccc_rows)
gate2 = bt.compute_spike_confirm_gate(df_ccc, vol_mult=10.0, move_pct=0.20, confirm_days=3, giveback_pct=0.15)
assert all(gate2[("CCC", d)] for d in dates), "a stock that never spikes must gate True on every row"
print("[PASS] compute_spike_confirm_gate: a stock that never spikes is a pure no-op")


# ---- Flag defaults OFF, env var overrides both ways, cold-process import (real CI shape) ----
def _gate_flags(env_overrides: dict) -> str:
    env = dict(os.environ)
    for k in ("V4_SPIKE_CONFIRM_GATE", "V4_SPIKE_CONFIRM_DAYS", "V4_SPIKE_GIVEBACK_PCT",
              "V4_PARTICIPATION_GATE", "V4_TREND_DURATION_GATE"):
        env.pop(k, None)
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c",
         "import backtest_v4 as bt; print(bt.SPIKE_CONFIRM_GATE_ENABLED, bt.SPIKE_CONFIRM_DAYS, "
         "bt.SPIKE_GIVEBACK_PCT, bt.SPIKE_VOL_MULT, bt.SPIKE_MOVE_PCT, "
         "bt.PARTICIPATION_GATE_ENABLED, bt.TREND_DURATION_GATE_ENABLED)"],
        cwd=REPO_SRC, env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"subprocess import failed: {out.stderr}"
    return out.stdout.strip()

assert _gate_flags({}) == "False 3 0.15 10.0 0.2 False False", (
    "default must be OFF (confirm_days=3, giveback=0.15, vol_mult=10.0, move_pct=0.2), "
    "and must NOT touch PARTICIPATION_GATE_ENABLED/TREND_DURATION_GATE_ENABLED's own defaults"
)
assert _gate_flags({"V4_SPIKE_CONFIRM_GATE": "1", "V4_SPIKE_CONFIRM_DAYS": "5"}) == (
    "True 5 0.15 10.0 0.2 False False"
), "flipping the new flag must not flip any other gate's own default"
print("[PASS] V4_SPIKE_CONFIRM_GATE defaults OFF, overrides both ways, and every other "
      "gate's own default is untouched")

print("\nAll spike-confirm-gate checks passed.")
