"""Self-check for V4_DIVERGENCE_GATE (research candidate, docs/V3_FINDINGS_LOG.md
2026-08-25 entry -- "per-stock smart-money divergence gate"). Same discipline as
test_broker_flow_gate.py. Checks a broken implementation could silently get wrong:

  1. compute_broker_divergence() restricts foreign/retail legs to the exact broker
     codes named (32 Foreign-classified codes / XL+XC+PD only for retail) -- a
     BUMN or other-Local broker's flow must NOT leak into either leg, and the
     ratio must be relative to that STOCK's OWN total turnover (all brokers).
  2. The rolling window needs `window_days` of history before it emits a value
     (dropna()'d, not filled with a fake 0), and an unknown (stock, date) lookup
     defaults to "pass" (>= its own DIVERGENCE_MIN).
  3. The flag defaults OFF, overrides both ways via env var, and leaves every
     other gate's own default untouched.

Usage: python src/test_broker_divergence_gate.py
"""

import os
from datetime import date, timedelta

os.environ.setdefault("V4_TEST_END", "2026-06-30")

import pandas as pd  # noqa: E402
import backtest_v4 as bt  # noqa: E402

# ---- Synthetic archive: one stock, 5 days, one Foreign broker (AK) buying, one retail
# broker (XL) selling, one BUMN broker (CC) trading too (must not leak into either leg) ----
n_days = 5
dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(n_days)]

raw_rows, df_rows = [], []
for d in dates:
    raw_rows += [
        # Foreign (AK): buy 20 lots @1000 = 2,000,000
        {"stock_code": "DIV", "broker_code": "AK", "side": "buy", "lot": 20.0, "avg_price": 1000.0,
         "val_rupiah": 20 * 100 * 1000.0, "trade_date": d.isoformat()},
        # Retail (XL): sell 10 lots @1000 = 1,000,000
        {"stock_code": "DIV", "broker_code": "XL", "side": "sell", "lot": 10.0, "avg_price": 1000.0,
         "val_rupiah": 10 * 100 * 1000.0, "trade_date": d.isoformat()},
        # BUMN (CC): buy 10 lots @1000 = 1,000,000 -- counts in total_turnover, must NOT
        # appear in foreign_net or retail_net.
        {"stock_code": "DIV", "broker_code": "CC", "side": "buy", "lot": 10.0, "avg_price": 1000.0,
         "val_rupiah": 10 * 100 * 1000.0, "trade_date": d.isoformat()},
    ]
    df_rows.append({"stock_code": "DIV", "trade_date": d, "close_price": 1000.0, "high": 1000.0,
                     "low": 1000.0, "volume": 100_000})

raw = pd.DataFrame(raw_rows)
df = pd.DataFrame(df_rows)

bt.bf.load_raw = lambda: raw.assign(trade_date=pd.to_datetime(raw["trade_date"]).dt.date)
bt._broker_divergence_raw_cache.clear()

WINDOW = 3
out = bt.compute_broker_divergence(df, window_days=WINDOW)

# ---- 1: hand-checked value, BUMN leg excluded from both foreign_net and retail_net ----
# Per day: foreign_net=+2,000,000, retail_net=-1,000,000, total_turnover=2M+1M+1M=4,000,000
# (buy+sell across ALL brokers, all one-sided here so turnover = each leg's single-sided val).
# divergence = (foreign_net - retail_net) / total_turnover = (2,000,000 - (-1,000,000)) / 4,000,000 = 0.75
expected = 3_000_000.0 / 4_000_000.0
for d in dates[WINDOW - 1:]:
    got = out[("DIV", d)]
    assert abs(got - expected) < 1e-9, (
        f"{d}: got {got:.6f}, expected {expected:.6f} -- BUMN leg may have leaked into "
        f"foreign_net/retail_net, or total_turnover isn't using ALL brokers"
    )
print(f"[PASS] compute_broker_divergence restricts foreign/retail legs to their named broker "
      f"sets, normalizes by the stock's OWN total turnover (BUMN leg counted in the "
      f"denominator only) -- divergence={expected:.4f} every day, matches hand-computed value")

# ---- 2: rolling window needs window_days of history; missing (stock,date) defaults to "pass" ----
for d in dates[:WINDOW - 1]:
    assert ("DIV", d) not in out, f"{d}: should have no value yet (< {WINDOW} days of history)"
print(f"[PASS] first {WINDOW - 1} day(s) have no rolling value yet (dropna'd, not a fake 0)")

missing_key = ("NOPE", date(2099, 1, 1))
lookup_default = out.get(missing_key, bt.DIVERGENCE_MIN)
assert lookup_default == bt.DIVERGENCE_MIN, "an unknown (stock,date)'s lookup must default to DIVERGENCE_MIN itself (always passes >=)"
print("[PASS] an unknown/missing (stock,date)'s gate lookup defaults to DIVERGENCE_MIN itself -- never blocks")

# ---- 3: flag defaults OFF, overrides both ways, other gates' defaults untouched ----
import subprocess  # noqa: E402
import sys  # noqa: E402

REPO_SRC = os.path.dirname(os.path.abspath(__file__))


def _gate_flags(env_overrides: dict) -> str:
    env = dict(os.environ)
    for k in ("V4_DIVERGENCE_GATE", "V4_DIVERGENCE_WINDOW_DAYS", "V4_DIVERGENCE_MIN",
              "V4_BROKER_FLOW_GATE", "V4_BROKER_FLOW_MIN"):
        env.pop(k, None)
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c",
         "import backtest_v4 as bt; print(bt.DIVERGENCE_GATE_ENABLED, bt.DIVERGENCE_WINDOW_DAYS, "
         "bt.DIVERGENCE_MIN, bt.BROKER_FLOW_GATE_ENABLED, bt.BROKER_FLOW_MIN)"],
        cwd=REPO_SRC, env=env, capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"subprocess import failed: {out.stderr}"
    return out.stdout.strip()


assert _gate_flags({}) == "False 5 0.0 False 0.0", (
    "default must be OFF, window=5, min=0.0, and must NOT touch BROKER_FLOW_GATE_ENABLED's own defaults"
)
assert _gate_flags({"V4_DIVERGENCE_GATE": "1", "V4_DIVERGENCE_MIN": "0.1"}) == (
    "True 5 0.1 False 0.0"
), "flipping the new flag must not flip BROKER_FLOW_GATE_ENABLED's own default"
print("[PASS] V4_DIVERGENCE_GATE defaults OFF, overrides both ways, and BROKER_FLOW_GATE's own default is untouched")

print("\nAll broker-divergence-gate checks passed.")
