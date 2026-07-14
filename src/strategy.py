"""
strategy.py — Satu-satunya sumber logic sinyal Accumulation Detector.

screener.py (live, GitHub Actions harian) dan backtest.py
(simulasi historis) sama-sama import dari sini, supaya sinyal yang
dikirim ke Telegram selalu identik dengan yang sudah divalidasi backtest.
Jangan duplikasi fungsi-fungsi ini di tempat lain.
"""

import numpy as np
import pandas as pd

import config as cfg

REQUIRED_COLS = ["ma10", "ma20", "ma50", "std20", "avg_vol_20", "avg_vol_20_prev"]


# ======================================================================
# FEATURE ENGINEERING
# ======================================================================
def add_features(group: pd.DataFrame) -> pd.DataFrame:
    """Menambahkan indikator teknikal secara vektorisasi per grup saham.

    Butuh kolom: close_price, previous, volume, high, low, foreign_buy, foreign_sell.
    """
    group = group.sort_values("trade_date")

    # Moving averages
    group["ma10"] = group["close_price"].rolling(10, min_periods=10).mean()
    group["ma20"] = group["close_price"].rolling(20, min_periods=20).mean()
    group["ma50"] = group["close_price"].rolling(50, min_periods=50).mean()

    # Bollinger Bands (20,2)
    group["std20"] = group["close_price"].rolling(20, min_periods=20).std()
    group["bb_upper"] = group["ma20"] + 2 * group["std20"]
    group["bb_lower"] = group["ma20"] - 2 * group["std20"]
    group["bb_bandwidth"] = 4 * group["std20"] / group["ma20"] * 100

    # Volume averages
    group["avg_vol_20"] = group["volume"].rolling(20, min_periods=20).mean()
    group["avg_vol_20_prev"] = (
        group["volume"].shift(1).rolling(20, min_periods=20).mean()
    )

    # Daily return
    group["daily_return"] = group["close_price"] / group["previous"] - 1

    # Sleeping detection helpers
    group["rolling_min_close"] = (
        group["close_price"]
        .rolling(cfg.SLEEPING_FLAT_DAYS, min_periods=cfg.SLEEPING_FLAT_DAYS)
        .min()
    )
    group["rolling_max_close"] = (
        group["close_price"]
        .rolling(cfg.SLEEPING_FLAT_DAYS, min_periods=cfg.SLEEPING_FLAT_DAYS)
        .max()
    )

    # ---- UT Bot ATR trailing stop (adapted from ut_bot.pine) ----
    group["tr"] = (group["close_price"] - group["previous"]).abs()
    group["atr"] = group["tr"].rolling(
        cfg.UT_ATR_PERIOD, min_periods=cfg.UT_ATR_PERIOD
    ).mean()
    n_loss = cfg.UT_MULTIPLIER * group["atr"]

    stop = np.full(len(group), np.nan)
    pos = np.full(len(group), 0)
    close_vals = group["close_price"].to_numpy()
    loss_vals = n_loss.to_numpy()
    for i in range(len(group)):
        src = close_vals[i]
        src1 = close_vals[i - 1] if i > 0 else src
        stop1 = stop[i - 1] if i > 0 and not np.isnan(stop[i - 1]) else 0
        pos1 = pos[i - 1] if i > 0 else 0
        loss = loss_vals[i]
        if src1 > stop1 and src > stop1:
            stop[i] = max(stop1, src - loss)
        elif src1 < stop1 and src < stop1:
            stop[i] = min(stop1, src + loss)
        else:
            stop[i] = src - loss if src > stop1 else src + loss
        pos[i] = (
            1
            if src1 < stop1 and src > stop1
            else (-1 if src1 > stop1 and src < stop1 else pos1)
        )
    group["ut_stop"] = stop
    group["ut_position"] = pos
    group["ut_buy_signal"] = (group["ut_position"] == 1) & (
        group["ut_position"].shift(1) == -1
    )

    # ---- RSI (Lorentzian-inspired) ----
    delta = group["close_price"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss_ = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(cfg.RSI_PERIOD, min_periods=cfg.RSI_PERIOD).mean()
    avg_loss = loss_.rolling(cfg.RSI_PERIOD, min_periods=cfg.RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    group["rsi"] = 100 - (100 / (1 + rs))

    # ---- ADX (Lorentzian-inspired) ----
    group["tr_hl"] = (group["high"] - group["low"]).abs()
    group["tr_hc"] = (group["high"] - group["previous"]).abs()
    group["tr_lc"] = (group["low"] - group["previous"]).abs()
    group["tr_atr"] = group[["tr_hl", "tr_hc", "tr_lc"]].max(axis=1)
    group["atr_14"] = group["tr_atr"].rolling(cfg.ADX_PERIOD, min_periods=cfg.ADX_PERIOD).mean()

    group["up_move"] = group["high"] - group["high"].shift(1)
    group["down_move"] = group["low"].shift(1) - group["low"]
    group["plus_dm"] = np.where(
        (group["up_move"] > group["down_move"]) & (group["up_move"] > 0),
        group["up_move"],
        0.0,
    )
    group["minus_dm"] = np.where(
        (group["down_move"] > group["up_move"]) & (group["down_move"] > 0),
        group["down_move"],
        0.0,
    )
    group["plus_di"] = 100 * group["plus_dm"].rolling(cfg.ADX_PERIOD, min_periods=cfg.ADX_PERIOD).mean() / group["atr_14"].replace(0, np.nan)
    group["minus_di"] = 100 * group["minus_dm"].rolling(cfg.ADX_PERIOD, min_periods=cfg.ADX_PERIOD).mean() / group["atr_14"].replace(0, np.nan)
    group["dx"] = 100 * (group["plus_di"] - group["minus_di"]).abs() / (group["plus_di"] + group["minus_di"]).replace(0, np.nan)
    group["adx"] = group["dx"].rolling(cfg.ADX_PERIOD, min_periods=cfg.ADX_PERIOD).mean()

    # ---- SMA200 trend filter (Lorentzian-inspired) ----
    group["sma200"] = group["close_price"].rolling(cfg.SMA_TREND_PERIOD, min_periods=cfg.SMA_TREND_PERIOD).mean()

    # ---- ATR-based TP/SL (dinamis, bukan fixed 2%) ----
    group["atr_tp"] = group["close_price"] + group["atr_14"] * cfg.ATR_TP_MULTIPLIER
    group["atr_sl"] = group["close_price"] - group["atr_14"] * cfg.ATR_SL_MULTIPLIER

    # ---- SMC Swing pivots, Order Block, TP (LuxAlgo) ----
    p = cfg.SMC_SWING_PERIOD
    group["swing_high"] = group["close_price"].rolling(p, min_periods=p).max().shift(p // 2)
    group["swing_low"] = group["close_price"].rolling(p, min_periods=p).min().shift(p // 2)

    is_swing_low = (group["close_price"] == group["swing_low"]) & (
        group["close_price"] < group["close_price"].shift(1)
    )
    group["last_swing_low"] = group["swing_low"].where(is_swing_low).ffill()

    last_low = group["last_swing_low"].fillna(group["close_price"])
    buy_buffer = last_low * cfg.SMC_OB_BUFFER_PCT
    group["buy_zone_low"] = last_low - buy_buffer
    group["buy_zone_high"] = last_low + buy_buffer

    is_swing_high = (group["close_price"] == group["swing_high"]) & (
        group["close_price"] > group["close_price"].shift(1)
    )
    group["last_swing_high"] = group["swing_high"].where(is_swing_high).ffill()

    above_price = group["last_swing_high"] > group["close_price"]
    group["tp_target"] = (
        group["last_swing_high"].where(above_price).fillna(group["close_price"] * 1.05)
    )

    # ---- Foreign flow (Bandamologi) ----
    group["foreign_buy"] = pd.to_numeric(group["foreign_buy"], errors="coerce").fillna(0)
    group["foreign_sell"] = pd.to_numeric(group["foreign_sell"], errors="coerce").fillna(0)
    group["foreign_net"] = group["foreign_buy"] - group["foreign_sell"]
    group["foreign_net_ratio"] = group["foreign_net"] / group["volume"].replace(0, np.nan)
    group["foreign_net_ratio"] = group["foreign_net_ratio"].clip(-1, 1).fillna(0)
    group["foreign_net_ma"] = (
        group["foreign_net_ratio"].rolling(cfg.FOREIGN_LOOKBACK, min_periods=1).mean()
    )

    return group


# ======================================================================
# MARKET REGIME (IHSG)
# ======================================================================
def get_regime(idx_df: pd.DataFrame, trade_date) -> str:
    """Klasifikasi regime IHSG pada trade_date tertentu: BULLISH/NEUTRAL/BEARISH."""
    sub = idx_df[idx_df["trade_date"] <= trade_date]
    if sub.empty or "ma50" not in sub.columns:
        return "NEUTRAL"

    latest_idx = sub.iloc[-1]
    if pd.isna(latest_idx.get("ma50")):
        return "NEUTRAL"

    close_idx = latest_idx["close"]
    ma50_idx = latest_idx["ma50"]

    if close_idx > ma50_idx:
        return "BULLISH"
    elif close_idx < ma50_idx:
        return "BEARISH"
    else:
        return "NEUTRAL"


def get_regime_params(regime: str) -> dict:
    """Parameter trading sesuai regime."""
    if regime == "BULLISH":
        return {
            "confidence_min": cfg.CONF_BULLISH,
            "max_positions": cfg.MAX_POS_BULLISH,
            "sl_mult": cfg.SL_BULLISH,
            "tp_mult": cfg.TP_BULLISH,
            "alloc_pct": cfg.ALLOC_BULLISH,
            "min_conditions": cfg.BULLISH_MIN_CONDITIONS,
        }
    elif regime == "BEARISH":
        return {
            "confidence_min": cfg.CONF_BEARISH,
            "max_positions": cfg.MAX_POS_BEARISH,
            "sl_mult": cfg.SL_BEARISH,
            "tp_mult": cfg.TP_BEARISH,
            "alloc_pct": cfg.ALLOC_BEARISH,
            "min_conditions": cfg.BEARISH_MIN_CONDITIONS,
        }
    else:  # NEUTRAL
        return {
            "confidence_min": cfg.CONF_NEUTRAL,
            "max_positions": cfg.MAX_POS_NEUTRAL,
            "sl_mult": cfg.SL_NEUTRAL,
            "tp_mult": cfg.TP_NEUTRAL,
            "alloc_pct": cfg.ALLOC_NEUTRAL,
            "min_conditions": cfg.NEUTRAL_MIN_CONDITIONS,
        }


# ======================================================================
# SCREENER LOGIC PER HARI
# ======================================================================
def get_signals(df_day: pd.DataFrame, confidence_min: float, min_conditions: int = 4) -> pd.DataFrame:
    """
    Menjalankan logika screener pada data satu hari tertentu.
    Enhancement 4: jumlah kondisi yang dibutuhkan tergantung regime.
    Mengembalikan seluruh kolom candidates yang lolos + kolom confidence,
    diurutkan dari confidence tertinggi.
    """
    if df_day.empty:
        return pd.DataFrame()

    latest = df_day.dropna(subset=REQUIRED_COLS)
    if latest.empty:
        return pd.DataFrame()

    # --- Red-flag filters ---
    sleeping = (
        (latest["close_price"] <= cfg.SLEEPING_PRICE)
        & (latest["rolling_min_close"] == cfg.SLEEPING_PRICE)
        & (latest["rolling_max_close"] == cfg.SLEEPING_PRICE)
    )
    illiquid = latest["avg_vol_20"] < cfg.MIN_LIQUIDITY_VOL
    candidates = latest[~(sleeping | illiquid)].copy()
    if candidates.empty:
        return pd.DataFrame()

    # --- 4 kondisi sinyal ---
    ma_spread = (
        candidates[["ma10", "ma20", "ma50"]].max(axis=1)
        - candidates[["ma10", "ma20", "ma50"]].min(axis=1)
    ) / candidates["ma50"] * 100
    cond1 = ma_spread < cfg.MA_SQUEEZE_THRESHOLD
    cond2 = candidates["bb_bandwidth"] < cfg.BB_SQUEEZE_THRESHOLD
    vol_ratio = candidates["volume"] / candidates["avg_vol_20_prev"]
    cond3 = vol_ratio > cfg.VOL_SPIKE_MULT
    flat_price = candidates["daily_return"].abs() <= cfg.FLAT_RANGE
    price_not_overbought = candidates["close_price"] < candidates["bb_upper"]
    cond4 = flat_price & price_not_overbought

    conditions_met = cond1.astype(int) + cond2.astype(int) + cond3.astype(int) + cond4.astype(int)
    signal_mask = conditions_met >= min_conditions

    # Simpan kondisi mana yang kena, buat label "trigger" (dipakai website/laporan)
    candidates["cond_ma_squeeze"] = cond1
    candidates["cond_bb_squeeze"] = cond2
    candidates["cond_vol_spike"] = cond3
    candidates["cond_sideways"] = cond4

    # --- Lorentzian-inspired filters (wajib selalu) ---
    rsi_ok = candidates["rsi"].fillna(50) > cfg.RSI_OVERSOLD
    adx_ok = candidates["adx"].fillna(25) > cfg.ADX_THRESHOLD
    sma200_ok = candidates["sma200"].isna() | (candidates["close_price"] > candidates["sma200"])
    foreign_ok = candidates["foreign_net_ma"].fillna(0) >= cfg.FOREIGN_NET_MIN
    signal_mask = signal_mask & rsi_ok & adx_ok & sma200_ok & foreign_ok

    candidates["ut_bullish"] = candidates["ut_position"] == 1
    candidates["ut_fresh_buy"] = candidates.get("ut_buy_signal", False)

    signals = candidates[signal_mask].copy()
    if signals.empty:
        return pd.DataFrame()

    # --- Confidence scoring ---
    ma_spread_signal = (
        signals[["ma10", "ma20", "ma50"]].max(axis=1)
        - signals[["ma10", "ma20", "ma50"]].min(axis=1)
    ) / signals["ma50"] * 100
    bb_width = signals["bb_bandwidth"]
    vol_ratio_signal = signals["volume"] / signals["avg_vol_20_prev"]

    squeeze_ma_score = np.clip(100 * (1 - ma_spread_signal / cfg.SCORE_MA_SPREAD_MAX), 0, 100)
    squeeze_bb_score = np.clip(100 * (1 - bb_width / cfg.SCORE_BB_WIDTH_MAX), 0, 100)
    vol_score = np.clip(100 * (vol_ratio_signal - 1) / (cfg.SCORE_VOL_MULT_MAX - 1), 0, 100)

    rsi_val = signals["rsi"]
    rsi_score = np.clip(100 - 5 * (rsi_val - 50).abs(), 0, 100)
    adx_val = signals["adx"]
    adx_score = np.clip(100 * (adx_val - cfg.ADX_THRESHOLD) / 30, 0, 100)
    foreign_ratio = signals["foreign_net_ma"].fillna(0)
    foreign_score = np.clip(100 * foreign_ratio, 0, 100)

    confidence_raw = (
        0.10 * squeeze_ma_score
        + 0.10 * squeeze_bb_score
        + 0.35 * vol_score
        + 0.15 * rsi_score
        + 0.15 * adx_score
        + 0.15 * foreign_score
    )

    ut_boost = 1.0
    ut_boost += signals["ut_bullish"].astype(float) * 0.15
    ut_boost += signals.get("ut_fresh_buy", pd.Series(0, index=signals.index)).astype(float) * 0.10

    signals["confidence"] = np.round(confidence_raw * ut_boost, 1)
    signals["vol_spike_pct"] = (vol_ratio_signal - 1) * 100

    _cond_labels = {
        "cond_vol_spike": "Volume Spike",
        "cond_ma_squeeze": "MA Squeeze",
        "cond_bb_squeeze": "BB Squeeze",
        "cond_sideways": "Sideways",
    }
    signals["trigger"] = signals.apply(
        lambda r: " + ".join(lbl for col, lbl in _cond_labels.items() if r[col]) or "Lorentzian Filter",
        axis=1,
    )
    signals["ut_trend"] = signals["ut_position"].map({1: "UP", -1: "DOWN"}).fillna("?")
    signals["ut_cross"] = signals.get("ut_fresh_buy", False)
    signals["tp_target"] = signals["tp_target"].fillna(0).round(0).astype(int)
    # SL dinamis ATR-based (atr_sl = close - 1.5*ATR); fallback -5% jika ATR NaN
    signals["sl_target"] = (
        signals["atr_sl"]
        .fillna(signals["close_price"] * 0.95)
        .fillna(0)
        .round(0)
        .astype(int)
    )
    signals["buy_zone"] = (
        signals["buy_zone_low"].fillna(0).round(0).astype(int).astype(str)
        + "–"
        + signals["buy_zone_high"].fillna(0).round(0).astype(int).astype(str)
    )

    return signals.sort_values("confidence", ascending=False)
