"""Stage 3 robustness follow-up to scratch_consolidation_scan.py (2026-08-27, see
docs/V3_FINDINGS_LOG.md) -- the primary scan's result is a rejection (near-zero alpha, sub-
55% win rate at the pre-registered +10d horizon); this checks whether that null is stable
across nearby parameter choices, or a one-lucky/unlucky-point artifact the way the
hysteresis-band sweep and the spike-confirm-gate sweep both turned out to be (see log).

Sweeps the "tight" percentile threshold (5/10/15/20%) at the pre-registered window/min-run,
and the window length (40/60/90/120 trading days, min-run scaled ~2/3 of window) at the
pre-registered 10th-percentile threshold. Reports +10d mean/median return, win rate, and
mean/median alpha vs IHSG for each cell.

Run: .venv/Scripts/python.exe src/scratch_consolidation_sensitivity.py (from worktree root;
needs .cache/walk_forward_data_2021-01-01_2026-06-30.pkl)."""
import sys
import pickle

sys.path.insert(0, "src")
import numpy as np
import pandas as pd
import backtest_v4 as bt
import config as cfg

with open(".cache/walk_forward_data_2021-01-01_2026-06-30.pkl", "rb") as f:
    df0, idx_df = pickle.load(f)
df0 = df0.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
idx_df = idx_df.sort_values("trade_date").reset_index(drop=True)
idx_df["trade_date"] = pd.to_datetime(idx_df["trade_date"])
df0["trade_date"] = pd.to_datetime(df0["trade_date"])
idx_close = idx_df.set_index("trade_date")["close"]
idx_dates = idx_df["trade_date"].values
idx_pos = {d: i for i, d in enumerate(idx_dates)}

liquid_mask = (
    (df0["adtv_20"] >= cfg.ADTV_MIN)
    & df0["atr_14"].notna() & (df0["atr_14"] > 0)
    & ((df0["atr_14"] / df0["close_price"]) <= bt.ATR_PRICE_RATIO_MAX)
)


def idx_fwd_return(trade_date, n):
    i = idx_pos.get(np.datetime64(trade_date))
    if i is None or i + n >= len(idx_dates):
        return np.nan
    return idx_close.iloc[i + n] / idx_close.iloc[i] - 1


def run_config(win, min_run, pctile, n=10):
    df = df0.copy()
    g = df.groupby("stock_code")
    roll_max_high = g["high"].transform(lambda s: s.rolling(win, min_periods=win).max())
    roll_min_low = g["low"].transform(lambda s: s.rolling(win, min_periods=win).min())
    roll_med_close = g["close_price"].transform(lambda s: s.rolling(win, min_periods=win).median())
    df["range_pct"] = (roll_max_high - roll_min_low) / roll_med_close
    threshold = df.loc[liquid_mask & df["range_pct"].notna(), "range_pct"].quantile(pctile)
    qualifies = liquid_mask & df["range_pct"].notna() & (df["range_pct"] <= threshold)
    new_run = qualifies & ~(qualifies.groupby(df["stock_code"]).shift(1, fill_value=False))
    run_id = new_run.cumsum().where(qualifies, -1)
    run_lengths = run_id[run_id >= 0].groupby(run_id[run_id >= 0]).size()
    long_ids = run_lengths[run_lengths >= min_run].index
    ep_mask = run_id.isin(long_ids)
    episodes = df[ep_mask].groupby(run_id[ep_mask]).tail(1).copy()

    fwd = df.sort_values(["stock_code", "trade_date"]).groupby("stock_code")["close_price"] \
        .transform(lambda s: s.shift(-n) / s - 1)
    df[f"fwd_{n}"] = fwd
    episodes[f"fwd_{n}"] = df.loc[episodes.index, f"fwd_{n}"]
    episodes[f"idx_fwd_{n}"] = [idx_fwd_return(d, n) for d in episodes["trade_date"]]
    sub = episodes.dropna(subset=[f"fwd_{n}", f"idx_fwd_{n}"])
    if len(sub) == 0:
        return dict(win=win, min_run=min_run, pctile=pctile, n_episodes=0)
    return dict(
        win=win, min_run=min_run, pctile=pctile, n_episodes=len(sub),
        mean_ret=sub[f"fwd_{n}"].mean() * 100, median_ret=sub[f"fwd_{n}"].median() * 100,
        win_rate=(sub[f"fwd_{n}"] > 0).mean() * 100,
        mean_alpha=(sub[f"fwd_{n}"] - sub[f"idx_fwd_{n}"]).mean() * 100,
        median_alpha=(sub[f"fwd_{n}"] - sub[f"idx_fwd_{n}"]).median() * 100,
    )


rows = [run_config(60, 40, p) for p in (0.05, 0.10, 0.15, 0.20)]
rows += [run_config(w, m, 0.10) for w, m in ((40, 25), (60, 40), (90, 60), (120, 80))]

out = pd.DataFrame(rows)
pd.set_option("display.width", 160)
print(out.to_string(index=False))
