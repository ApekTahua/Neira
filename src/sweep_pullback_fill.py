"""sweep_pullback_fill.py -- walk-forward sweep for PULLBACK_FILL_ENABLED (docs/
V3_FINDINGS_LOG.md, "pullback-to-buy-area fill" entry). Real-trader critique this
answers: a queued candidate fills at next-day's raw open no matter how far above the
signal's own ATR-implied pullback zone that open sits -- this tests waiting for the
zone instead (fill at the zone's near edge the moment the day's low touches it, retry
up to PULLBACK_EXPIRY_SESSIONS sessions, else drop the signal as a false start).

Grid: PULLBACK_LOW_MULT in {0.0, 0.2, 0.3, 0.5} x PULLBACK_HIGH_MULT in
{0.7, 1.0, 1.3, 1.5} (PULLBACK_HIGH_MULT is expected to be a no-op on the fill
mechanism itself per backtest_v4.py's own docstring -- confirmed directly in
test_pullback_fill.py; included here anyway so the full requested grid is reported,
not just asserted).

Baseline = the CURRENT LIVE V4_PAPER config (V4_BANDAR_SIZING default-on,
V4_ATR_PRICE_RATIO_MAX=0.08 -- see paper_signal_scan_v4_trigger.yml), NOT the
V4_BANDAR_SIZING=0 convention some older sweeps in this repo used before that flag was
promoted to default-on.

Usage:
    python src/sweep_pullback_fill.py
    SWEEP_LOW_MULT=0.0,0.3 SWEEP_HIGH_MULT=1.0 python src/sweep_pullback_fill.py
(no Supabase creds needed if .cache/walk_forward_data_*.pkl already exists.)
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")  # V4_PAPER's actual live frozen config

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt

LOW_GRID = [float(v.strip()) for v in os.environ.get("SWEEP_LOW_MULT", "0.0,0.2,0.3,0.5").split(",") if v.strip()]
HIGH_GRID = [float(v.strip()) for v in os.environ.get("SWEEP_HIGH_MULT", "0.7,1.0,1.3,1.5").split(",") if v.strip()]


def main():
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset()

    orig = (bt.PULLBACK_FILL_ENABLED, bt.PULLBACK_LOW_MULT, bt.PULLBACK_HIGH_MULT)
    all_rows = []
    miss_rate_rows = []

    print(f"\n{'='*100}\n[SWEEP] PULLBACK_FILL_ENABLED=False (baseline, live V4_PAPER config)\n{'='*100}", flush=True)
    bt.PULLBACK_FILL_ENABLED = False
    off_df = wf.run_schedule(df, idx_df, schedule)
    off_df["low_mult"], off_df["high_mult"] = "OFF", "OFF"
    all_rows.append(off_df)

    for low in LOW_GRID:
        for high in HIGH_GRID:
            label = f"PULLBACK_FILL_ENABLED=True LOW_MULT={low} HIGH_MULT={high}"
            print(f"\n{'='*100}\n[SWEEP] {label}\n{'='*100}", flush=True)
            bt.PULLBACK_FILL_ENABLED = True
            bt.PULLBACK_LOW_MULT = low
            bt.PULLBACK_HIGH_MULT = high
            bt.PULLBACK_FILL_LOG.clear()
            res_df = wf.run_schedule(df, idx_df, schedule)
            res_df["low_mult"], res_df["high_mult"] = low, high
            all_rows.append(res_df)

            fills = [r for r in bt.PULLBACK_FILL_LOG if r["outcome"] == "FILLED"]
            expired = [r for r in bt.PULLBACK_FILL_LOG if r["outcome"] == "EXPIRED_UNFILLED"]
            total_signals = len(fills) + len(expired)
            avg_improvement_pct = (
                sum((f["raw_open"] - f["fill_price"]) / f["raw_open"] for f in fills) / len(fills) * 100
                if fills else float("nan")
            )
            miss_rate_rows.append({
                "low_mult": low, "high_mult": high,
                "signals_seen": total_signals, "filled": len(fills), "expired_unfilled": len(expired),
                "miss_rate_pct": 100 * len(expired) / total_signals if total_signals else float("nan"),
                "avg_price_improvement_pct": avg_improvement_pct,
                # Of the fills, how many had the raw open already AT/BELOW the area's upper
                # bound (fill_price == raw_open, i.e. the day's real print did the work, no
                # assumed intraday limit fill needed) vs a genuine assumed intraday touch
                # (fill_price == area_upper < raw_open).
                "gap_already_at_open_pct": (
                    100 * sum(1 for f in fills if abs(f["fill_price"] - f["raw_open"]) < 1e-6) / len(fills)
                    if fills else float("nan")
                ),
            })

    bt.PULLBACK_FILL_ENABLED, bt.PULLBACK_LOW_MULT, bt.PULLBACK_HIGH_MULT = orig

    full = pd.concat(all_rows, ignore_index=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "pullback_fill_sweep_full.csv")
    full.to_csv(out_path, index=False)
    print(f"\n[OK] Saved full per-window results to {out_path}")

    agg_rows = []
    for (low, high), g in full.groupby(["low_mult", "high_mult"], sort=False):
        traded = g[g["trades"] > 0]
        if traded.empty:
            agg_rows.append({"low_mult": low, "high_mult": high, "windows_traded": 0})
            continue
        agg_rows.append({
            "low_mult": low, "high_mult": high,
            "windows_traded": len(traded),
            "beat_bench": int((traded["alpha_pct"] > 0).sum()),
            "winrate_over_50": int((traded["win_rate"] > 50).sum()),
            "trades_total": int(traded["trades"].sum()),
            "win_rate_mean": round(traded["win_rate"].mean(), 1),
            "profit_mean": round(traded["profit_pct"].mean(), 2),
            "alpha_mean": round(traded["alpha_pct"].mean(), 2),
            "alpha_median": round(traded["alpha_pct"].median(), 2),
            "pf_mean": round(traded["profit_factor"].mean(), 2),
            "dd_mean": round(traded["max_dd"].mean(), 2),
            "dd_worst": round(traded["max_dd"].min(), 2),
            "avg_n_positions_mean": round(traded["avg_n_positions"].mean(), 2),
        })
    agg = pd.DataFrame(agg_rows)
    print("\n" + "=" * 110)
    print("PULLBACK_FILL sweep -- aggregate per (low_mult, high_mult) cell ('OFF' == PULLBACK_FILL_ENABLED=False)")
    print("=" * 110)
    print(agg.to_string(index=False))
    agg_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "pullback_fill_sweep_agg.csv")
    agg.to_csv(agg_path, index=False)
    print(f"\n[OK] Saved aggregate to {agg_path}")

    miss_df = pd.DataFrame(miss_rate_rows)
    print("\n" + "=" * 110)
    print("FILL-QUALITY / MISS-RATE diagnostic (pooled across all 9 windows, per grid cell)")
    print("=" * 110)
    print(miss_df.to_string(index=False))
    miss_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "pullback_fill_miss_rate.csv")
    miss_df.to_csv(miss_path, index=False)
    print(f"\n[OK] Saved miss-rate diagnostic to {miss_path}")


if __name__ == "__main__":
    main()
