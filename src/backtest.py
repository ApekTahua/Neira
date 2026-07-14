"""
backtest.py — Backtesting untuk Accumulation Detector
Mensimulasikan strategi dari screener.py secara point-in-time.

Menghasilkan reports/backtest_report.html (grafik equity vs IHSG) dan
reports/backtest_report.txt, diupload sebagai artifact di GitHub Actions.
"""

import os
import sys
import base64
from io import BytesIO

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from supabase import create_client
from datetime import date, timedelta
import time
import config as cfg
from strategy import add_features, get_regime, get_regime_params, get_signals

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reports")


def _retry(fn, attempts=4, base_delay=2.0):
    """anon role punya statement_timeout=3s; query yang menyentuh tabel besar
    (ihsg_eod, 1.3jt baris) bisa melewati itu saat DB sedang ramai. Retry
    dengan backoff lebih murah daripada menaikkan timeout role secara global."""
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (i + 1))

# Palet warna (lihat skill dataviz): series-1 biru = portfolio, series-2
# aqua = IHSG, merah = drawdown/regime bearish.
COLOR_PORTFOLIO = "#2a78d6"
COLOR_IHSG = "#1baf7a"
COLOR_DRAWDOWN = "#e34948"
COLOR_BEARISH_BG = "#e3494820"  # merah, alpha rendah
COLOR_GRID = "#e1e0d9"
COLOR_INK = "#0b0b0b"
COLOR_MUTED = "#898781"

# ======================================================================
# KONFIGURASI BACKTEST
# ======================================================================
# Window bisa dioverride via env (untuk uji out-of-sample di GitHub Actions)
BACKTEST_START = date.fromisoformat(os.environ.get("BACKTEST_START", "2025-07-01"))
BACKTEST_END = date.fromisoformat(os.environ.get("BACKTEST_END", "2025-12-31"))
FETCH_START = BACKTEST_START - timedelta(days=280)   # ~200 hari bursa — cukup untuk SMA200
INITIAL_CAPITAL = 100_000_000        # Rp 100 juta
SL_PCT = 0.02                        # Stop loss 2% (fallback)
LOT_SIZE = 100                       # 1 lot = 100 lembar
TRANSACTION_COST = 0.002             # 0.2% biaya transaksi

# Tag hasil run ini di Supabase (website hanya menampilkan version+is_published
# yang sesuai — dipakai supaya eksperimen V2 tidak numpang tampil di production)
BACKTEST_VERSION = os.environ.get("BACKTEST_VERSION", "v1")
BACKTEST_PUBLISH = os.environ.get("BACKTEST_PUBLISH", "true").lower() == "true"

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
    # Ambil daftar stock_code dari hari bursa terakhir di rentang.
    # Cari tanggal dari idx_df (sudah di-fetch, kecil) — bukan query baru ke
    # ihsg_eod (1.3 juta baris): ORDER BY trade_date DESC tanpa filter
    # stock_code tidak bisa pakai index (stock_code, trade_date) dan gampang
    # timeout begitu rentang tanggalnya besar (mis. backtest multi-tahun).
    print("[FETCH] Mengambil daftar stock_code ...")
    idx_in_range = idx_df[
        (idx_df["trade_date"] >= BACKTEST_START) & (idx_df["trade_date"] <= BACKTEST_END)
    ] if not idx_df.empty else idx_df
    code_date = (
        idx_in_range["trade_date"].max().isoformat()
        if not idx_in_range.empty else BACKTEST_END.isoformat()
    )

    codes_batch = _retry(lambda: (
        supabase.table("ihsg_eod")
        .select("stock_code")
        .eq("trade_date", code_date)
        .limit(2000)
        .execute()
    ))
    unique_codes = sorted(set(row["stock_code"] for row in (codes_batch.data or [])))
    if not unique_codes:
        # Fallback: coba BACKTEST_START
        codes_batch = _retry(lambda: (
            supabase.table("ihsg_eod")
            .select("stock_code")
            .eq("trade_date", BACKTEST_START.isoformat())
            .limit(2000)
            .execute()
        ))
        unique_codes = sorted(set(row["stock_code"] for row in (codes_batch.data or [])))
    print(f"[FETCH] {len(unique_codes)} ticker unik ditemukan dari tanggal {code_date}")

    # Fetch data per batch stock_code (query kecil, tidak timeout)
    all_stocks = []
    batch_size = 50
    for i in range(0, len(unique_codes), batch_size):
        batch_codes = unique_codes[i : i + batch_size]
        offset = 0
        while True:
            batch = _retry(lambda: (
                supabase.table("ihsg_eod")
                .select("stock_code,trade_date,open_price,close_price,high,low,previous,volume,foreign_buy,foreign_sell")
                .in_("stock_code", batch_codes)
                .gte("trade_date", FETCH_START.isoformat())
                .lte("trade_date", BACKTEST_END.isoformat())
                .order("trade_date")
                .range(offset, offset + 999)
                .execute()
            ))
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
# 4b. GRAFIK: equity vs IHSG + drawdown
# ======================================================================
def _render_chart_png(df_equity: pd.DataFrame, idx_df: pd.DataFrame) -> str:
    """Equity portfolio vs IHSG (di-index ke 100) + drawdown. Return base64 PNG."""
    bench = idx_df[
        (idx_df["trade_date"] >= df_equity["date"].iloc[0])
        & (idx_df["trade_date"] <= df_equity["date"].iloc[-1])
    ].set_index("trade_date")["close"]
    bench_aligned = bench.reindex(df_equity["date"]).ffill().bfill()

    port_idx = df_equity["total"] / df_equity["total"].iloc[0] * 100
    ihsg_idx = bench_aligned / bench_aligned.iloc[0] * 100
    dates = df_equity["date"]

    regimes = [get_regime(idx_df, d) for d in dates]

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 6.5), sharex=True, height_ratios=[2.5, 1],
        gridspec_kw={"hspace": 0.08},
    )

    # Shading regime BEARISH (kondisi IHSG)
    in_bear = False
    bear_start = None
    for d, r in zip(dates, regimes):
        if r == "BEARISH" and not in_bear:
            in_bear, bear_start = True, d
        elif r != "BEARISH" and in_bear:
            ax1.axvspan(bear_start, d, color=COLOR_BEARISH_BG, lw=0)
            in_bear = False
    if in_bear:
        ax1.axvspan(bear_start, dates.iloc[-1], color=COLOR_BEARISH_BG, lw=0)

    ax1.plot(dates, port_idx, color=COLOR_PORTFOLIO, lw=2, label="Strategi")
    ax1.plot(dates, ihsg_idx, color=COLOR_IHSG, lw=2, label="IHSG")
    ax1.axhline(100, color=COLOR_MUTED, lw=1, ls="--")
    ax1.set_ylabel("Indeks (awal = 100)", color=COLOR_INK)
    ax1.legend(loc="upper left", frameon=False)
    ax1.grid(True, color=COLOR_GRID, lw=0.8)
    ax1.set_title(
        "Equity Strategi vs IHSG  (area merah = regime BEARISH)",
        color=COLOR_INK, fontsize=12, loc="left",
    )
    for spine in ("top", "right"):
        ax1.spines[spine].set_visible(False)

    dd = (df_equity["total"] - df_equity["total"].cummax()) / df_equity["total"].cummax() * 100
    ax2.fill_between(dates, dd, 0, color=COLOR_DRAWDOWN, alpha=0.35, lw=0)
    ax2.plot(dates, dd, color=COLOR_DRAWDOWN, lw=1.2)
    ax2.set_ylabel("Drawdown %", color=COLOR_INK)
    ax2.grid(True, color=COLOR_GRID, lw=0.8)
    for spine in ("top", "right"):
        ax2.spines[spine].set_visible(False)
    fig.autofmt_xdate()

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#fcfcfb")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _concentration_notes(df_trades: pd.DataFrame, net_profit: float) -> str:
    """Catatan risiko: seberapa besar net profit ditopang segelintir trade."""
    if net_profit <= 0 or df_trades.empty:
        return ""
    top = df_trades.sort_values("pnl", ascending=False)
    top1 = top.iloc[0]
    top1_pct = top1["pnl"] / net_profit * 100
    top3_pct = top["pnl"].head(3).sum() / net_profit * 100
    return (
        f"Trade terbesar ({top1['stock_code']}) menyumbang {top1_pct:.0f}% dari net profit; "
        f"top-3 trade = {top3_pct:.0f}%. Distribusi return fat-tailed (khas trend-following) — "
        f"angka net profit sensitif terhadap segelintir outlier, jangan dijadikan ekspektasi baseline."
    )


def _save_to_supabase(df_trades: pd.DataFrame, df_equity: pd.DataFrame, idx_df: pd.DataFrame, metrics: dict) -> None:
    """Simpan ringkasan + trade + equity curve ke Supabase untuk website."""
    try:
        run_res = supabase.table("backtest_runs").insert({
            "version": BACKTEST_VERSION,
            "period_start": BACKTEST_START.isoformat(),
            "period_end": BACKTEST_END.isoformat(),
            "initial_capital": metrics["initial_capital"],
            "final_capital": metrics["final_capital"],
            "net_profit_pct": metrics["total_return_pct"],
            "benchmark_pct": metrics["bench_ret"],
            "alpha_pct": metrics["total_return_pct"] - metrics["bench_ret"],
            "total_trades": metrics["total_trades"],
            "win_rate": metrics["win_rate"],
            "profit_factor": None if metrics["profit_factor"] == float("inf") else metrics["profit_factor"],
            "max_drawdown": metrics["max_drawdown"],
            "notes": metrics["notes"],
            "strategy_summary": metrics["strategy_summary"],
            "is_published": BACKTEST_PUBLISH,
        }).execute()
        run_id = run_res.data[0]["id"]

        trade_rows = [
            {
                "run_id": run_id,
                "stock_code": tr["stock_code"],
                "entry_date": tr["entry_date"].isoformat(),
                "exit_date": tr["exit_date"].isoformat(),
                "entry_price": float(tr["entry_price"]),
                "exit_price": float(tr["exit_price"]),
                "lots": int(tr["lots"]),
                "pnl": float(tr["pnl"]),
                "pnl_pct": float(tr["pnl_pct"]),
                "exit_reason": tr["exit_reason"],
            }
            for _, tr in df_trades.iterrows()
        ]
        equity_rows = [
            {
                "run_id": run_id,
                "date": row["date"].isoformat(),
                "portfolio_value": float(row["total"]),
                "drawdown_pct": float(row["drawdown"]),
                "regime": get_regime(idx_df, row["date"]),
            }
            for _, row in df_equity.iterrows()
        ]
        for i in range(0, len(trade_rows), 500):
            supabase.table("backtest_trades").insert(trade_rows[i:i + 500]).execute()
        for i in range(0, len(equity_rows), 500):
            supabase.table("backtest_equity").insert(equity_rows[i:i + 500]).execute()

        print(f"[OK] Tersimpan ke Supabase: backtest_runs id={run_id}, "
              f"{len(trade_rows)} trade, {len(equity_rows)} hari equity.")
    except Exception as e:
        print(f"WARNING: Gagal simpan ke Supabase: {e}")


def _render_html_report(report_text: str, chart_b64: str) -> str:
    return f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<title>Backtest Report — Accumulation Detector</title>
<style>
  body {{ background:#f9f9f7; color:#0b0b0b; font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         max-width: 900px; margin: 2rem auto; padding: 0 1rem; }}
  img {{ max-width: 100%; border-radius: 8px; border: 1px solid #e1e0d9; }}
  pre {{ background:#fcfcfb; border:1px solid #e1e0d9; border-radius:8px; padding:1rem;
        overflow-x:auto; font-size: 0.82rem; line-height:1.4; }}
  h1 {{ font-size: 1.3rem; }}
</style></head>
<body>
  <h1>Backtest Report — Accumulation Detector</h1>
  <img src="data:image/png;base64,{chart_b64}" alt="Equity vs IHSG">
  <pre>{report_text}</pre>
</body></html>"""


# ======================================================================
# 5. BACKTEST UTAMA
# ======================================================================
def run_backtest():
    print("=" * 70)
    print("BACKTEST ACCUMULATION DETECTOR")
    print(f"Periode: {BACKTEST_START} – {BACKTEST_END}")
    print(f"Modal Awal: Rp {INITIAL_CAPITAL:,.0f}")
    print(f"Entry: open T+1 | Exit: TP1/SL intraday, trailing EOD")
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

    # Lookup OHLC untuk eksekusi intraday (open bisa kotor di data: 0/di luar range)
    bar_lookup = {
        (r.stock_code, r.trade_date): (r.open_price, r.close_price, r.high, r.low)
        for r in df.itertuples()
    }

    def get_bar(stock_code, d):
        """(open, close, high, low) tersanitasi. open=None jika tidak dipercaya."""
        try:
            o, c, h, l = bar_lookup[(stock_code, d)]
        except KeyError:
            return None
        if pd.isna(c) or c <= 0:
            return None
        h = c if (pd.isna(h) or h <= 0) else max(h, c)
        l = c if (pd.isna(l) or l <= 0) else min(l, c)
        if pd.isna(o) or o <= 0 or o > h or o < l:
            o = None
        return o, c, h, l

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
    pending_entries = [] # Sinyal kemarin, dieksekusi di open hari ini

    # --- 5d. Loop utama ---
    for day_idx, trade_date in enumerate(trading_days):
        # Tentukan regime IHSG hari ini (dipakai di exit dan entry)
        regime = get_regime(idx_df, trade_date)
        regime_params = get_regime_params(regime)

        # ---- Eksekusi pending entry di OPEN hari ini (sinyal kemarin) ----
        # Realistis: screener jalan setelah bursa tutup, order dieksekusi besoknya.
        prev_equity = equity_curve[-1]["total"] if equity_curve else float(INITIAL_CAPITAL)
        for sig in pending_entries:
            if any(p["stock_code"] == sig["stock_code"] for p in positions):
                continue
            if len(positions) >= sig["max_positions"]:
                break

            bar = get_bar(sig["stock_code"], trade_date)
            if bar is None:
                continue
            o, c, h, l = bar
            entry_price = o if o is not None else c
            # Skip jika gap terlalu jauh dari harga sinyal (setup sudah basi).
            # Batas sadar-tick: saham murah bergerak >5% per tick — izinkan 2 tick.
            sc = sig["signal_close"]
            tick = 1 if sc < 200 else 2 if sc < 500 else 5 if sc < 2000 else 10 if sc < 5000 else 25
            gap_limit = max(cfg.GAP_MAX, 2 * tick / sc)
            if abs(entry_price / sc - 1) > gap_limit:
                continue

            atr_val = sig["atr"]
            if pd.isna(atr_val) or atr_val <= 0:
                tp1_price = entry_price * 1.02
                sl_price = entry_price * (1 - SL_PCT)
            else:
                tp1_price = entry_price + atr_val * cfg.TP1_MULT
                sl_price = entry_price - atr_val * sig["sl_mult"]
                tp1_price = max(tp1_price, entry_price * 1.01)
                sl_price = min(sl_price, entry_price * 0.99)

            # Position sizing: risk-based (fixed fractional) — risiko per trade
            # maks RISK_PCT equity, nilai posisi maks alloc_pct equity, dibatasi cash
            alloc = min(prev_equity * sig["alloc_pct"], cash)
            cost_per_share = entry_price * (1 + TRANSACTION_COST)
            lots = int(alloc / cost_per_share) // LOT_SIZE
            risk_per_share = entry_price - sl_price
            if risk_per_share > 0:
                lots_risk = int(prev_equity * cfg.RISK_PCT / risk_per_share) // LOT_SIZE
                lots = min(lots, lots_risk)
            # Liquidity cap: jangan beli lebih dari X% volume harian rata-rata
            liq_lots = int(sig["avg_vol_20"] * cfg.LIQ_CAP_PCT) // LOT_SIZE
            lots = min(lots, liq_lots)
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
            positions.append({
                "stock_code": sig["stock_code"],
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
        pending_entries = []

        # ---- Cek exit untuk posisi terbuka ----
        remaining_positions = []

        for pos in positions:
            # Posisi yang baru dibuka di open hari ini belum dicek exit
            if pos["entry_date"] == trade_date:
                remaining_positions.append(pos)
                continue

            bar = get_bar(pos["stock_code"], trade_date)
            if bar is None:
                # Saham tidak aktif di hari ini, hold
                pos["hold_days"] += 1
                remaining_positions.append(pos)
                continue
            o, close_price, high_price, low_price = bar

            exit_reason = None
            exit_price = None
            sell_lots = 0

            # Update highest price (basis close) untuk trailing stop
            if close_price > pos["highest_price"]:
                pos["highest_price"] = close_price

            if not pos["tp1_hit"]:
                # SL dicek duluan (konservatif jika SL & TP tersentuh di hari sama).
                # Stop order kena intraday via low; gap down -> isi di open.
                if low_price <= pos["sl_price"]:
                    exit_reason = "SL"
                    exit_price = o if (o is not None and o < pos["sl_price"]) else pos["sl_price"]
                    sell_lots = pos["remaining_lots"]
                # TP1 (partial): limit order kena intraday via high
                elif high_price >= pos["tp1_price"]:
                    exit_reason = "TP1"
                    exit_price = o if (o is not None and o > pos["tp1_price"]) else pos["tp1_price"]
                    sell_lots = max(1, int(pos["remaining_lots"] * cfg.TP1_PCT))
                # Time-based exit (Enhancement 3)
                elif pos["hold_days"] >= cfg.MAX_HOLD_DAYS - 1:
                    pnl_check = (close_price / pos["avg_price"] - 1) * 100
                    # Skip TIME exit jika profitable di bull market
                    if pnl_check > 0 and regime == "BULLISH":
                        pass  # biarkan trailing stop yang handle
                    else:
                        exit_reason = "TIME"
                        exit_price = close_price
                        sell_lots = pos["remaining_lots"]
            else:
                # Setelah TP1: stop efektif = max(trailing 8%, breakeven).
                # Keputusan EOD di close (sistem screener harian).
                trailing_stop = pos["highest_price"] * (1 - cfg.TRAILING_PCT)
                stop_eff = max(trailing_stop, pos["sl_price"])
                if close_price <= stop_eff:
                    exit_reason = "TRAILING"
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

        # ---- Dapatkan sinyal entry (dieksekusi besok di open) ----
        day_data = df[df["trade_date"] == trade_date].copy()

        # Enhancement 4: jumlah kondisi minimal tergantung regime
        if regime == "BULLISH":
            min_cond = cfg.BULLISH_MIN_CONDITIONS
        elif regime == "BEARISH":
            min_cond = cfg.BEARISH_MIN_CONDITIONS
        else:
            min_cond = cfg.NEUTRAL_MIN_CONDITIONS

        signals = get_signals(day_data, regime_params["confidence_min"], min_cond)

        if not signals.empty:
            # Enhancement 2: dynamic position sizing per regime
            if regime == "BULLISH":
                alloc_pct = cfg.ALLOC_BULLISH
            elif regime == "BEARISH":
                alloc_pct = cfg.ALLOC_BEARISH
            else:
                alloc_pct = cfg.ALLOC_NEUTRAL

            # Simpan snapshot parameter hari sinyal; eksekusi besok pagi
            for _, sig in signals.nlargest(15, "confidence").iterrows():
                pending_entries.append({
                    "stock_code": sig["stock_code"],
                    "confidence": float(sig["confidence"]),
                    "signal_close": float(sig["close_price"]),
                    "atr": sig["atr_14"],
                    "avg_vol_20": float(sig["avg_vol_20"]),
                    "sl_mult": regime_params["sl_mult"],
                    "alloc_pct": alloc_pct,
                    "max_positions": regime_params["max_positions"],
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

    # Benchmark IHSG di window yang sama
    bench = idx_df[
        (idx_df["trade_date"] >= BACKTEST_START) & (idx_df["trade_date"] <= BACKTEST_END)
    ]
    bench_ret = (
        (bench["close"].iloc[-1] / bench["close"].iloc[0] - 1) * 100
        if len(bench) >= 2 else float("nan")
    )

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
    _w(f"  Benchmark IHSG       : {bench_ret:+.2f}%  (alpha {total_return_pct - bench_ret:+.2f}%)")
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
    strategy_lines = [
        "Sinyal: MA squeeze + BB squeeze + volume spike + foreign flow (Bandamologi)",
        f"Eksekusi: sinyal EOD, beli di OPEN hari berikutnya (skip gap >{cfg.GAP_MAX*100:.0f}%)",
        f"Sizing: {cfg.ALLOC_BULLISH*100:.0f}%/{cfg.ALLOC_NEUTRAL*100:.0f}%/{cfg.ALLOC_BEARISH*100:.0f}% equity per posisi (bull/neutral/bear), "
        f"maks {cfg.MAX_POS_BULLISH}/{cfg.MAX_POS_NEUTRAL}/{cfg.MAX_POS_BEARISH} posisi",
        f"Liquidity cap: maks {cfg.LIQ_CAP_PCT*100:.0f}% dari avg volume 20 hari",
        f"Exit: TP1 intraday ({cfg.TP1_PCT*100:.0f}% partial) -> trailing {cfg.TRAILING_PCT*100:.0f}% (EOD) + SL breakeven; SL intraday",
        f"Hold max {cfg.MAX_HOLD_DAYS} hari, TP/SL/kondisi menyesuaikan regime IHSG",
    ]
    for line in strategy_lines:
        _w(f"  - {line}")

    _w("")
    _w("=" * 72)
    _w(f"Laporan digenerate oleh backtest.py — {date.today().isoformat()}")
    _w("=" * 72)

    report = "\n".join(report_lines)
    print(report)

    # Simpan ke reports/: .txt (raw) + .html (grafik equity vs IHSG + drawdown)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    txt_path = os.path.join(REPORTS_DIR, "backtest_report.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(report)

    chart_b64 = _render_chart_png(df_equity, idx_df)
    html_path = os.path.join(REPORTS_DIR, "backtest_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_render_html_report(report, chart_b64))

    print(f"\n[OK] Laporan tersimpan di: {txt_path} & {html_path}")

    _save_to_supabase(df_trades, df_equity, idx_df, {
        "initial_capital": INITIAL_CAPITAL,
        "final_capital": final_capital,
        "total_return_pct": total_return_pct,
        "bench_ret": bench_ret,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "notes": _concentration_notes(df_trades, net_profit),
        "strategy_summary": "\n".join(strategy_lines),
    })

    return html_path


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
    os.makedirs(REPORTS_DIR, exist_ok=True)
    txt_path = os.path.join(REPORTS_DIR, "backtest_report.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(report)
    html_path = os.path.join(REPORTS_DIR, "backtest_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(f"<!doctype html><pre>{report}</pre>")
    print(f"\n[OK] Laporan kosong tersimpan di: {txt_path}")


# ======================================================================
# ENTRY POINT
# ======================================================================
if __name__ == "__main__":
    run_backtest()