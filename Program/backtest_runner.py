"""
backtest_runner.py — Backtesting untuk Accumulation Detector
Mensimulasikan strategi dari quant_screener.py secara point-in-time
periode 1 Jul 2025 – 31 Des 2025.

Menghasilkan laporan backtest_report.txt yang diupload sebagai artifact
di GitHub Actions.
"""

import os
import sys
import pandas as pd
import numpy as np
from supabase import create_client
from datetime import date
import config as cfg

# ======================================================================
# KONFIGURASI BACKTEST
# ======================================================================
BACKTEST_START = date(2025, 7, 1)
BACKTEST_END = date(2025, 12, 31)
FETCH_START = date(2024, 10, 1)       # ~200 hari bursa sebelum Jul 2025 — cukup untuk SMA200
INITIAL_CAPITAL = 100_000_000        # Rp 100 juta
MAX_POSITIONS = 5                    # Maksimum saham di-hold bersamaan
SL_PCT = 0.02                        # Stop loss 2% (fallback)
LOT_SIZE = 100                       # 1 lot = 100 lembar
TRANSACTION_COST = 0.002             # 0.2% biaya transaksi

REQUIRED_COLS = ["ma10", "ma20", "ma50", "std20", "avg_vol_20", "avg_vol_20_prev"]

# ======================================================================
# KONEKSI SUPABASE
# ======================================================================
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
if not url or not key:
    sys.exit("Missing Supabase environment variables (SUPABASE_URL, SUPABASE_KEY)")

supabase = create_client(url, key)


# ======================================================================
# 1. FETCH DATA HISTORIS
# ======================================================================
def fetch_data():
    """
    Mengunduh data IHSG EOD dan Index EOD dari Supabase
    untuk periode FETCH_START sampai BACKTEST_END.
    """
    print(f"[FETCH] Mengunduh data dari {FETCH_START} ke {BACKTEST_END} ...")

    # --- Index EOD (IHSG COMPOSITE) ---
    all_idx = []
    offset = 0
    while True:
        batch = (
            supabase.table("index_eod")
            .select("trade_date,close")
            .eq("index_code", "COMPOSITE")
            .gte("trade_date", FETCH_START.isoformat())
            .lte("trade_date", BACKTEST_END.isoformat())
            .order("trade_date")
            .range(offset, offset + 999)
            .execute()
        )
        if not batch.data:
            break
        all_idx.extend(batch.data)
        offset += 1000

    idx_df = pd.DataFrame(all_idx) if all_idx else pd.DataFrame()
    if not idx_df.empty:
        idx_df["trade_date"] = pd.to_datetime(idx_df["trade_date"]).dt.date
        idx_df["close"] = pd.to_numeric(idx_df["close"], errors="coerce")
        idx_df = idx_df.sort_values("trade_date").reset_index(drop=True)
        idx_df["ma50"] = idx_df["close"].rolling(50, min_periods=50).mean()
        print(f"[FETCH] {len(idx_df)} baris data IHSG index")
    else:
        print("[FETCH] WARNING: Tidak ada data index_eod")

    # --- IHSG EOD (per stock code agar query tidak timeout) ---
    # Ambil daftar stock_code dari hari bursa terakhir di rentang
    print("[FETCH] Mengambil daftar stock_code ...")
    # Cari tanggal dengan data (hari bursa aktif)
    latest_day_res = (
        supabase.table("ihsg_eod")
        .select("trade_date")
        .lte("trade_date", BACKTEST_END.isoformat())
        .gte("trade_date", BACKTEST_START.isoformat())
        .order("trade_date", desc=True)
        .limit(1)
        .execute()
    )
    code_date = latest_day_res.data[0]["trade_date"] if latest_day_res.data else BACKTEST_END.isoformat()

    codes_batch = (
        supabase.table("ihsg_eod")
        .select("stock_code")
        .eq("trade_date", code_date)
        .limit(2000)
        .execute()
    )
    unique_codes = sorted(set(row["stock_code"] for row in (codes_batch.data or [])))
    if not unique_codes:
        # Fallback: coba BACKTEST_START
        codes_batch = (
            supabase.table("ihsg_eod")
            .select("stock_code")
            .eq("trade_date", BACKTEST_START.isoformat())
            .limit(2000)
            .execute()
        )
        unique_codes = sorted(set(row["stock_code"] for row in (codes_batch.data or [])))
    print(f"[FETCH] {len(unique_codes)} ticker unik ditemukan dari tanggal {code_date}")

    # Fetch data per batch stock_code (query kecil, tidak timeout)
    all_stocks = []
    batch_size = 50
    for i in range(0, len(unique_codes), batch_size):
        batch_codes = unique_codes[i : i + batch_size]
        offset = 0
        while True:
            batch = (
                supabase.table("ihsg_eod")
                .select("stock_code,trade_date,open_price,close_price,high,low,previous,volume,foreign_buy,foreign_sell")
                .in_("stock_code", batch_codes)
                .gte("trade_date", FETCH_START.isoformat())
                .lte("trade_date", BACKTEST_END.isoformat())
                .order("trade_date")
                .range(offset, offset + 999)
                .execute()
            )
            if not batch.data:
                break
            all_stocks.extend(batch.data)
            offset += 1000

        if (i + batch_size) % 200 == 0:
            print(f"[FETCH] {min(i+batch_size, len(unique_codes))}/{len(unique_codes)} ticker selesai ...")

    if not all_stocks:
        sys.exit("[ERROR] Tidak ada data IHSG EOD dari Supabase.")

    df = pd.DataFrame(all_stocks)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df = df.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)

    for col in ["open_price", "close_price", "high", "low", "volume", "previous", "foreign_buy", "foreign_sell"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    print(f"[FETCH] {len(df)} baris data saham, {df['stock_code'].nunique()} ticker")
    return df, idx_df


# ======================================================================
# 2. FEATURE ENGINEERING (sama persis dengan quant_screener.py)
# ======================================================================
def add_features(group: pd.DataFrame) -> pd.DataFrame:
    """Menambahkan indikator teknikal secara vektorisasi per grup saham."""
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

    # ---- UT Bot ATR trailing stop ----
    group["tr"] = (group["close_price"] - group["previous"]).abs()
    group["atr"] = group["tr"].rolling(
        cfg.UT_ATR_PERIOD, min_periods=cfg.UT_ATR_PERIOD
    ).mean()
    n_loss = cfg.UT_MULTIPLIER * group["atr"]

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
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(cfg.RSI_PERIOD, min_periods=cfg.RSI_PERIOD).mean()
    avg_loss = loss.rolling(cfg.RSI_PERIOD, min_periods=cfg.RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    group["rsi"] = 100 - (100 / (1 + rs))

    # ---- ADX (Lorentzian-inspired) ----
    # True Range
    group["tr_hl"] = (group["high"] - group["low"]).abs()
    group["tr_hc"] = (group["high"] - group["previous"]).abs()
    group["tr_lc"] = (group["low"] - group["previous"]).abs()
    group["tr_atr"] = group[["tr_hl", "tr_hc", "tr_lc"]].max(axis=1)
    group["atr_14"] = group["tr_atr"].rolling(cfg.ADX_PERIOD, min_periods=cfg.ADX_PERIOD).mean()

    # +DM and -DM
    group["up_move"] = group["high"] - group["high"].shift(1)
    group["down_move"] = group["low"].shift(1) - group["low"]
    group["plus_dm"] = np.where(
        (group["up_move"] > group["down_move"]) & (group["up_move"] > 0),
        group["up_move"],
        0.0
    )
    group["minus_dm"] = np.where(
        (group["down_move"] > group["up_move"]) & (group["down_move"] > 0),
        group["down_move"],
        0.0
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
    group["swing_high"] = (
        group["close_price"].rolling(p, min_periods=p).max().shift(p // 2)
    )
    group["swing_low"] = (
        group["close_price"].rolling(p, min_periods=p).min().shift(p // 2)
    )

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

    # Harga open keesokan hari (tidak dipakai — entry pakai close)
    # group["next_open"] = group["open_price"].shift(-1)

    # ---- Foreign flow (Bandamologi) ----
    group["foreign_buy"] = pd.to_numeric(group["foreign_buy"], errors="coerce").fillna(0)
    group["foreign_sell"] = pd.to_numeric(group["foreign_sell"], errors="coerce").fillna(0)
    group["foreign_net"] = group["foreign_buy"] - group["foreign_sell"]
    # Net ratio terhadap volume (0-1), positif = asing beli
    group["foreign_net_ratio"] = group["foreign_net"] / group["volume"].replace(0, np.nan)
    group["foreign_net_ratio"] = group["foreign_net_ratio"].clip(-1, 1).fillna(0)
    # Rata-rata foreign net ratio 5 hari
    group["foreign_net_ma"] = (
        group["foreign_net_ratio"].rolling(cfg.FOREIGN_LOOKBACK, min_periods=1).mean()
    )

    return group


# ======================================================================
# 3. MARKET REGIME (IHSG) PER TANGGAL
# ======================================================================
def get_regime(
    idx_df: pd.DataFrame, trade_date: date
) -> str:
    """
    Mengklasifikasikan regime IHSG pada trade_date tertentu.
    Returns: "BULLISH", "NEUTRAL", atau "BEARISH".
    """
    sub = idx_df[idx_df["trade_date"] <= trade_date].copy()
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


def get_regime_params(regime: str):
    """Mengembalikan parameter trading yang sesuai dengan regime."""
    if regime == "BULLISH":
        return {
            "confidence_min": cfg.CONF_BULLISH,
            "max_positions": cfg.MAX_POS_BULLISH,
            "sl_mult": cfg.SL_BULLISH,
            "tp_mult": cfg.TP_BULLISH,
        }
    elif regime == "BEARISH":
        return {
            "confidence_min": cfg.CONF_BEARISH,
            "max_positions": cfg.MAX_POS_BEARISH,
            "sl_mult": cfg.SL_BEARISH,
            "tp_mult": cfg.TP_BEARISH,
        }
    else:  # NEUTRAL
        return {
            "confidence_min": cfg.CONF_NEUTRAL,
            "max_positions": cfg.MAX_POS_NEUTRAL,
            "sl_mult": cfg.SL_NEUTRAL,
            "tp_mult": cfg.TP_NEUTRAL,
        }


# ======================================================================
# 4. SCREENER LOGIC PER HARI
# ======================================================================
def get_signals(
    df_day: pd.DataFrame, confidence_min: float, min_conditions: int = 4,
) -> pd.DataFrame:
    """
    Menjalankan logika screener pada data satu hari tertentu.
    Enhancement 4: jumlah kondisi yang dibutuhkan tergantung regime.
    """
    if df_day.empty:
        return pd.DataFrame()

    latest = df_day.copy()
    latest = latest.dropna(subset=REQUIRED_COLS)

    if latest.empty:
        return pd.DataFrame()

    # --- Red-flag filters ---
    sleeping = (
        (latest["close_price"] <= cfg.SLEEPING_PRICE)
        & (latest["rolling_min_close"] == cfg.SLEEPING_PRICE)
        & (latest["rolling_max_close"] == cfg.SLEEPING_PRICE)
    )
    illiquid = latest["avg_vol_20"] < cfg.MIN_LIQUIDITY_VOL
    red_flagged = sleeping | illiquid
    candidates = latest[~red_flagged].copy()

    if candidates.empty:
        return pd.DataFrame()

    # --- 4 kondisi sinyal ---
    # MA Squeeze
    ma_spread = (
        candidates[["ma10", "ma20", "ma50"]].max(axis=1)
        - candidates[["ma10", "ma20", "ma50"]].min(axis=1)
    ) / candidates["ma50"] * 100
    cond1 = ma_spread < cfg.MA_SQUEEZE_THRESHOLD

    # BB Squeeze
    cond2 = candidates["bb_bandwidth"] < cfg.BB_SQUEEZE_THRESHOLD

    # Volume Anomaly
    vol_ratio = candidates["volume"] / candidates["avg_vol_20_prev"]
    cond3 = vol_ratio > cfg.VOL_SPIKE_MULT

    # Price Constraint
    flat_price = candidates["daily_return"].abs() <= cfg.FLAT_RANGE
    price_not_overbought = candidates["close_price"] < candidates["bb_upper"]
    cond4 = flat_price & price_not_overbought

    # Enhancement 4: jumlah kondisi minimal tergantung regime
    conditions_met = cond1.astype(int) + cond2.astype(int) + cond3.astype(int) + cond4.astype(int)
    signal_mask = conditions_met >= min_conditions

    # --- Lorentzian-inspired filters (mandatory always) ---
    rsi_ok = candidates["rsi"].fillna(50) > cfg.RSI_OVERSOLD
    adx_ok = candidates["adx"].fillna(25) > cfg.ADX_THRESHOLD
    sma200_ok = candidates["sma200"].isna() | (candidates["close_price"] > candidates["sma200"])
    foreign_ok = candidates["foreign_net_ma"].fillna(0) >= cfg.FOREIGN_NET_MIN

    # Gabung semua filter wajib
    signal_mask = signal_mask & rsi_ok & adx_ok & sma200_ok & foreign_ok

    # --- UT Bot overlay ---
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

    squeeze_ma_score = np.clip(
        100 * (1 - ma_spread_signal / cfg.SCORE_MA_SPREAD_MAX), 0, 100
    )
    squeeze_bb_score = np.clip(
        100 * (1 - bb_width / cfg.SCORE_BB_WIDTH_MAX), 0, 100
    )
    vol_score = np.clip(
        100 * (vol_ratio_signal - 1) / (cfg.SCORE_VOL_MULT_MAX - 1), 0, 100
    )

    # RSI score: 100 jika RSI ~50 (netral), turun jika mendekati 30 atau 70
    rsi_val = signals["rsi"]
    rsi_score = np.clip(100 - 5 * (rsi_val - 50).abs(), 0, 100)

    # ADX score: 100 jika ADX tinggi (trend kuat)
    adx_val = signals["adx"]
    adx_score = np.clip(100 * (adx_val - cfg.ADX_THRESHOLD) / 30, 0, 100)

    # Foreign flow score: 100 jika asing banyak beli, 0 jika asing jual
    foreign_ratio = signals["foreign_net_ma"].fillna(0)
    foreign_score = np.clip(100 * foreign_ratio, 0, 100)

    # Composite: squeeze 10%, BB 10%, volume 35%, RSI 15%, ADX 15%, foreign 15%
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
    ut_boost += signals.get("ut_fresh_buy", pd.Series(0, index=signals.index)).astype(
        float
    ) * 0.10

    signals["confidence"] = np.round(
        confidence_raw * ut_boost, 1
    )

    # Kolom tambahan untuk backtest
    signals["tp_target"] = signals["tp_target"].fillna(0).round(0).astype(int)

    return signals[["stock_code", "confidence", "tp_target"]]


# ======================================================================
# 5. BACKTEST UTAMA
# ======================================================================
def run_backtest():
    print("=" * 70)
    print("BACKTEST ACCUMULATION DETECTOR")
    print(f"Periode: {BACKTEST_START} – {BACKTEST_END}")
    print(f"Modal Awal: Rp {INITIAL_CAPITAL:,.0f}")
    print(f"Max Posisi: {MAX_POSITIONS}")
    print(f"Stop Loss: {SL_PCT*100:.0f}%")
    print(f"Time-based Exit: {cfg.MAX_HOLD_DAYS} hari")
    print("=" * 70)

    # --- 5a. Fetch & feature engineering ---
    df, idx_df = fetch_data()

    print("[FEATURE] Menghitung indikator teknikal ...")
    # Loop per stock_code — dijamin stock_code tidak hilang, compatible semua versi pandas
    stock_codes = df["stock_code"].unique()
    frames = []
    for sc in stock_codes:
        mask = df["stock_code"] == sc
        frames.append(add_features(df[mask].copy()))
    df = pd.concat(frames, ignore_index=True)

    # Buat lookup cepat: (stock_code, trade_date) -> harga
    close_lookup = df.set_index(["stock_code", "trade_date"])["close_price"]

    # --- 5b. Daftar hari bursa dalam periode backtest ---
    trading_days = sorted(
        d
        for d in df[df["trade_date"] >= BACKTEST_START]["trade_date"].unique()
        if d <= BACKTEST_END
    )
    print(f"[BACKTEST] {len(trading_days)} hari bursa dalam periode pengujian\n")

    # --- 5c. State backtest ---
    positions = []       # List[dict]: posisi terbuka
    cash = float(INITIAL_CAPITAL)
    trades = []          # List[dict]: riwayat transaksi
    equity_curve = []    # List[dict]: nilai portofolio per hari

    # --- 5d. Loop utama ---
    for day_idx, trade_date in enumerate(trading_days):
        # Tentukan regime IHSG hari ini (dipakai di exit dan entry)
        regime = get_regime(idx_df, trade_date)
        regime_params = get_regime_params(regime)

        # ---- Cek exit untuk posisi terbuka ----
        remaining_positions = []

        for pos in positions:
            try:
                close_price = close_lookup.loc[(pos["stock_code"], trade_date)]
                if hasattr(close_price, 'iloc'):
                    close_price = close_price.iloc[0]
            except KeyError:
                # Saham tidak aktif di hari ini, hold
                pos["hold_days"] += 1
                remaining_positions.append(pos)
                continue

            if pd.isna(close_price):
                pos["hold_days"] += 1
                remaining_positions.append(pos)
                continue

            exit_reason = None
            exit_price = None
            sell_lots = 0

            # Update highest price untuk trailing stop
            if not pd.isna(close_price) and close_price > pos["highest_price"]:
                pos["highest_price"] = close_price

            # Cek TP1 (partial): ambil 40% profit
            if not pos["tp1_hit"] and close_price >= pos["tp1_price"]:
                exit_reason = "TP1"
                exit_price = pos["tp1_price"]
                sell_lots = max(1, int(pos["remaining_lots"] * cfg.TP1_PCT))
            # Cek Trailing Stop (Enhancement 1): setelah TP1 hit
            elif pos["tp1_hit"]:
                trailing_stop = pos["highest_price"] * (1 - cfg.TRAILING_PCT)
                if close_price <= trailing_stop:
                    exit_reason = "TRAILING"
                    exit_price = close_price
                    sell_lots = pos["remaining_lots"]
            # Cek Stop Loss (sebelum TP1)
            elif close_price <= pos["sl_price"]:
                exit_reason = "SL"
                exit_price = pos["sl_price"]
                sell_lots = pos["remaining_lots"]
            # Cek time-based exit (Enhancement 3)
            elif pos["hold_days"] >= cfg.MAX_HOLD_DAYS - 1:
                # Hitung PnL%
                pnl_check = (close_price / pos["avg_price"] - 1) * 100
                # Enhancement 3: skip TIME exit jika profitable di bull market
                if pnl_check > 0 and regime == "BULLISH":
                    pass  # biarkan trailing stop yang handle
                else:
                    exit_reason = "TIME"
                    exit_price = close_price
                    sell_lots = pos["remaining_lots"]

            if exit_reason is not None and sell_lots > 0:
                sell_qty = sell_lots * LOT_SIZE
                # Hitung biaya dan PnL untuk lot yang dijual
                sell_cost_basis = pos["cost_basis"] * (sell_lots / pos["total_lots"])
                gross_return = exit_price * sell_qty
                cost = gross_return * TRANSACTION_COST
                net_return = gross_return - cost
                pnl = net_return - sell_cost_basis
                pnl_pct = (exit_price / pos["avg_price"] - 1) * 100

                cash += net_return
                pos["remaining_lots"] -= sell_lots

                trades.append({
                    "stock_code": pos["stock_code"],
                    "entry_date": pos["entry_date"],
                    "exit_date": trade_date,
                    "entry_price": pos["avg_price"],
                    "exit_price": exit_price,
                    "quantity": sell_qty,
                    "lots": sell_lots,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_reason": exit_reason,
                })

                if exit_reason == "TP1":
                    # TP1: sisa posisi, SL pindah ke breakeven
                    pos["tp1_hit"] = True
                    pos["sl_price"] = pos["avg_price"]  # SL ke breakeven
                    pos["cost_basis"] = pos["cost_basis"] - sell_cost_basis
                    pos["total_lots"] = pos["remaining_lots"]  # update total setelah partial exit
                    remaining_positions.append(pos)

            if exit_reason is None or sell_lots == 0:
                pos["hold_days"] += 1
                remaining_positions.append(pos)

        positions = remaining_positions

        # ---- Dapatkan sinyal entry ----
        day_data = df[df["trade_date"] == trade_date].copy()

        # Enhancement 4: jumlah kondisi minimal tergantung regime
        if regime == "BULLISH":
            min_cond = cfg.BULLISH_MIN_CONDITIONS
        elif regime == "BEARISH":
            min_cond = cfg.BEARISH_MIN_CONDITIONS
        else:
            min_cond = cfg.NEUTRAL_MIN_CONDITIONS

        signals = get_signals(day_data, regime_params["confidence_min"], min_cond)

        if not signals.empty and cash > 0:
            # Ambil sinyal terbaik, urut dari confidence tertinggi
            top_signals = signals.nlargest(len(signals), "confidence")

            for _, sig in top_signals.iterrows():
                stock_code = sig["stock_code"]

                # Cek duplikasi posisi
                if any(p["stock_code"] == stock_code for p in positions):
                    continue

                # Kalau sudah mentok max posisi sesuai regime, berhenti
                if len(positions) >= regime_params["max_positions"]:
                    break

                # Entry pakai close_price hari sinyal
                try:
                    entry_price = close_lookup.loc[
                        (stock_code, trade_date)
                    ]
                    entry_price = entry_price.iloc[0] if hasattr(entry_price, 'iloc') else entry_price
                except KeyError:
                    continue

                if pd.isna(entry_price) or entry_price <= 0:
                    continue

                # ATR
                day_row = day_data[day_data["stock_code"] == stock_code]
                if day_row.empty:
                    continue
                atr_val = day_row["atr_14"].iloc[0]
                if pd.isna(atr_val) or atr_val <= 0:
                    tp1_price = entry_price * 1.02
                    sl_price = entry_price * (1 - SL_PCT)
                else:
                    tp1_price = entry_price + atr_val * cfg.TP1_MULT
                    sl_price = entry_price - atr_val * regime_params["sl_mult"]
                    tp1_price = max(tp1_price, entry_price * 1.01)
                    sl_price = min(sl_price, entry_price * 0.99)

                # Enhancement 2: dynamic position sizing per regime
                if regime == "BULLISH":
                    alloc_pct = cfg.ALLOC_BULLISH
                elif regime == "BEARISH":
                    alloc_pct = cfg.ALLOC_BEARISH
                else:
                    alloc_pct = cfg.ALLOC_NEUTRAL

                # Organic: confidence-based dalam batas regime
                confidence = float(sig["confidence"])
                adj_pct = alloc_pct * (confidence / 70)  # confidence 70 → full alloc
                adj_pct = min(adj_pct, alloc_pct)
                adj_pct = max(adj_pct, 0.05)

                alloc = cash * adj_pct

                # Hitung lot
                cost_per_share = entry_price * (1 + TRANSACTION_COST)
                max_shares = int(alloc / cost_per_share)
                lots = max_shares // LOT_SIZE
                if lots < cfg.ALLOC_MIN_LOTS:
                    continue

                quantity = lots * LOT_SIZE
                cost_basis = quantity * cost_per_share
                if cost_basis > cash:
                    lots = int(cash / cost_per_share) // LOT_SIZE
                    if lots < 1:
                        continue
                    quantity = lots * LOT_SIZE
                    cost_basis = quantity * cost_per_share

                cash -= cost_basis

                # Enhancement 1: simpan highest_price untuk trailing stop
                positions.append({
                    "stock_code": stock_code,
                    "entry_date": trade_date,
                    "avg_price": entry_price,
                    "tp1_price": tp1_price,
                    "sl_price": sl_price,
                    "total_lots": lots,
                    "remaining_lots": lots,
                    "quantity": quantity,
                    "cost_basis": cost_basis,
                    "hold_days": 0,
                    "tp1_hit": False,
                    "highest_price": entry_price,  # trailing stop tracker
                })

        # ---- Catat equity curve ----
        pos_market_value = 0.0
        for pos in positions:
            try:
                cp = close_lookup.loc[(pos["stock_code"], trade_date)]
                if hasattr(cp, 'iloc'):
                    cp = cp.iloc[0]
                if not pd.isna(cp):
                    pos_market_value += cp * pos["remaining_lots"] * LOT_SIZE
                else:
                    pos_market_value += pos["avg_price"] * pos["remaining_lots"] * LOT_SIZE
            except KeyError:
                pos_market_value += pos["avg_price"] * pos["remaining_lots"] * LOT_SIZE

        portfolio_value = cash + pos_market_value
        equity_curve.append({
            "date": trade_date,
            "cash": cash,
            "market_value": pos_market_value,
            "total": portfolio_value,
        })

    # --- 5e. Tutup semua posisi tersisa di akhir periode ---
    final_date = BACKTEST_END
    for pos in positions:
        if pos["remaining_lots"] <= 0:
            continue
        try:
            exit_price = close_lookup.loc[(pos["stock_code"], final_date)]
            if hasattr(exit_price, 'iloc'):
                exit_price = exit_price.iloc[0]
            if pd.isna(exit_price):
                exit_price = pos["avg_price"]
        except KeyError:
            exit_price = pos["avg_price"]

        exit_qty = pos["remaining_lots"] * LOT_SIZE
        exit_cost_basis = pos["cost_basis"] * (pos["remaining_lots"] / pos["total_lots"])
        gross_return = exit_price * exit_qty
        cost = gross_return * TRANSACTION_COST
        net_return = gross_return - cost
        pnl = net_return - exit_cost_basis
        pnl_pct = (exit_price / pos["avg_price"] - 1) * 100

        cash += net_return

        trades.append({
            "stock_code": pos["stock_code"],
            "entry_date": pos["entry_date"],
            "exit_date": final_date,
            "entry_price": pos["avg_price"],
            "exit_price": exit_price,
            "quantity": exit_qty,
            "lots": pos["remaining_lots"],
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "exit_reason": "END",
        })

    positions = []

    # ==================================================================
    # 6. HITUNG METRIK
    # ==================================================================
    total_trades = len(trades)
    if total_trades == 0:
        print("\n[BACKTEST] Tidak ada trade yang terjadi.")
        _write_empty_report()
        return

    df_trades = pd.DataFrame(trades)
    df_equity = pd.DataFrame(equity_curve)

    winning_trades = df_trades[df_trades["pnl"] > 0]
    losing_trades = df_trades[df_trades["pnl"] <= 0]
    win_count = len(winning_trades)
    loss_count = len(losing_trades)
    win_rate = win_count / total_trades * 100 if total_trades > 0 else 0.0

    total_profit = winning_trades["pnl"].sum() if not winning_trades.empty else 0.0
    total_loss = losing_trades["pnl"].sum() if not losing_trades.empty else 0.0
    net_profit = total_profit + total_loss
    final_capital = cash

    profit_factor = abs(total_profit / total_loss) if total_loss != 0 else float("inf")

    avg_win = winning_trades["pnl_pct"].mean() if not winning_trades.empty else 0.0
    avg_loss = losing_trades["pnl_pct"].mean() if not losing_trades.empty else 0.0

    # Max drawdown
    df_equity["peak"] = df_equity["total"].cummax()
    df_equity["drawdown"] = (df_equity["total"] - df_equity["peak"]) / df_equity["peak"] * 100
    max_drawdown = df_equity["drawdown"].min()

    # Return
    total_return_pct = (final_capital / INITIAL_CAPITAL - 1) * 100

    # ==================================================================
    # 7. TULIS LAPORAN
    # ==================================================================
    report_lines = []
    _w = report_lines.append

    _w("=" * 72)
    _w("                BACKTEST REPORT — ACCUMULATION DETECTOR")
    _w("=" * 72)
    _w("")
    _w(f"  Periode Pengujian    : {BACKTEST_START} – {BACKTEST_END}")
    _w(f"  Modal Awal           : Rp {INITIAL_CAPITAL:>12,.0f}")
    _w(f"  Modal Akhir          : Rp {final_capital:>12,.0f}")
    _w(f"  Net Profit           : Rp {net_profit:>12,.0f}  ({total_return_pct:+.2f}%)")
    _w(f"  Total Trade          : {total_trades}")
    _w(f"  Win Rate             : {win_rate:.1f}% ({win_count} menang, {loss_count} kalah)")
    _w(f"  Profit Factor        : {profit_factor:.2f}")
    _w(f"  Max Drawdown         : {max_drawdown:.2f}%")
    _w(f"  Rata-rata Win        : {avg_win:+.2f}%")
    _w(f"  Rata-rata Loss       : {avg_loss:+.2f}%")
    _w(f"  Biaya Transaksi      : {TRANSACTION_COST*100:.1f}% per transaksi")
    _w("")

    # Breakdown by exit reason
    _w("--- Breakdown by Exit Reason ---")
    for reason in ["TP1", "TRAILING", "SL", "TIME", "END"]:
        subset = df_trades[df_trades["exit_reason"] == reason]
        if not subset.empty:
            r_win = (subset["pnl"] > 0).sum()
            r_total = len(subset)
            r_pnl = subset["pnl"].sum()
            _w(f"  {reason:6s}: {r_total:2d} trade ({r_win:2d} win), "
               f"total PnL Rp {r_pnl:>10,.0f}")
    _w("")

    # Daftar trade (rata kiri)
    _w("--- Daftar Transaksi ---")
    _w(f"{'No':<4} {'Ticker':<7} {'Entry':<12} {'Exit':<12} {'Entry':<8} {'Exit':<8} {'Lot':<5} {'PnL':<14} {'PnL%':<8} {'Exit'}")
    _w("-" * 88)

    for i, (_, tr) in enumerate(df_trades.iterrows(), 1):
        _w(
            f"{i:<4} {tr['stock_code']:<7} {str(tr['entry_date']):<12} "
            f"{str(tr['exit_date']):<12} {tr['entry_price']:<8.0f} "
            f"{tr['exit_price']:<8.0f} {tr['lots']:<5} "
            f"{tr['pnl']:<+14,.0f} {tr['pnl_pct']:<+7.2f}% {tr['exit_reason']}"
        )

    _w("")
    _w("--- Equity Curve ---")
    _w(f"{'Tanggal':<12} {'Portofolio':<18} {'Drawdown':<10} {'Regime':<10}")
    _w("-" * 54)

    step = max(1, len(df_equity) // 6)
    for idx in range(0, len(df_equity), step):
        row = df_equity.iloc[idx]
        reg = get_regime(idx_df, row["date"])
        _w(
            f"{str(row['date']):<12} Rp {row['total']:<14,.0f} "
            f"{row['drawdown']:<+9.2f}% {reg:<10}"
        )
    # Pastikan baris terakhir selalu tampil
    if (len(df_equity) - 1) % step != 0:
        last_eq = df_equity.iloc[-1]
        last_reg = get_regime(idx_df, last_eq["date"])
        _w(
            f"{str(last_eq['date']):<12} Rp {last_eq['total']:<14,.0f} "
            f"{last_eq['drawdown']:<+9.2f}% {last_reg:<10}"
        )

    # Ringkasan portfolio
    first_val = df_equity.iloc[0]["total"]
    last_val = df_equity.iloc[-1]["total"]
    best_val = df_equity["total"].max()
    worst_val = df_equity["total"].min()
    _w("")
    _w(f"  Portfolio Awal : Rp {first_val:>12,.0f}")
    _w(f"  Portfolio Akhir: Rp {last_val:>12,.0f}")
    _w(f"  Nilai Tertinggi: Rp {best_val:>12,.0f}")
    _w(f"  Nilai Terendah : Rp {worst_val:>12,.0f}")
    _w(f"  Max Drawdown   : {max_drawdown:.2f}%")
    _w(f"  Biaya Transaksi: {TRANSACTION_COST*100:.1f}% per transaksi")

    # Ringkasan strategi
    _w("")
    _w("--- Ringkasan Strategi ---")
    # Hitung distribusi regime sepanjang periode
    regime_counts = {"BULLISH": 0, "NEUTRAL": 0, "BEARISH": 0}
    for _, row in df_equity.iterrows():
        reg = get_regime(idx_df, row["date"])
        regime_counts[reg] = regime_counts.get(reg, 0) + 1
    total_days = sum(regime_counts.values())
    if total_days > 0:
        parts = []
        for reg in ["BULLISH", "NEUTRAL", "BEARISH"]:
            pct = regime_counts[reg] / total_days * 100
            parts.append(f"{pct:.0f}% {reg}")
        _w(f"  - Regime IHSG: {', '.join(parts)}")
    _w(f"  - Entry: MA squeeze + BB squeeze + volume spike + foreign flow (Bandamologi)")
    _w(f"  - Bullish: 2/4 kondisi, 6 posisi, max 25% cash, trailing stop 8%")
    _w(f"  - Neutral: 4/4 kondisi, 3 posisi, max 20% cash")
    _w(f"  - Bearish: 4/4 kondisi, 2 posisi, max 10% cash, TIME exit berjalan")
    _w(f"  - Exit: TP1 (40% partial) -> trailing stop 8% -> SL ke breakeven")
    _w(f"  - Hold max {cfg.MAX_HOLD_DAYS} hari, TP/SL menyesuaikan regime IHSG")

    _w("")
    _w("=" * 72)
    _w(f"Laporan digenerate oleh backtest_runner.py — {date.today().isoformat()}")
    _w("=" * 72)

    report = "\n".join(report_lines)
    print(report)

    # Simpan ke file
    report_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "backtest_report.txt"
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n[OK] Laporan tersimpan di: {report_path}")
    return report_path


def _write_empty_report():
    """Menulis laporan kosong jika tidak ada trade."""
    lines = [
        "=" * 72,
        "         BACKTEST REPORT — ACCUMULATION DETECTOR",
        "=" * 72,
        "",
        f"  Periode Pengujian: {BACKTEST_START} – {BACKTEST_END}",
        f"  Modal Awal       : Rp {INITIAL_CAPITAL:>12,.0f}",
        f"  Modal Akhir      : Rp {INITIAL_CAPITAL:>12,.0f}",
        "  Total Trade      : 0",
        "",
        "  TIDAK ADA SINYAL ENTRY SELAMA PERIODE BACKTEST.",
        "",
        "=" * 72,
    ]
    report = "\n".join(lines)
    print(report)
    report_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "backtest_report.txt"
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n[OK] Laporan kosong tersimpan di: {report_path}")


# ======================================================================
# ENTRY POINT
# ======================================================================
if __name__ == "__main__":
    run_backtest()