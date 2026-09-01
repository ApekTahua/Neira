"""Diagnostic (not a new idea test): decompose V4's frozen-config trade
history to distinguish two rival explanations for the 2026-07-01..2026-08-11
blind holdout's 53.8% win rate / 0.28 profit factor (see docs/V3_FINDINGS_LOG.md
2026-09-01 entry):

  A. exits are mistuned (TP1/trailing cut winners short, SL lets losers run)
  B. strategy is structurally fat-tail dependent, this window had no fat tail

Reuses simulate_window() exactly as already validated/run (same frozen
config: V4_BANDAR_SIZING=1, V4_ATR_PRICE_RATIO_MAX=0.08) against the SAME
already-fetched/cached data (.cache/walk_forward_data_2021-01-01_2026-08-11.pkl,
built by the 2026-09-01 holdout run) -- no new fetch, no parameter sweep, no
code change to backtest_v4.py. Re-running the 9-window schedule + the holdout
window is not a second independent test of anything: same config, same data,
same deterministic simulation, just captured at trade-record granularity
instead of summary-metric granularity, which the original runs never saved.

Usage: SUPABASE_URL=... SUPABASE_KEY=... python src/scratch_v4_exit_diagnostic.py
(or rely on a local .env; supabase creds only needed for the live V4_PAPER pull,
the backtest side runs entirely from cache)
"""
import os

os.environ["V4_BANDAR_SIZING"] = "1"
os.environ["V4_ATR_PRICE_RATIO_MAX"] = "0.08"
os.environ["V4_TEST_END"] = "2026-08-11"

from datetime import date  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import backtest_v4 as bt  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402

pd.set_option("display.width", 160)

print(f"[CONFIG CHECK] BANDAR_SIZING_ENABLED={bt.BANDAR_SIZING_ENABLED}  "
      f"ATR_PRICE_RATIO_MAX={bt.ATR_PRICE_RATIO_MAX}")

# ---------------------------------------------------------------------------
# 1. Load cached dataset (already fetched through 2026-08-11 by the holdout
# run), build the SAME 9-window schedule walk_forward_v4.py always uses, plus
# the holdout window as a 10th entry -- one script, one df/idx_df, no refetch.
# ---------------------------------------------------------------------------
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = None
if url and key:
    from supabase import create_client
    supabase = create_client(url, key)

df, idx_df = wf.load_dataset(supabase)
print(f"[DATA] df rows={len(df)}  date range {df['trade_date'].min()}..{df['trade_date'].max()}")

schedule = wf.build_schedule(date(2022, 1, 1), date(2026, 6, 30))
schedule.append((date(2026, 6, 30), date(2026, 7, 1), date(2026, 8, 11)))  # HOLDOUT, 10th entry
labels = [f"W{i}" for i in range(1, len(schedule))] + ["HOLDOUT"]

all_trades = []
window_meta = []
for label, (tr_end, te_start, te_end) in zip(labels, schedule):
    print(f"\n{'-'*100}\n{label}: train<={tr_end}  test {te_start}..{te_end}\n{'-'*100}")
    metrics, df_trades, df_equity, _regime = bt.simulate_window(df, idx_df, tr_end, te_start, te_end, label=label)
    if metrics is None:
        window_meta.append({"window": label, "test_start": te_start, "test_end": te_end, "trades": 0})
        continue
    df_trades = df_trades.copy()
    df_trades["window"] = label
    all_trades.append(df_trades)
    window_meta.append({
        "window": label, "test_start": te_start, "test_end": te_end,
        "trades": metrics["total_trades"], "win_rate": metrics["win_rate"],
        "profit_pct": metrics["total_return_pct"], "bench_pct": metrics["bench_ret"],
        "profit_factor": metrics["profit_factor"],
    })

trades = pd.concat(all_trades, ignore_index=True)
meta_df = pd.DataFrame(window_meta)
os.makedirs(os.path.join(os.path.dirname(__file__), "..", ".cache"), exist_ok=True)
trades_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "exit_diagnostic_trades.csv")
trades.to_csv(trades_path, index=False)
print(f"\n[OK] {len(trades)} trade-legs across {len(all_trades)} windows saved to {trades_path}")
print(meta_df.to_string(index=False))

# ---------------------------------------------------------------------------
# 2. Win/loss size decomposition -- overall and per window.
# ---------------------------------------------------------------------------
def size_decomp(g, name):
    wins = g[g["pnl"] > 0]
    losses = g[g["pnl"] <= 0]
    n = len(g)
    row = {
        "window": name, "n_trades": n,
        "win_rate": 100 * len(wins) / n if n else float("nan"),
        "avg_win_pct": wins["pnl_pct"].mean() if len(wins) else float("nan"),
        "avg_loss_pct": losses["pnl_pct"].mean() if len(losses) else float("nan"),
        "median_win_pct": wins["pnl_pct"].median() if len(wins) else float("nan"),
        "median_loss_pct": losses["pnl_pct"].median() if len(losses) else float("nan"),
        "avg_win_rp": wins["pnl"].mean() if len(wins) else float("nan"),
        "avg_loss_rp": losses["pnl"].mean() if len(losses) else float("nan"),
        "median_pnl_rp": g["pnl"].median(),
        "mean_pnl_rp": g["pnl"].mean(),
        "profit_factor": (wins["pnl"].sum() / abs(losses["pnl"].sum())) if losses["pnl"].sum() != 0 else float("inf"),
    }
    pos_total = g[g["pnl"] > 0]["pnl"].sum()
    if pos_total > 0:
        top = g["pnl"].sort_values(ascending=False)
        row["top1_pct_of_profit"] = 100 * top.head(1).clip(lower=0).sum() / pos_total
        row["top3_pct_of_profit"] = 100 * top.head(3).clip(lower=0).sum() / pos_total
        row["top5_pct_of_profit"] = 100 * top.head(5).clip(lower=0).sum() / pos_total
    else:
        row["top1_pct_of_profit"] = row["top3_pct_of_profit"] = row["top5_pct_of_profit"] = float("nan")
    return row

print("\n" + "=" * 100)
print("WIN/LOSS SIZE DECOMPOSITION -- per window (trade-leg level: TP1 partial exits are")
print("their own row, separate from the remaining-lot exit of the same position)")
print("=" * 100)
decomp_rows = [size_decomp(g, w) for w, g in trades.groupby("window")]
decomp_rows.append(size_decomp(trades, "ALL"))
decomp_df = pd.DataFrame(decomp_rows)
print(decomp_df.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))

# ---------------------------------------------------------------------------
# 3. Exit-reason breakdown -- count, avg pnl, total pnl contribution, per
# reason, per window and overall. Direct evidence on hypothesis A.
# ---------------------------------------------------------------------------
print("\n" + "=" * 100)
print("EXIT-REASON BREAKDOWN -- overall (all windows + holdout pooled)")
print("=" * 100)
exit_all = trades.groupby("exit_reason").agg(
    n=("pnl", "size"), avg_pnl_pct=("pnl_pct", "mean"), median_pnl_pct=("pnl_pct", "median"),
    avg_pnl_rp=("pnl", "mean"), total_pnl_rp=("pnl", "sum"), avg_hold_days=("hold_days", "mean"),
).sort_values("total_pnl_rp", ascending=False)
exit_all["pct_of_gross_positive"] = 100 * exit_all["total_pnl_rp"].clip(lower=0) / trades[trades["pnl"] > 0]["pnl"].sum()
print(exit_all.to_string(float_format=lambda x: f"{x:,.2f}"))

print("\n" + "-" * 100)
print("EXIT-REASON BREAKDOWN -- HOLDOUT window only")
print("-" * 100)
hold = trades[trades["window"] == "HOLDOUT"]
if len(hold):
    exit_hold = hold.groupby("exit_reason").agg(
        n=("pnl", "size"), avg_pnl_pct=("pnl_pct", "mean"), avg_pnl_rp=("pnl", "mean"),
        total_pnl_rp=("pnl", "sum"), avg_hold_days=("hold_days", "mean"),
    ).sort_values("total_pnl_rp", ascending=False)
    print(exit_hold.to_string(float_format=lambda x: f"{x:,.2f}"))

print("\n" + "-" * 100)
print("EXIT-REASON BREAKDOWN -- per window (avg_pnl_pct pivot, blank = 0 trades that reason)")
print("-" * 100)
pivot = trades.pivot_table(index="window", columns="exit_reason", values="pnl_pct", aggfunc="mean")
pivot = pivot.reindex(labels)
print(pivot.to_string(float_format=lambda x: f"{x:,.2f}"))
pivot_n = trades.pivot_table(index="window", columns="exit_reason", values="pnl_pct", aggfunc="count")
pivot_n = pivot_n.reindex(labels)
print("\n(counts)")
print(pivot_n.to_string())

# ---------------------------------------------------------------------------
# 4. Money left on the table -- for TP1/TRAILING exits, what did the stock do
# in the N trading days AFTER this exit? Uses `df` (per-stock EOD, the same
# in-memory frame simulate_window() itself used -- pulled from ihsg_eod).
# ---------------------------------------------------------------------------
print("\n" + "=" * 100)
print("MONEY LEFT ON THE TABLE -- max favourable excursion after TP1/TRAILING exits")
print("=" * 100)

df_idx = df.set_index(["stock_code", "trade_date"]).sort_index()
by_stock = {sc: g.reset_index(drop=True) for sc, g in df.groupby("stock_code")}


def mfe_after_exit(row, n_days):
    sc, ed, ep = row["stock_code"], row["exit_date"], row["exit_price"]
    g = by_stock.get(sc)
    if g is None:
        return np.nan, np.nan
    pos = g["trade_date"].searchsorted(ed, side="right")
    fwd = g.iloc[pos:pos + n_days]
    if fwd.empty or ep is None or ep <= 0:
        return np.nan, np.nan
    max_high_pct = (fwd["high"].max() / ep - 1) * 100
    max_close_pct = (fwd["close_price"].max() / ep - 1) * 100
    return max_high_pct, max_close_pct


early_exits = trades[trades["exit_reason"].isin(["TP1", "TRAILING"])].copy()
for n in (10, 20):
    res = early_exits.apply(lambda r: mfe_after_exit(r, n), axis=1, result_type="expand")
    early_exits[f"mfe_high_pct_{n}d"] = res[0]
    early_exits[f"mfe_close_pct_{n}d"] = res[1]

print(f"n TP1/TRAILING exit-legs with forward data: {early_exits['mfe_high_pct_10d'].notna().sum()} / {len(early_exits)}")
print("\nBy exit reason (mean realized pnl_pct at exit, vs mean/median further favourable move over next 10/20d):")
summary = early_exits.groupby("exit_reason").agg(
    n=("pnl_pct", "size"),
    realized_pnl_pct=("pnl_pct", "mean"),
    mfe_high_10d_mean=("mfe_high_pct_10d", "mean"),
    mfe_high_10d_median=("mfe_high_pct_10d", "median"),
    mfe_high_20d_mean=("mfe_high_pct_20d", "mean"),
    mfe_high_20d_median=("mfe_high_pct_20d", "median"),
    pct_with_further_upside_10d=("mfe_high_pct_10d", lambda s: 100 * (s > 0).mean()),
)
print(summary.to_string(float_format=lambda x: f"{x:,.2f}"))

print("\nSame breakdown, HOLDOUT window only:")
hold_early = early_exits[early_exits["window"] == "HOLDOUT"]
if len(hold_early):
    print(hold_early[["stock_code", "exit_date", "exit_reason", "pnl_pct",
                       "mfe_high_pct_10d", "mfe_high_pct_20d"]].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
else:
    print("(none)")

# ---------------------------------------------------------------------------
# 5. Full per-trade return distribution -- overall and holdout, for the
# mean-vs-median fat-tail tell.
# ---------------------------------------------------------------------------
print("\n" + "=" * 100)
print("PER-TRADE RETURN DISTRIBUTION (pnl_pct) -- fat-tail tell: mean >> median means")
print("a few big winners carry the average; mean ~= median means returns are more even")
print("=" * 100)
for name, g in [("ALL (9 windows + holdout)", trades), ("9 windows only", trades[trades["window"] != "HOLDOUT"]),
                ("HOLDOUT only", hold)]:
    if not len(g):
        continue
    print(f"\n{name}: n={len(g)}  mean={g['pnl_pct'].mean():.2f}%  median={g['pnl_pct'].median():.2f}%  "
          f"std={g['pnl_pct'].std():.2f}%  skew={g['pnl_pct'].skew():.2f}  "
          f"min={g['pnl_pct'].min():.2f}%  max={g['pnl_pct'].max():.2f}%  "
          f"p10={g['pnl_pct'].quantile(0.10):.2f}%  p90={g['pnl_pct'].quantile(0.90):.2f}%")

# ---------------------------------------------------------------------------
# 6. Position-level (not leg-level) top-N concentration check, per window --
# is the window's total profit generally carried by a handful of positions,
# and does the holdout simply lack one?
# ---------------------------------------------------------------------------
print("\n" + "=" * 100)
print("POSITION-LEVEL CONCENTRATION -- % of window's gross positive PnL from top 1/3/5 STOCKS")
print("(collapses TP1 + final-exit legs of the same position into one stock_code total)")
print("=" * 100)
conc_rows = []
for w, g in trades.groupby("window"):
    by_pos = g.groupby("stock_code")["pnl"].sum().sort_values(ascending=False)
    pos_total = by_pos[by_pos > 0].sum()
    row = {"window": w, "n_positions": len(by_pos)}
    for k in (1, 3, 5):
        row[f"top{k}_pct"] = 100 * by_pos.head(k).clip(lower=0).sum() / pos_total if pos_total > 0 else float("nan")
    row["max_single_stock_pnl_rp"] = by_pos.iloc[0] if len(by_pos) else float("nan")
    conc_rows.append(row)
conc_df = pd.DataFrame(conc_rows).set_index("window").reindex(labels)
print(conc_df.to_string(float_format=lambda x: f"{x:,.2f}"))

# ---------------------------------------------------------------------------
# 7. Live V4_PAPER closed trades, for corroboration (not a new pull -- same
# query scratch_v4paper_live_record_pull.py already used). NOTE: the live
# paper engine only inserts a `backtest_trades` row on the FINAL leg of a
# position (SL/TRAILING/CHECKPOINT/TIME/END) -- see paper_monitor.py's TP1
# branch, which updates `paper_positions` in place but does NOT insert a
# `backtest_trades` row for the TP1 partial sale. So live "closed trade" pnl
# rows are NOT directly comparable, leg-for-leg, to the backtest df_trades
# used above (which record TP1 as its own leg) -- a live CLOSED row's pnl only
# reflects the remaining-lot leg, understating any earlier TP1 profit on that
# same position. Flagged, not fixed (no production code touched).
# ---------------------------------------------------------------------------
if supabase is not None:
    print("\n" + "=" * 100)
    print("LIVE V4_PAPER CLOSED TRADES (corroboration only, see leg-granularity caveat above)")
    print("=" * 100)
    run = supabase.table("backtest_runs").select("*").eq("version", "V4_PAPER").order("id", desc=True).limit(1).execute().data
    if run:
        run_id = run[0]["id"]
        live_trades = supabase.table("backtest_trades").select("*").eq("run_id", run_id).execute().data
        ldf = pd.DataFrame(live_trades)
        if len(ldf):
            print(ldf[["stock_code", "entry_date", "exit_date", "entry_price", "exit_price",
                        "pnl", "pnl_pct", "exit_reason", "hold_days"]].to_string(index=False))
            print(f"\nn={len(ldf)}  win_rate={100*(ldf['pnl']>0).mean():.1f}%  "
                  f"avg_win_pct={ldf.loc[ldf['pnl']>0,'pnl_pct'].mean() if (ldf['pnl']>0).any() else float('nan'):.2f}%  "
                  f"avg_loss_pct={ldf.loc[ldf['pnl']<=0,'pnl_pct'].mean() if (ldf['pnl']<=0).any() else float('nan'):.2f}%")
        else:
            print("No backtest_trades rows yet for this run_id.")
else:
    print("\n[SKIP] No SUPABASE_URL/KEY -- skipped live V4_PAPER corroboration pull.")

print("\n[DONE]")
