"""Dry-run self-check for entry_scenarios.py (no Supabase). Usage: python src/test_entry_scenarios.py"""

from datetime import date, timedelta

import pandas as pd

import backtest_v4 as bt
import entry_scenarios as es

# Synthetic IHSG: calm drift up to 7000, a -11% crash day, then a slide to ~5200 (BEARISH, far below MA50).
closes = [6000 + i * 4 for i in range(250)]
closes.append(closes[-1] * 0.8843)
for _ in range(20):
    closes.append(closes[-1] * 0.995)
start = date(2025, 1, 1)
idx = pd.DataFrame({"trade_date": [start + timedelta(days=i) for i in range(len(closes))], "close": closes})
idx["ma50"] = idx["close"].rolling(50, min_periods=50).mean()
fn, cd, tm = bt.compute_regime_with_hysteresis, bt.REGIME_CONFIRM_DAYS, bt.TREND_STRENGTH_MIN

regime, streak, trend = fn(idx)
assert regime[idx["trade_date"].iloc[-1]] == "BEARISH"

level = es.level_to_watch(idx, fn)
assert level is not None and level > closes[-1]
print(f"[PASS] level to watch {level:,.0f} is above the last close {closes[-1]:,.0f}")

flat = es.earliest_open_session(idx, fn, cd, tm, 0.0)
half = es.earliest_open_session(idx, fn, cd, tm, 0.005)
one = es.earliest_open_session(idx, fn, cd, tm, 0.01)
assert flat is None, flat  # flat close drags MA50 to the close -> trend 0% -> never >= 1%
assert one is not None and half is not None and one <= half, (one, half)
assert one >= cd  # at least the confirming days
print(f"[PASS] flat={flat} +0.5%/day={half} +1%/day={one} sessions")

# Self-consistency: the gate really reads open at that session and not one session earlier.
def gate_at(daily, k):
    base = idx[["trade_date", "close"]].copy()
    last = base["close"].iloc[-1]
    extra = pd.DataFrame({"trade_date": [base["trade_date"].iloc[-1] + timedelta(days=j) for j in range(1, k + 1)],
                          "close": [last * (1 + daily) ** j for j in range(1, k + 1)]})
    df = pd.concat([base, extra], ignore_index=True)
    df["ma50"] = df["close"].rolling(50, min_periods=50).mean()
    return es._gate_open(df, fn, cd, tm)

assert gate_at(0.01, one) and not gate_at(0.01, one - 1)
print("[PASS] gate opens exactly at the reported session, not before")

lines = es.summary_lines(idx, fn, cd, tm, closes[-1])
txt = "\n".join(lines)
assert "Gerbang entry baru terbuka kalau IHSG tutup di atas" in txt
assert "harga datar: tidak dalam 120 sesi" in txt and "bukan prediksi" in txt
print("[PASS] summary lines")

assert es.add_weekdays(date(2026, 11, 19), 2) == date(2026, 11, 23)  # Thu -> Fri, Mon
print("[PASS] add_weekdays skips the weekend")
print("\nAll entry_scenarios checks passed.")