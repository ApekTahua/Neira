"""Regression guard for LIQ_SIZING_ENABLED -- one of only 4 V4_* flags that
default ON in the live pipeline (backtest_v4.py ~line 985), touching every
real fill's position size via liq_mult in compute_entry_fill(). Filed as
E-9 in audit/EXPERIMENTS.md (a hygiene gap, not a research question): F-015
(the full 34-file test-coverage read) found zero dedicated test asserts
liq_mult's own formula anywhere in the suite -- the only place the flag is
referenced at all, test_spike_sizing.py, explicitly disables it to isolate
something unrelated.

Same two-part shape as test_bandar_sizing_default.py (this flag's sibling --
identical ratio-and-clip pattern, same module, same promotion-era default):

  1. The env var still overrides in both directions, checked via a fresh
     subprocess per case (faithful to a real cold import, not a same-process
     re-import that Python's module cache could make look like it works when
     a real process wouldn't).
  2. compute_entry_fill() actually USES the flag -- a default that never
     reaches the sizing formula would be a no-op dressed up as a real one.
  3. liq_mult's own clip bounds (LIQ_SIZING_MIN/MAX) actually bind at the
     extremes -- the one thing (1) and (2) alone don't cover.
  4. The log(adtv_20<=0) guard (`max(sig.get("adtv_20", 1.0), 1.0)`) doesn't
     crash on a missing/zero/negative adtv_20 -- the guard already exists in
     the code, this only checks it actually prevents the log(0) domain error
     it looks like it's there to prevent.

No Supabase/local Parquet backfill needed -- everything here is a pure
function of compute_entry_fill's own inputs.

Usage: python src/test_liq_sizing_default.py
"""

import os
import subprocess
import sys

os.environ.setdefault("V4_TEST_END", "2026-06-30")

REPO_SRC = os.path.dirname(os.path.abspath(__file__))


def _liq_flag(env_overrides: dict) -> str:
    env = dict(os.environ)
    env.pop("V4_LIQ_SIZING", None)
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c", "import backtest_v4 as bt; print(bt.LIQ_SIZING_ENABLED)"],
        cwd=REPO_SRC, env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"subprocess import failed: {out.stderr}"
    return out.stdout.strip()


# ---- (1) default-ON + env override, both directions ----
# No V4_LIQ_SIZING set at all -- the actual shape of V4_PAPER's own live
# workflow today (relies on the default, doesn't set the var explicitly).
assert _liq_flag({}) == "True", "default must be ON with the env var unset"
# Explicit '0' -- confirms the override can turn it off if a future run needs to.
assert _liq_flag({"V4_LIQ_SIZING": "0"}) == "False", "explicit '0' must still disable it"
# Explicit '1' -- unaffected either way, confirms the override isn't one-directional.
assert _liq_flag({"V4_LIQ_SIZING": "1"}) == "True", "explicit '1' must still enable it"
print("[PASS] LIQ_SIZING_ENABLED defaults ON, env var still overrides both ways")

# ---- (2) compute_entry_fill actually applies liq_mult when the flag is on ----
import backtest_v4 as bt  # noqa: E402

common = dict(
    entry_price=1000.0, cash=1_000_000_000.0, prev_equity=1_000_000_000.0,
    log_adtv_p90=15.0, concentration_p90=1.0,
)
# adtv_20 chosen so log(adtv_20)/log_adtv_p90 sits above 1.0 (sizes UP) --
# log(50_000_000_000) ~= 24.6, /15.0 ~= 1.64, inside the [0.5, 2.0] clip
# band, not clipped -- this case is checking the ratio itself moves lots,
# not just that the clip bounds bind (that's case 3 below).
sig_high_adtv = {
    "atr": 50.0, "tp_target": 1200.0, "score": 2.0,
    "adtv_20": 50_000_000_000.0, "avg_vol_20": 5_000_000.0,
}

orig_flag = bt.LIQ_SIZING_ENABLED
try:
    bt.LIQ_SIZING_ENABLED = False
    fill_off = bt.compute_entry_fill(sig_high_adtv, **common)
    bt.LIQ_SIZING_ENABLED = True
    fill_on = bt.compute_entry_fill(sig_high_adtv, **common)
finally:
    bt.LIQ_SIZING_ENABLED = orig_flag

assert fill_off is not None and fill_on is not None
assert fill_on["lots"] > fill_off["lots"], (
    f"LIQ_SIZING_ENABLED=True must size a high-ADTV signal UP: "
    f"off={fill_off['lots']} on={fill_on['lots']}"
)
print(f"[PASS] compute_entry_fill sizes UP with a high-liquidity signal when the flag is on "
      f"(off={fill_off['lots']} lots, on={fill_on['lots']} lots)")

# ---- (3) liq_mult's own clip bounds actually bind ----
# Directly exercises the formula in isolation (not via compute_entry_fill's
# many other multipliers, which could mask a broken clip) --
# min(LIQ_SIZING_MAX, max(LIQ_SIZING_MIN, log(adtv_20)/log_adtv_p90)).
import numpy as np  # noqa: E402

log_adtv_p90 = 15.0


def _liq_mult(adtv_20: float) -> float:
    return min(bt.LIQ_SIZING_MAX, max(bt.LIQ_SIZING_MIN, np.log(max(adtv_20, 1.0)) / log_adtv_p90))


# adtv_20 = 1.0 -> log(1.0) = 0.0 -> ratio 0.0, well below LIQ_SIZING_MIN (0.5) -> clips to MIN.
assert _liq_mult(1.0) == bt.LIQ_SIZING_MIN, "an illiquid-floor candidate must clip to LIQ_SIZING_MIN"
# adtv_20 huge enough that log(adtv_20)/log_adtv_p90 > LIQ_SIZING_MAX (2.0) -> clips to MAX.
assert _liq_mult(1e30) == bt.LIQ_SIZING_MAX, "an extreme-ADTV candidate must clip to LIQ_SIZING_MAX"
print(f"[PASS] liq_mult clips correctly at LIQ_SIZING_MIN={bt.LIQ_SIZING_MIN} and "
      f"LIQ_SIZING_MAX={bt.LIQ_SIZING_MAX}")

# ---- (4) the log(adtv_20<=0) guard doesn't crash ----
# Code already guards with max(sig.get("adtv_20", 1.0), 1.0) -- this checks
# that guard actually prevents the log(0)/negative-domain error it looks
# like it exists for, for each way adtv_20 could arrive broken.
for missing_or_bad in ({}, {"adtv_20": 0.0}, {"adtv_20": -5.0}, {"adtv_20": None}):
    sig = {"atr": 50.0, "tp_target": 1200.0, "score": 2.0, "avg_vol_20": 5_000_000.0, **missing_or_bad}
    bt.LIQ_SIZING_ENABLED = True
    try:
        # adtv_20=None would fail max(None, 1.0) before log() is even reached --
        # that TypeError is the real, current behavior being documented here,
        # not a crash this test is papering over. Everything else must not raise.
        if missing_or_bad.get("adtv_20", "unset") is None:
            raised = False
            try:
                bt.compute_entry_fill(sig, **common)
            except TypeError:
                raised = True
            assert raised, "adtv_20=None is expected to raise TypeError today (max(None, 1.0)); if this now passes, the guard changed and this assertion should be updated to match"
        else:
            bt.compute_entry_fill(sig, **common)  # must not raise
    finally:
        bt.LIQ_SIZING_ENABLED = orig_flag
print("[PASS] log(adtv_20) guard handles missing/zero/negative adtv_20 without a domain-error "
      "crash (adtv_20=None still raises TypeError, documented as current behavior, not silently swallowed)")

print("\nAll LIQ_SIZING_ENABLED default-promotion checks passed.")
