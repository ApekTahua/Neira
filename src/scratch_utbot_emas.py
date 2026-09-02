"""What UT Bot actually did on EMAS, and what Neira did on the same bars.

The user's claim, in his words: UT Bot would have bought EMAS around 6,000 in
July and given a sell signal around 9,000 on 1 Sept, while Neira was still
publishing BUY at 9,600. This script checks that against real EOD bars instead
of arguing about it.

UT Bot Alerts is a plain ATR trailing stop. There is no target in it and no
notion of a "discount price" -- it flips long when close crosses above the
trailing line and flips flat/short when close crosses back below. That matters
for reading the result: any "TP at 9,000" is the trailing line being hit, not a
level the indicator predicted in advance.

Pine reference (Yo_adriiiiaan / QuantNomad), defaults a=1, c=10:
    nLoss = a * atr(c)
    stop  = close > prev_stop and prev_close > prev_stop ? max(prev_stop, close - nLoss)
          : close < prev_stop and prev_close < prev_stop ? min(prev_stop, close + nLoss)
          : close > prev_stop ? close - nLoss : close + nLoss
    buy   = close crosses above stop ; sell = close crosses below stop

Read-only. Touches no live table, no config, no protected V1 file.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from supabase import create_client  # noqa: E402

from db_retry import retry as _retry  # noqa: E402

TICKER = "EMAS"
START = "2026-01-01"


def fetch_bars(supabase, code: str, start: str) -> list[dict]:
    """Only bars that actually traded -- ihsg_eod carries rows with high/low/open
    all zero for non-trading days, and feeding those to an ATR makes it
    meaningless."""
    rows = _retry(lambda: supabase.table("ihsg_eod")
                  .select("trade_date, open_price, high, low, close_price")
                  .eq("stock_code", code).gte("trade_date", start)
                  .order("trade_date").execute()).data
    return [r for r in rows if float(r["high"]) > 0 and float(r["low"]) > 0 and float(r["close_price"]) > 0]


def wilder_atr(highs, lows, closes, period: int) -> list[float | None]:
    """Wilder's RMA of true range -- what Pine's ta.atr() uses. A simple moving
    average here would shift every signal date by a bar or two."""
    trs = []
    for i in range(len(closes)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            trs.append(max(highs[i] - lows[i],
                           abs(highs[i] - closes[i - 1]),
                           abs(lows[i] - closes[i - 1])))
    out: list[float | None] = [None] * len(trs)
    if len(trs) < period:
        return out
    seed = sum(trs[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(trs)):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out


def ut_bot(bars: list[dict], key: float = 1.0, atr_period: int = 10):
    """Returns (signals, series). signals = list of (date, 'BUY'|'SELL', close)."""
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    closes = [float(b["close_price"]) for b in bars]
    atr = wilder_atr(highs, lows, closes, atr_period)

    stop = None
    pos = 0
    signals = []
    series = []
    for i, c in enumerate(closes):
        if atr[i] is None:
            series.append(None)
            continue
        n_loss = key * atr[i]
        prev_stop = stop if stop is not None else 0.0
        prev_close = closes[i - 1] if i > 0 else c
        if c > prev_stop and prev_close > prev_stop:
            stop = max(prev_stop, c - n_loss)
        elif c < prev_stop and prev_close < prev_stop:
            stop = min(prev_stop, c + n_loss)
        elif c > prev_stop:
            stop = c - n_loss
        else:
            stop = c + n_loss
        series.append(stop)

        new_pos = 1 if c > stop else -1
        if pos != 0 and new_pos != pos:
            signals.append((bars[i]["trade_date"], "BUY" if new_pos == 1 else "SELL", c, stop))
        pos = new_pos
    return signals, series


def main():
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    bars = fetch_bars(supabase, TICKER, START)
    print(f"{TICKER}: {len(bars)} traded bars, {bars[0]['trade_date']} .. {bars[-1]['trade_date']}\n")

    for key, period in ((1.0, 10), (2.0, 10), (1.0, 14)):
        signals, _ = ut_bot(bars, key, period)
        print(f"--- UT Bot key={key} atr={period} ---")
        open_price = None
        open_date = None
        for date, kind, close, stop in signals:
            if kind == "BUY":
                open_price, open_date = close, date
                print(f"  {date}  BUY   @ {close:>7,.0f}   (trailing line {stop:,.0f})")
            else:
                pl = f"{100 * (close / open_price - 1):+.1f}% since {open_date}" if open_price else ""
                print(f"  {date}  SELL  @ {close:>7,.0f}   (trailing line {stop:,.0f})  {pl}")
                open_price = None
        if open_price:
            last = float(bars[-1]["close_price"])
            print(f"  (still long, {100 * (last / open_price - 1):+.1f}% since {open_date})")
        print()

    # What Neira said on the same bars.
    sigs = _retry(lambda: supabase.table("daily_qualifying_signals")
                  .select("trade_date, rank, score, signal_close")
                  .eq("stock_code", TICKER).order("trade_date").execute()).data
    print("--- What Neira published ---")
    for s in sigs:
        print(f"  {s['trade_date']}  rank #{s['rank']:<3} score {float(s['score']):.2f}  "
              f"close {float(s['signal_close']):,.0f}")


if __name__ == "__main__":
    main()
