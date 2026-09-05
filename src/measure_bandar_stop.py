"""Could a stop that reads broker flow have kept the runners?

49 of the 120 positions that had a >+25% run available were stopped out first, at
a median -8.75%, on names that went on to offer a median +50%. The council's one
concrete proposal is a stop that consults broker accumulation rather than price
alone: hold while accumulation continues, leave when distribution starts.

That only works if the flow can tell the two kinds of stop-out apart IN ADVANCE.
This checks exactly that and nothing more: among run 37's stop-loss exits, split
by whether accumulation was present in the five sessions before the stop, does
the name's forward run after the stop differ?

Pre-registered before running (docs/EXPERIMENT_REGISTER.md). Deciding metric:
P(the name runs >+25% within 40 sessions after the stop), accumulation present vs
absent, gap bootstrapped by date.

If the gap straddles zero, the flow has nothing to work with and the idea dies
here. Read-only, closed windows, Rule 1.
"""
import os
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
os.chdir(SRC)

from dotenv import load_dotenv

load_dotenv(os.path.join(SRC, "..", ".env"))
os.environ.setdefault("V4_TEST_END", "2026-06-30")

import numpy as np  # noqa: E402
from supabase import create_client  # noqa: E402

import walk_forward_v4 as wf  # noqa: E402

AFTER = 40
RUN = 25.0
LOOKBACK = 5


def main():
    print("[DATA] cached dataset ...")
    df, _ = wf.load_dataset()
    df = df[["stock_code", "trade_date", "close_price",
             "mover_score", "accdist_score"]].copy()
    df["trade_date"] = df["trade_date"].astype(str).str.slice(0, 10)
    cal = sorted(df.trade_date.unique())
    idx = {d: i for i, d in enumerate(cal)}
    close = df.set_index(["stock_code", "trade_date"]).close_price.to_dict()
    mov = df.set_index(["stock_code", "trade_date"]).mover_score.to_dict()
    acc = df.set_index(["stock_code", "trade_date"]).accdist_score.to_dict()

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    sl = sb.table("backtest_trades").select(
        "stock_code,exit_date,exit_price,pnl_pct").eq("run_id", 37).eq(
        "exit_reason", "SL").execute().data
    print(f"[EXITS] {len(sl)} stop-loss exits on run 37\n")

    rows = []
    for t in sl:
        code, d = t["stock_code"], t["exit_date"]
        i = idx.get(d)
        if i is None or i + AFTER >= len(cal):
            continue
        p0 = close.get((code, d))
        if not p0 or p0 <= 0:
            continue
        w = [p for p in (close.get((code, x)) for x in cal[i + 1:i + 1 + AFTER]) if p]
        if not w:
            continue
        run = (max(w) / p0 - 1) * 100
        # Accumulation in the five sessions up to and including the stop.
        back = cal[max(0, i - LOOKBACK + 1):i + 1]
        active = any((mov.get((code, x)) or 0) > 0 or (acc.get((code, x)) or 0) > 0
                     for x in back)
        rows.append((d, active, run))

    if not rows:
        print("no usable exits")
        return
    act = np.array([r[2] for r in rows if r[1]])
    non = np.array([r[2] for r in rows if not r[1]])
    print(f"{'':>26}{'n':>7}{'P(>+' + str(int(RUN)) + '%)':>12}{'median run':>13}"
          f"{'mean run':>12}")
    for lab, a in [("accumulation present", act), ("accumulation absent", non)]:
        if not len(a):
            print(f"{lab:>26}{0:>7}   (none)")
            continue
        print(f"{lab:>26}{len(a):>7}{100 * (a > RUN).mean():>11.1f}%"
              f"{np.median(a):>+12.2f}%{a.mean():>+11.2f}%")

    if not len(act) or not len(non):
        print("\none side is empty -- no comparison possible")
        return

    rng = np.random.default_rng(11)
    by_date = {}
    for d, a, r in rows:
        by_date.setdefault(d, ([], []))[0 if a else 1].append(r)
    dates = list(by_date)
    diffs = []
    for _ in range(4000):
        x, y = [], []
        for d in rng.choice(dates, size=len(dates), replace=True):
            p, q = by_date[d]
            x += p
            y += q
        if x and y:
            diffs.append(100 * ((np.array(x) > RUN).mean() - (np.array(y) > RUN).mean()))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    sig = "SIGNIFICANT" if lo > 0 or hi < 0 else "not significant"
    print(f"\ngap (accumulation present minus absent), date-level bootstrap:")
    print(f"  {np.mean(diffs):+.2f} pp   95% CI [{lo:+.2f}, {hi:+.2f}]   {sig}")
    print(f"\n{len(dates)} distinct exit dates behind {len(rows)} exits -- read the")
    print("interval with that in mind, it is a small sample by construction.")


if __name__ == "__main__":
    main()
