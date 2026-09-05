"""Does the entry filter draw from a fatter-tailed population than chance?

Every previous selection test asked whether the picks go UP -- hit rate,
information coefficient, profit factor. Measured 2026-09-05, buy-and-hold from
entry against liquid names on the same dates, the answer to that question is
no: the MEDIAN pick loses (-4.28% at 60 days) and wins only 45% of the time.

But the MEAN is positive and its gap over random widens with horizon
(+0.47 -> +2.23 -> +4.37pp at 5/20/60 days). Both facts together describe a
system that is not a direction predictor at all: it is a right-tail harvester.
The stop cuts the losing median, the trailing stop rides the tail, and the
trailing stop is where 92.1% of gross profit comes from.

If that reading is right, the metric that matters for an entry is not "how
often is it up" but "how fat is the right tail of what it draws". That has
never been measured. This measures it.

The test is deliberately blunt: no stop, no trail, no sizing, no regime gate --
just the forward return distribution of the names the filter picked, against
names that were liquid on the same day. If the tails are indistinguishable, the
entry filter earns nothing and the system simplifies enormously.

Read-only. Nothing here can be promoted: the underlying window is the same
exhausted data (see docs/HOLDOUT_PROTOCOL.md).
"""
import os
import random
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
os.chdir(SRC)

from dotenv import load_dotenv

load_dotenv(os.path.join(SRC, "..", ".env"))
os.environ.setdefault("V4_TEST_END", "2026-06-30")

import numpy as np  # noqa: E402
import walk_forward_v4 as wf  # noqa: E402
from supabase import create_client  # noqa: E402

HORIZONS = [20, 60]
N_RANDOM_PER_DATE = 12
SEED = 11
BOOT = 4000


def main():
    print("[DATA] cached dataset ...")
    df, _ = wf.load_dataset()
    df = df[["stock_code", "trade_date", "close_price", "adtv_20"]].copy()
    df["trade_date"] = df["trade_date"].astype(str).str.slice(0, 10)
    print(f"[DATA] {len(df):,} rows, {df.stock_code.nunique()} tickers")

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    tr = sb.table("backtest_trades").select("stock_code,entry_date").eq("run_id", 37).execute().data
    entries = sorted({(t["stock_code"], t["entry_date"]) for t in tr})
    print(f"[POS ] {len(entries)} positions")

    cal = sorted(df.trade_date.unique())
    idx = {d: i for i, d in enumerate(cal)}
    close = df.set_index(["stock_code", "trade_date"]).close_price.to_dict()
    liq = (df[(df.adtv_20 >= 1e9) & (df.close_price >= 50)]
           .groupby("trade_date").stock_code.apply(list).to_dict())

    def fwd(code, d0, n):
        i = idx.get(d0)
        if i is None or i + n >= len(cal):
            return None
        p0, p1 = close.get((code, d0)), close.get((code, cal[i + n]))
        if not p0 or not p1 or p0 <= 0:
            return None
        return (p1 / p0 - 1) * 100

    rng = random.Random(SEED)
    for h in HORIZONS:
        ours, rand = [], []
        for code, d0 in entries:
            r = fwd(code, d0, h)
            if r is None:
                continue
            ours.append(r)
            pool = liq.get(d0, [])
            for c in rng.sample(pool, min(N_RANDOM_PER_DATE, len(pool))):
                rr = fwd(c, d0, h)
                if rr is not None:
                    rand.append(rr)
        a, b = np.array(ours), np.array(rand)
        if not len(a):
            continue

        print("\n" + "=" * 92)
        print(f"HOLD {h} SESSIONS   ours n={len(a)}   random n={len(b)}")
        print("=" * 92)

        print(f"\n{'':>22}{'ours':>12}{'random':>12}{'gap':>10}")
        for label, f in [
            ("median", lambda x: np.median(x)),
            ("mean", lambda x: x.mean()),
            ("p75", lambda x: np.percentile(x, 75)),
            ("p90", lambda x: np.percentile(x, 90)),
            ("p95", lambda x: np.percentile(x, 95)),
            ("p99", lambda x: np.percentile(x, 99)),
            ("max", lambda x: x.max()),
        ]:
            va, vb = f(a), f(b)
            print(f"{label:>22}{va:>+11.2f}%{vb:>+11.2f}%{va - vb:>+9.2f}")

        print(f"\n{'share exceeding':>22}{'ours':>12}{'random':>12}{'ratio':>10}")
        for thr in (10, 25, 50, 100):
            pa = 100 * (a > thr).mean()
            pb = 100 * (b > thr).mean()
            ratio = pa / pb if pb > 0 else float("inf")
            print(f"{'+' + str(thr) + '%':>22}{pa:>11.1f}%{pb:>11.1f}%{ratio:>9.2f}x")

        # Bootstrap the two readings that separate "fat tail" from "shifted mean".
        print("\n  bootstrap, 4000 resamples:")
        for label, stat in [
            ("p90 gap", lambda x: np.percentile(x, 90)),
            ("p95 gap", lambda x: np.percentile(x, 95)),
            ("share >+25% gap", lambda x: 100 * (x > 25).mean()),
            ("median gap", lambda x: np.median(x)),
        ]:
            al, bl = a.tolist(), b.tolist()
            d = [stat(np.array(rng.choices(al, k=len(al))))
                 - stat(np.array(rng.choices(bl, k=len(bl)))) for _ in range(BOOT)]
            lo, hi = np.percentile(d, [2.5, 97.5])
            sig = "SIGNIFICANT" if lo > 0 or hi < 0 else "not significant"
            print(f"    {label:<18} {np.mean(d):+7.2f}  95% CI [{lo:+.2f}, {hi:+.2f}]  {sig}")

    print("\nA fat-tail story predicts: p90/p95 and the share above +25% clearly")
    print("beat random, while the median does not. A no-edge story predicts every")
    print("gap straddles zero. Read which pattern the numbers actually show.")


if __name__ == "__main__":
    main()
