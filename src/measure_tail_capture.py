"""How much of the tail our exit actually keeps.

The 2026-09-05 measurement (`measure_tail_fatness.py`) established that the
entry filter has no directional skill but draws from a right tail roughly twice
as fat as the liquid universe: the odds of a +25% run over 20 sessions are
16.4% against 7.5%, and that gap is significant while the median gap is not.

That reframes the exit. If the edge IS the tail, the exit's job is not to be
right about direction -- it is to still be holding when a tail event finishes.
92.1% of gross profit already comes from the trailing stop, which says the
mechanism is roughly correct, but nothing has ever measured what fraction of an
available run we keep, or which exit reason leaks the most.

For every position in run 37: take the best close-to-close gain available from
the entry date over the next `HORIZON` sessions, and compare it against what the
position actually realised. Capture ratio = realised / available. Split by exit
reason, because the interesting number is not the average -- it is whether the
leak is concentrated in one exit type.

Pre-registered in docs/EXPERIMENT_REGISTER.md before running. Deciding metric:
**median capture ratio by exit reason, on positions whose available peak exceeded
+25%** -- i.e. the tail draws specifically, since capture on a position that
never ran anywhere is not a question about the tail.

Read-only. Nothing here may be promoted: same exhausted windows, see
docs/HOLDOUT_PROTOCOL.md Rule 1.
"""
import os
import sys
from collections import defaultdict

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
os.chdir(SRC)

from dotenv import load_dotenv

load_dotenv(os.path.join(SRC, "..", ".env"))
os.environ.setdefault("V4_TEST_END", "2026-06-30")

import numpy as np  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402
from supabase import create_client  # noqa: E402

RUN_ID = 37
HORIZON = 60          # sessions from entry the peak is measured over
TAIL_CUT = 25.0       # a position "had a tail" if its available peak beat this


def main():
    print("[DATA] cached dataset ...")
    df, _ = wf.load_dataset()
    df = df[["stock_code", "trade_date", "close_price"]].copy()
    df["trade_date"] = df["trade_date"].astype(str).str.slice(0, 10)
    cal = sorted(df.trade_date.unique())
    idx = {d: i for i, d in enumerate(cal)}
    close = df.set_index(["stock_code", "trade_date"]).close_price.to_dict()
    print(f"[DATA] {len(df):,} rows, {len(cal)} sessions")

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    legs = sb.table("backtest_trades").select(
        "stock_code,entry_date,exit_date,entry_price,exit_price,exit_reason,shares"
    ).eq("run_id", RUN_ID).execute().data
    print(f"[POS ] {len(legs)} legs")

    # A position is one (stock, entry_date); TP1 splits it into legs, so combine
    # them share-weighted -- otherwise a partial sale counts as a whole outcome,
    # the same leg-vs-position error that once inflated the win rate 26.3 -> 49.3.
    pos = defaultdict(lambda: {"pnl": 0.0, "cost": 0.0, "reasons": []})
    for t in legs:
        k = (t["stock_code"], t["entry_date"])
        ep, xp = float(t["entry_price"]), float(t["exit_price"])
        sh = float(t["shares"] or 0)
        pos[k]["pnl"] += (xp - ep) * sh
        pos[k]["cost"] += ep * sh
        pos[k]["reasons"].append((t["exit_date"], t["exit_reason"]))

    rows = []
    for (code, d0), v in pos.items():
        if v["cost"] <= 0:
            continue
        i = idx.get(d0)
        if i is None:
            continue
        p0 = close.get((code, d0))
        if not p0 or p0 <= 0:
            continue
        window = [close.get((code, d)) for d in cal[i + 1:i + 1 + HORIZON]]
        window = [p for p in window if p]
        if not window:
            continue
        available = (max(window) / p0 - 1) * 100
        realised = v["pnl"] / v["cost"] * 100
        final_reason = sorted(v["reasons"])[-1][1]
        rows.append((code, d0, final_reason, available, realised))

    print(f"[POS ] {len(rows)} positions with a usable {HORIZON}-session window\n")

    def block(sel, title):
        sub = [r for r in rows if sel(r)]
        if not sub:
            return
        print("=" * 92)
        print(f"{title}   n={len(sub)}")
        print("=" * 92)
        print(f"{'exit reason':>14}{'n':>6}{'avail p50':>12}{'realised p50':>14}"
              f"{'capture p50':>13}{'capture mean':>14}")
        by = defaultdict(list)
        for r in sub:
            by[r[2]].append(r)
        for reason in sorted(by, key=lambda k: -len(by[k])):
            g = by[reason]
            av = np.array([x[3] for x in g])
            re = np.array([x[4] for x in g])
            cap = np.where(av > 0, re / np.where(av == 0, np.nan, av), np.nan)
            cap = cap[~np.isnan(cap)]
            print(f"{reason:>14}{len(g):>6}{np.median(av):>+11.2f}%"
                  f"{np.median(re):>+13.2f}%"
                  f"{(np.median(cap) * 100 if len(cap) else float('nan')):>12.1f}%"
                  f"{(cap.mean() * 100 if len(cap) else float('nan')):>13.1f}%")
        av = np.array([x[3] for x in sub])
        re = np.array([x[4] for x in sub])
        cap = re[av > 0] / av[av > 0]
        print(f"{'ALL':>14}{len(sub):>6}{np.median(av):>+11.2f}%"
              f"{np.median(re):>+13.2f}%{np.median(cap) * 100:>12.1f}%"
              f"{cap.mean() * 100:>13.1f}%\n")

    block(lambda r: True, "Every position")
    block(lambda r: r[3] > TAIL_CUT,
          f"Positions that actually ran (available peak > +{TAIL_CUT:.0f}%)")

    print("A capture ratio near 100% on the tail block means the exit is already")
    print("harvesting what the entry draws, and the entry is the thing to improve.")
    print("A low ratio concentrated in ONE exit reason names the leak.")


if __name__ == "__main__":
    main()
