"""
Quant Screener: Accumulation Detector
Runs daily on GitHub Actions with Supabase PostgreSQL.

Sinyal dihasilkan oleh strategy.py — modul yang sama persis dipakai
backtest.py, supaya hasil live selalu konsisten dengan backtest.
"""

import os
import sys
import time
import pandas as pd
from supabase import create_client, Client
from datetime import date, timedelta

import config as cfg
from strategy import add_features, get_regime, get_regime_params, get_signals
from notifier import send_screener_results


def _retry(fn, attempts=4, base_delay=2.0):
    """anon role punya statement_timeout=3s; query ke ihsg_eod (1.3jt baris)
    bisa melewati itu saat DB sedang ramai. Retry lebih murah daripada
    menaikkan timeout role secara global."""
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (i + 1))

# ----------------------------------------------------------------------
# Supabase connection
# ----------------------------------------------------------------------
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
if not url or not key:
    sys.exit("Missing Supabase environment variables")

supabase: Client = create_client(url, key)

# ----------------------------------------------------------------------
# 1. Determine latest date & fetch IHSG index history
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

    if not idx_data:
        sys.exit("No IHSG index data retrieved")

    idx_df = pd.DataFrame(idx_data)
    idx_df["trade_date"] = pd.to_datetime(idx_df["trade_date"]).dt.date
    idx_df = idx_df.sort_values("trade_date").reset_index(drop=True)
    idx_df["close"] = pd.to_numeric(idx_df["close"], errors="coerce")
    idx_df["ma50"] = idx_df["close"].rolling(50, min_periods=50).mean()

    market_label = get_regime(idx_df, latest_date)
    regime_params = get_regime_params(market_label)
    latest_idx = idx_df.iloc[-1]
    print(f"IHSG Market Regime: {market_label} "
          f"(Close={latest_idx['close']:,.2f}, MA50={latest_idx.get('ma50', float('nan')):,.2f})")

except Exception as e:
    sys.exit(f"Supabase index query failed: {e}")

# ----------------------------------------------------------------------
# 2. Fetch stock historical data
# ----------------------------------------------------------------------
# Ambil per-batch stock_code (bukan satu query date-range besar) — tabel
# ihsg_eod di-index per (stock_code, trade_date), jadi query date-range
# murni di 280 hari x ~1000 saham gampang kena statement timeout.
try:
    codes_res = _retry(lambda: supabase.table("ihsg_eod")
        .select("stock_code")
        .eq("trade_date", latest_date.isoformat())
        .limit(2000)
        .execute())
    stock_codes = sorted(set(row["stock_code"] for row in (codes_res.data or [])))
    if not stock_codes:
        sys.exit("No stock_code found on latest trading day")

    all_data = []
    batch_size = 50
    for i in range(0, len(stock_codes), batch_size):
        chunk = stock_codes[i:i + batch_size]
        offset = 0
        while True:
            batch = supabase.table("ihsg_eod") \
                .select("stock_code,trade_date,close_price,high,low,volume,previous,foreign_buy,foreign_sell") \
                .in_("stock_code", chunk) \
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
for col in ["close_price", "high", "low", "volume", "previous", "foreign_buy", "foreign_sell"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# ----------------------------------------------------------------------
# 4. Feature engineering + sinyal (identik dengan backtest.py)
# ----------------------------------------------------------------------
# Loop per stock_code (bukan groupby-apply) — kompatibel semua versi pandas
frames = [add_features(df[df["stock_code"] == sc].copy()) for sc in df["stock_code"].unique()]
df = pd.concat(frames, ignore_index=True)

day_data = df[df["trade_date"] == latest_date].copy()
print(f"Stocks on latest day: {len(day_data)}")

signals = get_signals(day_data, regime_params["confidence_min"], regime_params["min_conditions"])
if signals.empty:
    print("\nNo stocks meet the accumulation criteria today.")
    sys.exit(0)

top10 = signals.head(10)

# ----------------------------------------------------------------------
# 5. Console output
# ----------------------------------------------------------------------
print("\n" + "=" * 70)
print(f"{'TOP ACCUMULATION CANDIDATES':^70}")
print(f"Date: {latest_date}   IHSG Regime: {market_label}")
print("=" * 70)
print(f"{'Stock':<8} {'Conf':>7} {'Buy Zone':>16} {'TP':>10} {'SL':>10}")
print("-" * 70)

for _, row in top10.iterrows():
    print(f"{row['stock_code']:<8} {row['confidence']:>6.1f}% "
          f"{row['buy_zone']:>16} {row['tp_target']:>10} {row['sl_target']:>10}")

print("-" * 70)
print(f"Generated by screener.py – {date.today().isoformat()}")

# ----------------------------------------------------------------------
# 6. Simpan ke Supabase (untuk website) + kirim ke Telegram
# ----------------------------------------------------------------------
try:
    supabase.table("screener_results").delete().eq("run_date", latest_date.isoformat()).execute()
    rows = [
        {
            "run_date": latest_date.isoformat(),
            "stock_code": row["stock_code"],
            "confidence": float(row["confidence"]),
            "buy_zone": row["buy_zone"],
            "tp_target": int(row["tp_target"]),
            "sl_target": int(row["sl_target"]),
            "regime": market_label,
        }
        for _, row in top10.iterrows()
    ]
    supabase.table("screener_results").insert(rows).execute()
    print(f"Saved {len(rows)} rows to screener_results.")
except Exception as e:
    print(f"WARNING: Failed to save screener_results to Supabase: {e}")

send_screener_results(top10, latest_date, market_label, regime_params["alloc_pct"])
