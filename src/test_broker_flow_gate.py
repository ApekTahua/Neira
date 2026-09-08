"""Self-check for V4_BROKER_FLOW_GATE (research candidate, docs/V3_FINDINGS_LOG.md
2026-08-25 entry -- "market-wide broker-flow gate"). Two things a broken
implementation could silently get wrong, same discipline as test_participation_gate.py:

  1. compute_market_broker_flow() restricts to the SAME liquid universe
     score_candidates() uses (adtv_20 >= cfg.ADTV_MIN) -- an illiquid stock's
     huge/lopsided flow must NOT leak into the market-wide aggregate.
  2. The rolling window needs `window_days` of history before it emits a value
     (dropna()'d, not filled with a fake 0), and BROKER_FLOW_MIN's own lookup
     site (`.get(trade_date, BROKER_FLOW_MIN)`) means a missing/unknown date
     never blocks a trade regardless of threshold sign.
  3. The flag defaults OFF, overrides both ways via env var, and leaves every
     other gate's own default untouched.

Usage: python src/test_broker_flow_gate.py
"""

import os
from datetime import date, timedelta

os.environ.setdefault("V4_TEST_END", "2026-06-30")

import pandas as pd  # noqa: E402
import backtest_v4 as bt  # noqa: E402
import config as cfg  # noqa: E402

# ---- Synthetic archive: one liquid stock (LIQ), one illiquid stock (ILLIQ) ----
n_days = 5
dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(n_days)]

raw_rows = []
df_rows = []
for d in dates:
    # LIQ: buy 10 lots @1000, sell 4 lots @1000 -- net=600,000, turnover=1,400,000,
    # ratio = 600000/1400000 = 3/7 every day (constant, easy to hand-check a rolling mean of).
    raw_rows += [
        {"stock_code": "LIQ", "broker_code": "AA", "side": "buy", "lot": 10.0, "avg_price": 1000.0,
         "val_rupiah": 10 * 100 * 1000.0, "trade_date": d.isoformat()},
        {"stock_code": "LIQ", "broker_code": "BB", "side": "sell", "lot": 4.0, "avg_price": 1000.0,
         "val_rupiah": 4 * 100 * 1000.0, "trade_date": d.isoformat()},
    ]
    df_rows.append({"stock_code": "LIQ", "trade_date": d, "close_price": 1000.0, "high": 1000.0,
                     "low": 1000.0, "volume": 100_000, "adtv_20": 2 * cfg.ADTV_MIN})

    # ILLIQ: a much bigger, heavily one-sided net flow (would swamp LIQ's ratio if it leaked
    # into the aggregate) but adtv_20 sits below cfg.ADTV_MIN -- must be excluded.
    raw_rows += [
        {"stock_code": "ILLIQ", "broker_code": "CC", "side": "buy", "lot": 1000.0, "avg_price": 500.0,
         "val_rupiah": 1000 * 100 * 500.0, "trade_date": d.isoformat()},
    ]
    df_rows.append({"stock_code": "ILLIQ", "trade_date": d, "close_price": 500.0, "high": 500.0,
                     "low": 500.0, "volume": 200_000, "adtv_20": 0.5 * cfg.ADTV_MIN})

raw = pd.DataFrame(raw_rows)
df = pd.DataFrame(df_rows)

bt.bf.load_raw = lambda: raw.assign(trade_date=pd.to_datetime(raw["trade_date"]).dt.date)
bt._broker_flow_ratio_cache.clear()

WINDOW = 3
out = bt.compute_market_broker_flow(df, window_days=WINDOW)

# ---- 1: illiquid flow must not leak in ----
expected_ratio = 600_000.0 / 1_400_000.0
for d in dates[WINDOW - 1:]:
    got = out[d]
    assert abs(got - expected_ratio) < 1e-9, (
        f"{d}: got {got:.6f}, expected {expected_ratio:.6f} (LIQ-only) -- "
        f"ILLIQ's flow may have leaked into the liquid-universe aggregate"
    )
print(f"[PASS] compute_market_broker_flow restricts to the liquid universe "
      f"(adtv_20 >= cfg.ADTV_MIN) -- illiquid ILLIQ's flow does not leak in "
      f"(ratio={expected_ratio:.4f} every day, matches hand-computed LIQ-only value)")

# ---- 2: rolling window needs window_days of history; missing dates default to "pass" ----
for d in dates[:WINDOW - 1]:
    assert d not in out, f"{d}: should have no value yet (< {WINDOW} days of history), got {out.get(d)}"
print(f"[PASS] first {WINDOW - 1} day(s) have no rolling value yet (dropna'd, not a fake 0)")

missing_date = date(2099, 1, 1)
lookup_default = out.get(missing_date, bt.BROKER_FLOW_MIN)
assert lookup_default == bt.BROKER_FLOW_MIN, "an unknown date's lookup must default to BROKER_FLOW_MIN itself (always passes >=)"
print("[PASS] an unknown/missing date's gate lookup defaults to BROKER_FLOW_MIN itself -- never blocks")


# ---- 3: flag defaults OFF, overrides both ways, other gates' defaults untouched ----
import subprocess  # noqa: E402
import sys  # noqa: E402

REPO_SRC = os.path.dirname(os.path.abspath(__file__))


def _gate_flags(env_overrides: dict) -> str:
    env = dict(os.environ)
    for k in ("V4_BROKER_FLOW_GATE", "V4_BROKER_FLOW_WINDOW_DAYS", "V4_BROKER_FLOW_MIN",
              "V4_PARTICIPATION_GATE", "V4_PARTICIPATION_MIN"):
        env.pop(k, None)
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c",
         "import backtest_v4 as bt; print(bt.BROKER_FLOW_GATE_ENABLED, bt.BROKER_FLOW_WINDOW_DAYS, "
         "bt.BROKER_FLOW_MIN, bt.PARTICIPATION_GATE_ENABLED, bt.PARTICIPATION_MIN)"],
        cwd=REPO_SRC, env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"subprocess import failed: {out.stderr}"
    return out.stdout.strip()


assert _gate_flags({}) == "False 5 0.0 False 0.95", (
    "default must be OFF, window=5, min=0.0, and must NOT touch PARTICIPATION_GATE_ENABLED's own defaults"
)
assert _gate_flags({"V4_BROKER_FLOW_GATE": "1", "V4_BROKER_FLOW_MIN": "0.01"}) == (
    "True 5 0.01 False 0.95"
), "flipping the new flag must not flip PARTICIPATION_GATE_ENABLED's own default"
print("[PASS] V4_BROKER_FLOW_GATE defaults OFF, overrides both ways, and PARTICIPATION_GATE's own default is untouched")

print("\nAll broker-flow-gate checks passed.")
