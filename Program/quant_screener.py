"""
Quant Screener: Accumulation Detector (Relaxed for Bearish Market)
Runs daily on GitHub Actions with Supabase PostgreSQL.
"""

import os
import sys
import pandas as pd
import numpy as np
from supabase import create_client, Client
from datetime import date, timedelta

import config as cfg
from notifier import send_screener_results

# ----------------------------------------------------------------------
# Supabase connection
# ----------------------------------------------------------------------
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
if not url or not key:
    sys.exit("Missing Supabase environment variables")

supabase: Client = create_client(url, key)

# ----------------------------------------------------------------------
# 1. Determine latest date & IHSG market regime
# ----------------------------------------------------------------------
try:
    latest_date_res = supabase.table("ihsg_eod") \
        .select("trade_date") \
        .order("trade_date", desc=True) \
        .limit(1) \
        .execute()
    if not latest_date_res.data:
        sys.exit("No data in ihsg_eod")
    latest_date = pd.Timestamp(latest_date_res.data[0]["trade_date"]).date()
    start_date = latest_date - timedelta(days=cfg.LOOKBACK_DAYS)
    print(f"Latest market date: {latest_date}")

    # ---- IHSG (COMPOSITE) ----
    idx_data = []
    offset = 0
    while True:
        batch = supabase.table("index_eod") \
            .select("trade_date,close") \
            .eq("index_code", "COMPOSITE") \
            .gte("trade_date", start_date.isoformat()) \
            .lte("trade_date", latest_date.isoformat()) \
            .order("trade_date") \
            .range(offset, offset + 999) \
            .execute()
        if not batch.data:
            break
        idx_data.extend(batch.data)
        offset += 1000

    if idx_data:
        idx_df = pd.DataFrame(idx_data)
        idx_df["trade_date"] = pd.to_datetime(idx_df["trade_date"]).dt.date
        idx_df = idx_df.sort_values("trade_date")
        idx_df["close"] = pd.to_numeric(idx_df["close"], errors="coerce")
        idx_df["ma50"] = idx_df["close"].rolling(50, min_periods=50).mean()
        latest_idx = idx_df.iloc[-1]
        if pd.notna(latest_idx.get("ma50")):
            close_idx = latest_idx["close"]
            ma50_idx = latest_idx["ma50"]
            # simple 5‑day slope
            ma50_slope = idx_df["ma50"].diff(5).iloc[-1] if len(idx_df["ma50"].dropna()) > 5 else 0
            if close_idx > ma50_idx and ma50_slope > 0:
                market_label = "BULLISH"
                market_multiplier = cfg.MARKET_BULLISH_MULT
            elif close_idx < ma50_idx and ma50_slope < 0:
                market_label = "BEARISH"
                market_multiplier = cfg.MARKET_BEARISH_MULT
            else:
                market_label = "NEUTRAL"
                market_multiplier = cfg.MARKET_NEUTRAL_MULT
            pct_dev = (close_idx / ma50_idx - 1) * 100
            print(f"IHSG Market Regime: {market_label} "
                  f"(Close={close_idx:,.2f}, MA50={ma50_idx:,.2f}, "
                  f"%dev={pct_dev:+.1f}%, multiplier={market_multiplier})")
        else:
            market_label = "NEUTRAL"
            market_multiplier = 1.0
    else:
        print("WARNING: No IHSG data retrieved. Using neutral multiplier.")
        market_label = "UNKNOWN"
        market_multiplier = 1.0

except Exception as e:
    sys.exit(f"Supabase index query failed: {e}")

# ----------------------------------------------------------------------
# 2. Fetch stock historical data
# ----------------------------------------------------------------------
try:
    all_data = []
    offset = 0
    while True:
        batch = supabase.table("ihsg_eod") \
            .select("stock_code,trade_date,close_price,volume,previous") \
            .gte("trade_date", start_date.isoformat()) \
            .lte("trade_date", latest_date.isoformat()) \
            .order("trade_date") \
            .range(offset, offset + 999) \
            .execute()
        if not batch.data:
            break
        all_data.extend(batch.data)
        offset += 1000

    if not all_data:
        sys.exit("No stock data retrieved")
    df = pd.DataFrame(all_data)
except Exception as e:
    sys.exit(f"Failed to fetch stock data: {e}")

# ----------------------------------------------------------------------
# 3. Data preparation
# ----------------------------------------------------------------------
df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
df = df.sort_values(["stock_code", "trade_date"])
for col in ["close_price", "volume", "previous"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# Only keep stocks present on the latest trading day
stocks_on_latest = df[df["trade_date"] == latest_date]["stock_code"].unique()
df = df[df["stock_code"].isin(stocks_on_latest)].copy()

# ----------------------------------------------------------------------
# 4. Vectorised feature engineering
# ----------------------------------------------------------------------
def add_features(group: pd.DataFrame) -> pd.DataFrame:
    group = group.sort_values("trade_date")
    # Moving averages
    group["ma10"] = group["close_price"].rolling(10, min_periods=10).mean()
    group["ma20"] = group["close_price"].rolling(20, min_periods=20).mean()
    group["ma50"] = group["close_price"].rolling(50, min_periods=50).mean()
    # Bollinger Bands (20,2)
    group["std20"] = group["close_price"].rolling(20, min_periods=20).std()
    group["bb_upper"] = group["ma20"] + 2 * group["std20"]
    group["bb_lower"] = group["ma20"] - 2 * group["std20"]
    group["bb_bandwidth"] = 4 * group["std20"] / group["ma20"] * 100  # percent
    # Volume averages
    group["avg_vol_20"] = group["volume"].rolling(20, min_periods=20).mean()
    group["avg_vol_20_prev"] = group["volume"].shift(1).rolling(20, min_periods=20).mean()
    # Daily return
    group["daily_return"] = group["close_price"] / group["previous"] - 1
    # Sleeping detection helpers
    group["rolling_min_close"] = group["close_price"].rolling(
        cfg.SLEEPING_FLAT_DAYS, min_periods=cfg.SLEEPING_FLAT_DAYS
    ).min()
    group["rolling_max_close"] = group["close_price"].rolling(
        cfg.SLEEPING_FLAT_DAYS, min_periods=cfg.SLEEPING_FLAT_DAYS
    ).max()
    # ---- UT Bot ATR trailing stop (adapted from ut_bot.pine) ----
    # Approximate ATR from close-to-close change (no high/low in data)
    group["tr"] = (group["close_price"] - group["previous"]).abs()
    group["atr"] = group["tr"].rolling(cfg.UT_ATR_PERIOD, min_periods=cfg.UT_ATR_PERIOD).mean()
    n_loss = cfg.UT_MULTIPLIER * group["atr"]
    # Vectorised trailing stop via expanding window
    stop = np.full(len(group), np.nan)
    pos = np.full(len(group), 0)
    for i in range(len(group)):
        src = group["close_price"].iloc[i]
        src1 = group["close_price"].iloc[i - 1] if i > 0 else src
        stop1 = stop[i - 1] if i > 0 and not np.isnan(stop[i - 1]) else 0
        pos1 = pos[i - 1] if i > 0 else 0
        loss = n_loss.iloc[i]
        if src1 > stop1 and src > stop1:
            stop[i] = max(stop1, src - loss)
        elif src1 < stop1 and src < stop1:
            stop[i] = min(stop1, src + loss)
        else:
            stop[i] = src - loss if src > stop1 else src + loss
        pos[i] = 1 if src1 < stop1 and src > stop1 else (-1 if src1 > stop1 and src < stop1 else pos1)
    group["ut_stop"] = stop
    group["ut_position"] = pos  # 1 = bullish, -1 = bearish
    group["ut_buy_signal"] = (group["ut_position"] == 1) & (group["ut_position"].shift(1) == -1)
    # ---- SMC Swing pivots, Order Block, TP (adapted from LuxAlgo) ----
    p = cfg.SMC_SWING_PERIOD
    group["swing_high"] = group["close_price"].rolling(p, min_periods=p).max().shift(p // 2)
    group["swing_low"] = group["close_price"].rolling(p, min_periods=p).min().shift(p // 2)
    # Last confirmed swing low — the nearest local minimum
    is_swing_low = (group["close_price"] == group["swing_low"]) & (group["close_price"] < group["close_price"].shift(1))
    group["last_swing_low"] = group["swing_low"].where(is_swing_low).ffill()
    # Order block = ±buffer around last swing low (buy area)
    last_low = group["last_swing_low"].fillna(group["close_price"])
    buy_buffer = last_low * cfg.SMC_OB_BUFFER_PCT
    group["buy_zone_low"] = last_low - buy_buffer
    group["buy_zone_high"] = last_low + buy_buffer
    # TP = nearest swing high that was broken above
    is_swing_high = (group["close_price"] == group["swing_high"]) & (group["close_price"] > group["close_price"].shift(1))
    group["last_swing_high"] = group["swing_high"].where(is_swing_high).ffill()
    # TP fallback: if no swing high above price, use 1.05× close
    above_price = group["last_swing_high"] > group["close_price"]
    group["tp_target"] = group["last_swing_high"].where(above_price).fillna(group["close_price"] * 1.05)
    return group

df = df.groupby("stock_code", group_keys=False).apply(add_features)

# ----------------------------------------------------------------------
# 5. Latest day & red flag filters
# ----------------------------------------------------------------------
latest = df[df["trade_date"] == latest_date].copy()
required_cols = ["ma10", "ma20", "ma50", "std20", "avg_vol_20", "avg_vol_20_prev"]
latest = latest.dropna(subset=required_cols)

# Exclude sleeping stocks (flat at 50 for N days)
sleeping = (
    (latest["close_price"] <= cfg.SLEEPING_PRICE) &
    (latest["rolling_min_close"] == cfg.SLEEPING_PRICE) &
    (latest["rolling_max_close"] == cfg.SLEEPING_PRICE)
)
# Exclude illiquid stocks (low average volume)
illiquid = latest["avg_vol_20"] < cfg.MIN_LIQUIDITY_VOL

red_flagged = sleeping | illiquid
candidates = latest[~red_flagged].copy()
print(f"Stocks after red-flag removal: {len(candidates)} / {len(latest)}")

if candidates.empty:
    print("No candidates pass red-flag filters. Exiting.")
    sys.exit(0)

# ----------------------------------------------------------------------
# 6. Core strategy conditions (RELAXED)
# ----------------------------------------------------------------------
# --- MA Squeeze ---
ma_spread = (
    candidates[["ma10", "ma20", "ma50"]].max(axis=1) -
    candidates[["ma10", "ma20", "ma50"]].min(axis=1)
) / candidates["ma50"] * 100
squeeze_ma = ma_spread < cfg.MA_SQUEEZE_THRESHOLD

# --- BB Squeeze ---
squeeze_bb = candidates["bb_bandwidth"] < cfg.BB_SQUEEZE_THRESHOLD

# --- Volume Anomaly ---
vol_ratio = candidates["volume"] / candidates["avg_vol_20_prev"]
volume_anomaly = vol_ratio > cfg.VOL_SPIKE_MULT

# --- Price Constraint (flat/resilient) ---
flat_price = candidates["daily_return"].abs() <= cfg.FLAT_RANGE
price_not_overbought = candidates["close_price"] < candidates["bb_upper"]
price_condition = flat_price & price_not_overbought

# Combine all
signal_mask = squeeze_ma & squeeze_bb & volume_anomaly & price_condition

# ---- UT Bot trend overlay (not mandatory, used for scoring) ----
candidates["ut_bullish"] = candidates["ut_position"] == 1
candidates["ut_fresh_buy"] = candidates.get("ut_buy_signal", False)

# ===================== DIAGNOSTIC LOGGING =====================
print("\n--- Filter Diagnostics ---")
print(f"Passed MA Squeeze:       {squeeze_ma.sum()}")
print(f"Passed BB Squeeze:       {squeeze_bb.sum()}")
print(f"Passed Volume Spike:     {volume_anomaly.sum()}")
print(f"Passed Price Constraint: {price_condition.sum()}")
ut_bullish_count = candidates["ut_bullish"].sum()
ut_signal_count = candidates["ut_fresh_buy"].sum()
print(f"In UT Uptrend:           {ut_bullish_count}")
print(f"Fresh UT Buy Signal:     {ut_signal_count}")
print(f"Passed ALL (Final):      {signal_mask.sum()}")
# ===============================================================

signals = candidates[signal_mask].copy()
if signals.empty:
    print("\nNo stocks meet the accumulation criteria today.")
    sys.exit(0)

# ----------------------------------------------------------------------
# 7. Confidence scoring (0-100)
# ----------------------------------------------------------------------
ma_spread_signal = (
    signals[["ma10", "ma20", "ma50"]].max(axis=1) -
    signals[["ma10", "ma20", "ma50"]].min(axis=1)
) / signals["ma50"] * 100
bb_width = signals["bb_bandwidth"]
vol_ratio_signal = signals["volume"] / signals["avg_vol_20_prev"]

# Normalised sub‑scores
squeeze_ma_score = np.clip(100 * (1 - ma_spread_signal / cfg.SCORE_MA_SPREAD_MAX), 0, 100)
squeeze_bb_score = np.clip(100 * (1 - bb_width / cfg.SCORE_BB_WIDTH_MAX), 0, 100)
vol_score = np.clip(100 * (vol_ratio_signal - 1) / (cfg.SCORE_VOL_MULT_MAX - 1), 0, 100)

# Composite (volume is the most important trigger)
confidence_raw = 0.20 * squeeze_ma_score + 0.20 * squeeze_bb_score + 0.60 * vol_score

# UT Bot bonus: +15% if in uptrend, another +10 if fresh crossover
ut_boost = 1.0
if "ut_bullish" in signals.columns:
    ut_boost += signals["ut_bullish"].astype(float) * 0.15
    ut_boost += signals.get("ut_fresh_buy", pd.Series(0, index=signals.index)).astype(float) * 0.10

# Apply market regime multiplier + UT boost
signals["confidence"] = np.round(confidence_raw * market_multiplier * ut_boost, 1)
signals["vol_spike_pct"] = (vol_ratio_signal - 1) * 100
signals["ut_trend"] = signals["ut_position"].map({1: "UP", -1: "DOWN"}).fillna("?")
signals["ut_cross"] = signals.get("ut_fresh_buy", False)
# SMC: buy zone & TP
signals["buy_zone"] = signals["buy_zone_low"].fillna(0).round(0).astype(int).astype(str) + "–" + signals["buy_zone_high"].fillna(0).round(0).astype(int).astype(str)
signals["tp_target"] = signals["tp_target"].fillna(0).round(0).astype(int)

# Top‑10 selection
top10 = signals.nlargest(10, "confidence")

# ----------------------------------------------------------------------
# 8. Console output
# ----------------------------------------------------------------------
print("\n" + "=" * 70)
print(f"{'TOP ACCUMULATION CANDIDATES':^70}")
print(f"Date: {latest_date}   IHSG Regime: {market_label} (adj ×{market_multiplier})")
print("=" * 70)
print(f"{'Stock':<8} {'Conf':>7} {'Buy Zone':>16} {'TP':>10}")
print("-" * 70)

for _, row in top10.iterrows():
    print(f"{row['stock_code']:<8} {row['confidence']:>6.1f}% "
          f"{row['buy_zone']:>16} {row['tp_target']:>10}")

print("-" * 70)
print(f"Generated by quant_screener.py – {date.today().isoformat()}")
print("Note: Confidence already adjusted by market regime multiplier.")

# ----------------------------------------------------------------------
# 9. Send results to Telegram
# ----------------------------------------------------------------------
send_screener_results(top10, latest_date, market_label, market_multiplier)
