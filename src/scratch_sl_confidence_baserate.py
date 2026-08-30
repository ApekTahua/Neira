"""scratch_sl_confidence_baserate.py -- trade-level base-rate check for
V4_SL_CONFIDENCE (docs/V3_FINDINGS_LOG.md 2026-08-30 entry): does the
score/score_p90 ratio compute_entry_fill() already uses for size_mult ALSO
carry information about which ADMITTED, ACTUALLY-TRADED entries turn out to
be "wrong" (stopped out) -- checked directly on real trades, not the fuller
qualifying-candidate-pool diagnose_score_power.py already checked once
(2026-08-07, docs/V3_FINDINGS_LOG.md) at the same-day-RANK level.

Runs the real 9-window schedule with SL_CONFIDENCE_ENABLED=False (the flag's
own effect on sl_price would contaminate the SL-hit-rate readout: a stock
whose stop only moved because of the flag isn't an independent data point
about whether the SIGNAL predicted trouble) and diag={} (purely additive
research hook, see test_diag_hook.py), joins each admitted candidate
(diag["days"][i]["admitted"]) against its own eventual df_trades outcome by
(stock_code, trade_date==entry_date), and buckets by score/score_p90 tercile.

V4_ATR_PRICE_RATIO_MAX pinned to 0.08 -- same baseline convention as
test_sl_confidence.py / the two most recent broker-flow/divergence sessions.

Usage: python src/scratch_sl_confidence_baserate.py
(requires .cache/walk_forward_data_2021-01-01_2026-06-30.pkl)
"""

import os
from datetime import date

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt


def main():
    bt.SL_CONFIDENCE_ENABLED = False  # baseline SL behavior -- see module docstring for why
    df, idx_df = wf.load_dataset()
    schedule = wf.build_schedule(date(2022, 1, 1), bt.TEST_END)

    rows = []
    for i, (tr_end, te_start, te_end) in enumerate(schedule, 1):
        diag = {}
        metrics, df_trades, df_equity, _regime = bt.simulate_window(
            df, idx_df, tr_end, te_start, te_end, label=f"W{i}", diag=diag)
        if metrics is None or df_trades.empty:
            continue

        admitted = [a for d in diag.get("days", []) for a in (d.get("admitted") or [])]
        if not admitted:
            continue
        adm = pd.DataFrame(admitted)

        # Per-position outcome: aggregate every df_trades row sharing (stock_code, entry_date)
        # -- a position with a partial TP1 sell followed by a later full exit produces two
        # rows; "hit_sl" asks whether SL fired at all for that position, "win" asks whether
        # its NET pnl across all rows was positive.
        outcome = df_trades.groupby(["stock_code", "entry_date"]).agg(
            hit_sl=("exit_reason", lambda s: (s == "SL").any()),
            net_pnl=("pnl", "sum"),
        ).reset_index()
        outcome["win"] = outcome["net_pnl"] > 0

        merged = adm.merge(outcome, left_on=["stock_code", "trade_date"],
                            right_on=["stock_code", "entry_date"], how="inner")
        merged["window"] = i
        rows.append(merged)

    if not rows:
        raise SystemExit("[DIAG] No admitted+matched trades across the whole schedule.")

    all_rows = pd.concat(rows, ignore_index=True)
    all_rows["score_ratio"] = all_rows["score"] / all_rows["score_p90"].replace(0, np.nan)
    print(f"\n[DIAG] {len(all_rows)} admitted candidates matched to a real trade outcome "
          f"across {all_rows['window'].nunique()} windows")

    print("\n" + "=" * 90)
    print("A. POOLED -- bucketed by score/score_p90 tercile (the exact ratio size_mult uses)")
    print("=" * 90)
    all_rows["bucket"] = pd.qcut(all_rows["score_ratio"], 3, labels=["low", "mid", "high"], duplicates="drop")
    agg = all_rows.groupby("bucket", observed=True).agg(
        n=("win", "size"), win_rate=("win", lambda s: 100 * s.mean()),
        sl_hit_rate=("hit_sl", lambda s: 100 * s.mean()),
        mean_pnl=("net_pnl", "mean"), score_ratio_mean=("score_ratio", "mean"),
    ).round(2)
    print(agg.to_string())

    print("\n" + "=" * 90)
    print("B. TOP DECILE vs REST -- isolates the same-day-outlier effect diagnose_score_power")
    print("   found concentrated in rank-1 specifically, not a smooth gradient")
    print("=" * 90)
    cut = all_rows["score_ratio"].quantile(0.90)
    all_rows["top_decile"] = all_rows["score_ratio"] >= cut
    agg2 = all_rows.groupby("top_decile").agg(
        n=("win", "size"), win_rate=("win", lambda s: 100 * s.mean()),
        sl_hit_rate=("hit_sl", lambda s: 100 * s.mean()), mean_pnl=("net_pnl", "mean"),
    ).round(2)
    print(agg2.to_string())

    print("\n" + "=" * 90)
    print("C. PER-WINDOW -- is the pooled read (if any) consistent, or one window's artifact?")
    print("=" * 90)
    per_window = all_rows.groupby(["window", "bucket"], observed=True).agg(
        n=("win", "size"), win_rate=("win", lambda s: 100 * s.mean()),
        sl_hit_rate=("hit_sl", lambda s: 100 * s.mean()),
    ).round(1).reset_index()
    print(per_window.to_string(index=False))

    has_conc = all_rows["concentration"].notna() & (all_rows["concentration_p90"] > 0)
    if has_conc.sum() >= 30:
        print("\n" + "=" * 90)
        print(f"D. BANDARMOLOGY CONCENTRATION coverage check -- {has_conc.sum()}/{len(all_rows)} "
              f"admitted candidates ({100*has_conc.mean():.1f}%) have real concentration data")
        print("=" * 90)
        cr = all_rows[has_conc].copy()
        cr["conc_ratio"] = cr["concentration"] / cr["concentration_p90"]
        cr["conc_bucket"] = pd.qcut(cr["conc_ratio"], 3, labels=["low", "mid", "high"], duplicates="drop")
        aggc = cr.groupby("conc_bucket", observed=True).agg(
            n=("win", "size"), win_rate=("win", lambda s: 100 * s.mean()),
            sl_hit_rate=("hit_sl", lambda s: 100 * s.mean()),
        ).round(2)
        print(aggc.to_string())
    else:
        print(f"\n[D] Concentration data coverage too thin to bucket "
              f"({has_conc.sum()}/{len(all_rows)} admitted candidates) -- skipped.")

    all_rows.to_csv("scratch_sl_confidence_baserate_raw.csv", index=False)
    print("\n[OK] Saved scratch_sl_confidence_baserate_raw.csv")


if __name__ == "__main__":
    main()
