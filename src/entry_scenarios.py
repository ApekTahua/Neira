"""entry_scenarios.py -- "when could the entry gate open?" for the daily Telegram summary.

Pure arithmetic on the entry rule, not a forecast. It re-runs the engine's own
compute_regime_with_hysteresis (passed in as `regime_fn`) on the real IHSG history plus synthetic
closes, one session at a time, so the volatility window, the 50-day average and the confirming days
are counted by the same code that decides real entries. The frontend (newscraper.ai
lib/regime-gauge.ts entryScenario) ports the same arithmetic for the "What would open the gate" card;
the two are cross-checked against each other, so change them together.

Reads nothing from, and writes nothing to, the strategy config or the database.
"""

from datetime import date, timedelta

import pandas as pd

BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

# (label for the message, constant daily change of the IHSG close)
SCENARIOS = (("harga datar", 0.0), ("naik 0,5% per hari", 0.005), ("naik 1% per hari", 0.01))
MAX_SESSIONS = 120
LEVEL_STEP = 0.001   # 0.1% steps, same as the frontend
LEVEL_MAX_STEPS = 400


def _gate_open(df, regime_fn, confirm_days, trend_min) -> bool:
    regime, streak, trend = regime_fn(df)
    d = df["trade_date"].iloc[-1]
    return (regime.get(d) == "BULLISH" and streak.get(d, 0) >= confirm_days
            and trend.get(d, 0.0) >= trend_min)


def _with_ma50(df):
    df["ma50"] = df["close"].rolling(50, min_periods=50).mean()
    return df


def earliest_open_session(idx_df, regime_fn, confirm_days, trend_min, daily, max_sessions=MAX_SESSIONS):
    """Sessions until the gate first reads open if the IHSG close moves by `daily` every session
    (includes the confirming days). None = not within max_sessions."""
    base = idx_df[["trade_date", "close"]].copy()
    last_date, last_close = base["trade_date"].iloc[-1], float(base["close"].iloc[-1])
    for k in range(1, max_sessions + 1):
        extra = pd.DataFrame({
            "trade_date": [last_date + timedelta(days=j) for j in range(1, k + 1)],
            "close": [last_close * (1 + daily) ** j for j in range(1, k + 1)],
        })
        df = _with_ma50(pd.concat([base, extra], ignore_index=True))
        if _gate_open(df, regime_fn, confirm_days, trend_min):
            return k
    return None


def level_to_watch(idx_df, regime_fn):
    """Lowest next close (0.1% steps) that makes tomorrow's state BULLISH, or None. Only meaningful
    while the state is not already BULLISH."""
    base = idx_df[["trade_date", "close"]].copy()
    last_date, last_close = base["trade_date"].iloc[-1], float(base["close"].iloc[-1])
    for k in range(1, LEVEL_MAX_STEPS + 1):
        p = last_close * (1 + k * LEVEL_STEP)
        df = _with_ma50(pd.concat(
            [base, pd.DataFrame({"trade_date": [last_date + timedelta(days=1)], "close": [p]})], ignore_index=True))
        regime, _, _ = regime_fn(df)
        if regime.get(df["trade_date"].iloc[-1]) == "BULLISH":
            return p
    return None


def add_weekdays(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _num(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def summary_lines(idx_df, regime_fn, confirm_days, trend_min, close_now: float) -> list:
    """Plain Indonesian lines for the daily message: the level to watch and the earliest-open
    session under three price paths. Same numbers as the website card."""
    last_date = idx_df["trade_date"].iloc[-1]
    level = level_to_watch(idx_df, regime_fn)
    if level is not None:
        first = (f"Gerbang entry baru terbuka kalau IHSG tutup di atas {_num(level)} "
                 f"(sekarang {_num(close_now)}).")
    else:
        first = ("Tidak ada satu hari tutup yang cukup untuk membuka gerbang entry. "
                 "IHSG perlu naik beberapa hari berturut-turut.")
    parts = []
    for label, daily in SCENARIOS:
        k = earliest_open_session(idx_df, regime_fn, confirm_days, trend_min, daily)
        if k is None:
            parts.append(f"{label}: tidak dalam {MAX_SESSIONS} sesi")
        else:
            d = add_weekdays(last_date, k)
            parts.append(f"{label}: {k} sesi lagi (sekitar {d.day} {BULAN[d.month - 1]})")
    return [first, "Paling cepat gerbang terbuka, kalau " + "; ".join(parts) +
            ". Ini hitungan dari aturan beli, bukan prediksi."]