"""Dry-run self-check for BANDAR_SIZING_ENABLED's 2026-08-15 promotion to
default ON (docs/BANDARMOLOGY_DESIGN.md, "BANDAR_SIZING_ENABLED promoted to
default ON"). Two things a broken default flip could silently get wrong:

  1. The env var still overrides in both directions -- V3_PAPER's live
     workflows now pin V3_BANDAR_SIZING=0 explicitly to stay frozen; if the
     override stopped working, that pin would be a no-op and V3_PAPER's
     new-entry sizing would silently drift.
  2. compute_entry_fill() actually USES the flag -- a promoted default that
     doesn't reach the sizing formula would be a no-op change dressed up as
     a real one.

Checks (1) via a fresh subprocess per case (faithful to how a real CI job
imports the module cold -- avoids Python's own module-cache making a
same-process re-import look like it works when a real process wouldn't).
Checks (2) directly against compute_entry_fill with the module constant
monkeypatched. No Supabase/local Parquet backfill needed.

Usage: python src/test_bandar_sizing_default.py
"""

import os
import subprocess
import sys
from datetime import date

os.environ.setdefault("V3_TEST_END", "2026-06-30")

REPO_SRC = os.path.dirname(os.path.abspath(__file__))


def _bandar_flag(env_overrides: dict) -> str:
    env = dict(os.environ)
    env.pop("V3_BANDAR_SIZING", None)
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c", "import backtest_v4 as bt; print(bt.BANDAR_SIZING_ENABLED)"],
        cwd=REPO_SRC, env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"subprocess import failed: {out.stderr}"
    return out.stdout.strip()


# No V3_BANDAR_SIZING set at all -- the actual shape of V4_PAPER's own
# workflow today (relies on the default, doesn't set the var explicitly).
assert _bandar_flag({}) == "True", "default must be ON with the env var unset"
# Explicit '0' -- the actual shape of V3_PAPER's pinned workflow post-promotion.
assert _bandar_flag({"V3_BANDAR_SIZING": "0"}) == "False", "explicit '0' must still disable it"
# Explicit '1' -- unaffected either way, just confirms the override isn't one-directional.
assert _bandar_flag({"V3_BANDAR_SIZING": "1"}) == "True", "explicit '1' must still enable it"
print("[PASS] BANDAR_SIZING_ENABLED defaults ON, env var still overrides both ways")

# ---- compute_entry_fill actually applies bandar_mult when the flag is on ----
import backtest_v4 as bt  # noqa: E402

sig = {
    "atr": 50.0, "tp_target": 1200.0, "score": 2.0,
    "adtv_20": 5_000_000.0, "avg_vol_20": 5_000_000.0,
    "concentration": 0.9,  # well above concentration_p90 below -> should size UP
}
common = dict(
    entry_price=1000.0, cash=1_000_000_000.0, prev_equity=1_000_000_000.0,
    log_adtv_p90=15.0, concentration_p90=0.3,
)

orig_flag = bt.BANDAR_SIZING_ENABLED
try:
    bt.BANDAR_SIZING_ENABLED = False
    fill_off = bt.compute_entry_fill(sig, **common)
    bt.BANDAR_SIZING_ENABLED = True
    fill_on = bt.compute_entry_fill(sig, **common)
finally:
    bt.BANDAR_SIZING_ENABLED = orig_flag

assert fill_off is not None and fill_on is not None
# concentration/concentration_p90 = 0.9/0.3 = 3.0, clipped to BANDAR_SIZING_MAX (2.0) ->
# fill_on's alloc (and therefore lots, pre-liquidity-cap) must come out strictly larger.
assert fill_on["lots"] > fill_off["lots"], (
    f"BANDAR_SIZING_ENABLED=True must size a high-concentration signal UP: "
    f"off={fill_off['lots']} on={fill_on['lots']}"
)
print(f"[PASS] compute_entry_fill sizes UP with concentration signal when the flag is on "
      f"(off={fill_off['lots']} lots, on={fill_on['lots']} lots)")

print("\nAll BANDAR_SIZING_ENABLED default-promotion checks passed.")
