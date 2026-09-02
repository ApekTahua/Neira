"""Is UT Bot actually accurate, or was EMAS one good ride?

EMAS is the reason this question exists: UT Bot went long at 6,100 on 23 July
and gave a sell at 8,800 on 1 Sept, +44.3%, while Neira was still publishing
BUY at 9,600. That single trade is the evidence for "UT Bot is accurate".

One trade in one stock is not a record. This runs the same indicator, same
default settings (key=1.0, ATR 10), over every ticker Neira has ever named, for
a full year, and reports what it would actually have done. Exits are the
indicator's own sell flip -- no stop, no target, no position sizing -- because
that is the thing being evaluated, not a portfolio built around it.

Read-only. No config change, no live table touched.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from supabase import create_client  # noqa: E402

from db_retry import retry as _retry  # noqa: E402
from scratch_utbot_emas import fetch_bars, ut_bot  # noqa: E402

START = "2025-09-01"


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    codes = sorted({r["stock_code"] for r in _retry(
        lambda: sb.table("daily_qualifying_signals").select("stock_code").execute()).data})
    print(f"{len(codes)} tickers Neira has named\n")

    trades = []
    still_open = []
    for i, code in enumerate(codes, 1):
        bars = fetch_bars(sb, code, START)
        if len(bars) < 60:
            continue
        signals, _ = ut_bot(bars, key=1.0, atr_period=10)
        entry = None
        for date_, kind, close, _stop in signals:
            if kind == "BUY":
                entry = (date_, close)
            elif entry:
                trades.append({"code": code, "in": entry[0], "out": date_,
                               "ret": 100 * (close / entry[1] - 1)})
                entry = None
        if entry:
            last = float(bars[-1]["close_price"])
            still_open.append({"code": code, "in": entry[0],
                               "ret": 100 * (last / entry[1] - 1)})
        if i % 20 == 0:
            print(f"  {i}/{len(codes)} tickers ...")

    rets = [t["ret"] for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    rets_sorted = sorted(rets)
    print(f"\n=== UT Bot (key=1, ATR 10), long-only, exit on its own sell flip ===")
    print(f"  closed trades      : {len(trades)} across {len({t['code'] for t in trades})} tickers")
    print(f"  win rate           : {100 * len(wins) / len(rets):.1f}%")
    print(f"  mean return        : {sum(rets) / len(rets):+.2f}%")
    print(f"  median return      : {rets_sorted[len(rets_sorted) // 2]:+.2f}%")
    print(f"  avg win / avg loss : {sum(wins) / len(wins):+.2f}% / {sum(losses) / len(losses):+.2f}%")
    print(f"  best / worst       : {max(rets):+.2f}% / {min(rets):+.2f}%")
    gross_win = sum(wins)
    print(f"  profit factor      : {gross_win / abs(sum(losses)):.2f}")

    # The whole point: is the mean carried by a few monsters, exactly like
    # Neira's own signals are?
    top5 = sorted(rets, reverse=True)[:5]
    print(f"  top 5 trades        : {', '.join(f'{r:+.0f}%' for r in top5)} "
          f"= {100 * sum(top5) / gross_win:.0f}% of all gross profit")
    print(f"  still open          : {len(still_open)}, "
          f"mean {sum(t['ret'] for t in still_open) / len(still_open):+.2f}%" if still_open else "")

    print("\n  best trades:")
    for t in sorted(trades, key=lambda t: -t["ret"])[:8]:
        print(f"    {t['code']:<6} {t['in']} -> {t['out']}  {t['ret']:+7.1f}%")


if __name__ == "__main__":
    main()
