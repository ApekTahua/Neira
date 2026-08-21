"""sweep_backlog_queue.py -- walk-forward sweep for BACKLOG_EXPIRY_DAYS, the bounded
backlog/priority queue (docs/V3_FINDINGS_LOG.md, "bounded backlog/priority queue" entry).
This is the OTHER candidate direction from the scarce-MAX_POSITIONS-slot investigation --
Phase 2 there (sweep_max_positions.py) WIDENED the queue (more concurrent slots, smaller
ALLOC_PCT) and was cleanly rejected. This instead lets a dropped candidate stay eligible
for a bounded number of EXTRA days (BACKLOG_EXPIRY_DAYS) before permanently expiring,
re-validated against the same regime gate on every backlog attempt -- MAX_POSITIONS/
ALLOC_PCT untouched.

BACKLOG_EXPIRY_DAYS=0 (with the flag ON) is included as a boundary/sanity cell, not a real
grid point -- at 0 extra days, no candidate ever survives to a second attempt (see the
module comment in backtest_v4.py), so this cell should reproduce the flag-OFF baseline
byte-for-byte. A useful correctness check before trusting 2/3/5, the same discipline
sweep_max_positions.py used (verify the (6, 0.20) cell reproduces the published baseline
before trusting the wider grid).

Same "plateau, not peak" discipline as every other sweep this session: reports per-window
profit/win/PF/DD/trades/concentration/avg_n_positions, not just the aggregate.
avg_n_positions (mean concurrent open positions, from simulate_window's own per-day
"n_positions" equity-curve field) is the explicit check for whether a backlog queue
quietly re-creates the MAX_POSITIONS-widening failure mode from a different angle --
capacity is nominally unchanged (still 6) but a backlog queue that ends up HOLDING more
positions on average would dilute capital the same way.

Usage:
    python src/sweep_backlog_queue.py
    SWEEP_BACKLOG_DAYS=0,2,3,5 python src/sweep_backlog_queue.py
(no Supabase creds needed if .cache/walk_forward_data_*.pkl already exists.)
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V4_BANDAR_SIZING", "0")  # matches the reproducible baseline this log has used since the tick-size-bug entry

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt

DEFAULT_GRID = "0,2,3,5"
GRID = [int(v.strip()) for v in os.environ.get("SWEEP_BACKLOG_DAYS", DEFAULT_GRID).split(",") if v.strip()]


def main():
    supabase = None
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if url and key:
        from supabase import create_client
        supabase = create_client(url, key)

    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)
    df, idx_df = wf.load_dataset(supabase)

    orig_enabled, orig_expiry = bt.BACKLOG_QUEUE_ENABLED, bt.BACKLOG_EXPIRY_DAYS
    all_rows = []

    # OFF baseline first, for the same "confirm the control cell before trusting the grid" reason
    # sweep_max_positions.py caught its own environment-pinning bug with.
    print(f"\n{'='*100}\n[SWEEP] BACKLOG_QUEUE_ENABLED=False (baseline)\n{'='*100}", flush=True)
    bt.BACKLOG_QUEUE_ENABLED = False
    off_df = wf.run_schedule(df, idx_df, schedule)
    off_df["backlog_expiry_days"] = "OFF"
    all_rows.append(off_df)

    for expiry in GRID:
        label = f"BACKLOG_QUEUE_ENABLED=True BACKLOG_EXPIRY_DAYS={expiry}"
        print(f"\n{'='*100}\n[SWEEP] {label}\n{'='*100}", flush=True)
        bt.BACKLOG_QUEUE_ENABLED = True
        bt.BACKLOG_EXPIRY_DAYS = expiry
        res_df = wf.run_schedule(df, idx_df, schedule)
        res_df["backlog_expiry_days"] = expiry
        all_rows.append(res_df)

    bt.BACKLOG_QUEUE_ENABLED, bt.BACKLOG_EXPIRY_DAYS = orig_enabled, orig_expiry

    full = pd.concat(all_rows, ignore_index=True)
    out_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "backlog_queue_sweep_full.csv")
    full.to_csv(out_path, index=False)
    print(f"\n[OK] Saved full per-window results to {out_path}")

    agg_rows = []
    for expiry, g in full.groupby("backlog_expiry_days"):
        traded = g[g["trades"] > 0]
        if traded.empty:
            agg_rows.append({"backlog_expiry_days": expiry, "windows_traded": 0})
            continue
        agg_rows.append({
            "backlog_expiry_days": expiry,
            "windows_traded": len(traded),
            "beat_bench": int((traded["alpha_pct"] > 0).sum()),
            "winrate_over_50": int((traded["win_rate"] > 50).sum()),
            "trades_total": int(traded["trades"].sum()),
            "win_rate_mean": round(traded["win_rate"].mean(), 1),
            "win_rate_median": round(traded["win_rate"].median(), 1),
            "profit_mean": round(traded["profit_pct"].mean(), 2),
            "profit_median": round(traded["profit_pct"].median(), 2),
            "alpha_mean": round(traded["alpha_pct"].mean(), 2),
            "alpha_median": round(traded["alpha_pct"].median(), 2),
            "pf_mean": round(traded["profit_factor"].mean(), 2),
            "pf_median": round(traded["profit_factor"].median(), 2),
            "dd_mean": round(traded["max_dd"].mean(), 2),
            "dd_worst": round(traded["max_dd"].min(), 2),
            "conc_mean": round(traded["concentration_pct"].mean(), 1),
            "conc_max": round(traded["concentration_pct"].max(), 1),
            "avg_n_positions_mean": round(traded["avg_n_positions"].mean(), 2),
            "avg_n_positions_max": round(traded["avg_n_positions"].max(), 2),
        })
    agg = pd.DataFrame(agg_rows)
    print("\n" + "=" * 110)
    print("BACKLOG_EXPIRY_DAYS SWEEP -- aggregate per value ('OFF' == BACKLOG_QUEUE_ENABLED=False)")
    print("=" * 110)
    print(agg.to_string(index=False))
    agg_path = os.path.join(os.path.dirname(__file__), "..", ".cache", "backlog_queue_sweep_agg.csv")
    agg.to_csv(agg_path, index=False)
    print(f"\n[OK] Saved aggregate to {agg_path}")


if __name__ == "__main__":
    main()
