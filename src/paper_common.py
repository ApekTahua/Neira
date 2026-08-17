"""paper_common.py -- shared helpers for the live paper-trading engine
(src/paper_signal_scan.py, src/paper_monitor.py), plus run_guarded() and
notify() reused by src/disclosure_extract.py purely for the generic
crash-alert wrapper -- that script is NOT part of paper trading and is
NOT covered by the governance rule below. Not imported by any V1 live
file; kept separate from notifier.py/config.py deliberately since those
are frozen production files (see CLAUDE.md).

Governance (paper-trading scripts only): the paper run trades the exact
configuration recorded as "current best validated V3 configuration" in
docs/V3_FINDINGS_LOG.md at launch (2026-08-03) and that configuration is
frozen for the run's lifetime -- see the "Live paper trading" section of
that log. Further algorithm research continues on the backtest side
only; an improvement only ever ships as a new run (e.g. V3.1_PAPER),
never a silent edit here.
"""

import os
import sys
import traceback
from datetime import date
import requests
import numpy as np

from db_retry import retry as _retry

PAPER_VERSION = os.environ.get("PAPER_VERSION", "V3_PAPER")

# IDX trading-suspension dates for 2026, per BEI's official announcement
# Peng-00171/BEI.POP/09-2025 (joint decision of 3 ministries on national
# holidays + cuti bersama). Sourced 2026-08-17 via secondary reporting
# (fortuneidn.com) after the official PDF at idx.co.id 403'd automated
# fetch -- cross-checked against a second source (idxchannel.com) for the
# Idul Fitri dates specifically. Re-verify against the official PDF (or
# BEI's own trading-calendar page) if anything here looks off, and this
# needs a fresh list every year -- it is NOT computed, it is transcribed.
#
# Added 2026-08-17 after paper_monitor.py filled EKAD (V3_PAPER) on this
# exact date: ihsg_realtime's upstream sync pushed ~965 freshly-timestamped
# rows despite the exchange being closed for Hari Kemerdekaan, which the
# existing 30-minute staleness guard alone couldn't catch (the data really
# was <30min old by its own timestamp, just wrongly present on a holiday).
IDX_HOLIDAYS_2026 = frozenset({
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 16),  # Isra Mikraj
    date(2026, 2, 16),  # Joint leave, Lunar New Year
    date(2026, 2, 17),  # Lunar New Year (Imlek)
    date(2026, 3, 18),  # Joint leave, Nyepi
    date(2026, 3, 19),  # Nyepi
    date(2026, 3, 20),  # Joint leave, Idul Fitri
    date(2026, 3, 23),  # Joint leave, Idul Fitri
    date(2026, 3, 24),  # Joint leave, Idul Fitri
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 1),   # Labor Day
    date(2026, 5, 14),  # Ascension Day
    date(2026, 5, 15),  # Joint leave, Ascension Day
    date(2026, 5, 27),  # Idul Adha
    date(2026, 5, 28),  # Joint leave, Idul Adha
    date(2026, 6, 1),   # Pancasila Day
    date(2026, 6, 16),  # Islamic New Year
    date(2026, 8, 17),  # Independence Day
    date(2026, 8, 25),  # Prophet Muhammad's Birthday (Maulid)
    date(2026, 12, 24), # Joint leave, Christmas
    date(2026, 12, 25), # Christmas
    date(2026, 12, 31), # Stock Exchange year-end holiday
})


def is_idx_trading_day(d: date) -> bool:
    """Weekday AND not an IDX_HOLIDAYS_2026 date. This is an ADDITIVE guard
    on top of paper_monitor.py's existing ihsg_realtime staleness check, not
    a replacement for it -- for a year IDX_HOLIDAYS_2026 doesn't cover (2027
    onward, until someone updates the table), this falls back to True
    (assume trading day) rather than False, so an un-updated table degrades
    back to pre-2026-08-17 behavior (staleness-only) instead of silently
    going permanently dark. Sends one Telegram warning per call in that
    case specifically so the gap gets noticed instead of rotting quietly --
    see notify()."""
    if d.weekday() >= 5:
        return False
    if d.year == 2026:
        return d not in IDX_HOLIDAYS_2026
    notify(f"⚠️ IDX_HOLIDAYS_{d.year} not in paper_common.py -- holiday guard is blind for {d.isoformat()}, "
           f"falling back to staleness-only. Add {d.year}'s IDX holiday calendar to paper_common.py.")
    return True

# Single source of truth for "this run stopped taking new capital" -- used by
# paper_signal_scan.py's stop_new_entries gate. V3_PAPER retired 2026-08-15
# (same treatment V3.1_PAPER got 2026-08-14): user explicitly chose "retire
# beneran, V4 doang" over keeping V3_PAPER as a quiet comparison baseline.
# V4_PAPER is now the sole source of new entries -- see docs/V3_FINDINGS_LOG.md.
RETIRED_PAPER_VERSIONS = ("V3_PAPER", "V3.1_PAPER")

# V4_PAPER is now the implicit-default/primary run (V3_PAPER held that role
# originally, back when it was the only run). notify() below leaves this
# version's own messages untagged; every other concurrent run gets a
# [PAPER_VERSION] prefix so a shared Telegram chat stays distinguishable.
PRIMARY_PAPER_VERSION = "V4_PAPER"

# Real broker fee structure reported by the user, on top of config.py's
# existing percentage BUY_FEE/SELL_FEE (0.18% / 0.28%) -- a flat surcharge
# on any single buy transaction over Rp10,000,000. Paper-trading-specific:
# does not touch config.py, which is shared with V1's live pipeline.
EXTRA_BUY_FEE_FLAT = 10_000
EXTRA_BUY_FEE_THRESHOLD = 10_000_000

# ihsg_eod/ihsg_realtime's close_price is NOT split-adjusted -- confirmed
# against real data (2026-08-02): DSSA 67000->3120, FISH exactly
# 10350->1035, CUAN 16875->1625, MLPT 25950->1300, PACK 3280->272, all
# clean round-number ratios on ordinary trading days, not crashes (IDX
# auto-reject bands don't permit a real single-day move anywhere near
# this). A position held through an unadjusted split/reverse-split would
# evaluate SL/TP/trailing against a fabricated price cliff and exit on a
# loss that never actually happened. These bounds are wide enough that no
# legitimate single-day IDX move (even ARA/ARB combined with a gap) should
# ever cross them, so a hit here is a very strong split signal, not noise.
CORP_ACTION_RATIO_LOW = 0.6
CORP_ACTION_RATIO_HIGH = 1.7


def looks_like_unadjusted_corporate_action(prev_price, current_price) -> bool:
    """True if current_price vs prev_price is a ratio no real single-day IDX
    move could produce -- see CORP_ACTION_RATIO_LOW/HIGH above. Callers should
    skip SL/TP/trailing evaluation for that position this cycle rather than
    act on a fabricated price cliff, and alert so a human can confirm and
    manually correct the position's avg_price/sl_price/tp1_price."""
    if prev_price is None or prev_price <= 0 or current_price is None or current_price <= 0:
        return False
    ratio = current_price / prev_price
    return ratio < CORP_ACTION_RATIO_LOW or ratio > CORP_ACTION_RATIO_HIGH


def compute_drawdown_and_cvar(equity_history: list, today_equity: float) -> tuple:
    """Pure function so it's independently testable (see
    test_paper_trading_math.py) -- extracted rather than left inline in
    paper_signal_scan.py so the same money-math discipline used for
    compute_entry_fill/evaluate_position_exit in backtest_v4.py applies here.

    `equity_history` = prior days' portfolio_value in date order (today's
    NOT included). Returns (drawdown_pct, cvar_95):
      - drawdown_pct: today's distance from the running peak (incl. today),
        <= 0. Previously hardcoded to 0.0 on every insert -- a real gap,
        fixed here.
      - cvar_95: mean daily return of the days at/below the 5th-percentile
        return (same quantile-then-average method as backtest_v4.py's
        simulate_window -- kept identical on purpose, so a "live CVaR" and
        a "backtest CVaR" are actually comparable numbers, not two
        different formulas sharing a label), or None before there are at
        least 20 daily returns to compute one from -- noisy and misleading
        on a handful of days, so withheld rather than shown.
    """
    series = equity_history + [today_equity]
    peak = max(series)
    drawdown_pct = (today_equity - peak) / peak * 100 if peak > 0 else 0.0

    if len(series) < 21:  # need >=20 day-over-day returns
        return drawdown_pct, None
    daily_rets = [(series[i] / series[i - 1] - 1) for i in range(1, len(series)) if series[i - 1] > 0]
    if len(daily_rets) < 20:
        return drawdown_pct, None
    var_95 = float(np.quantile(daily_rets, 0.05))
    worst = [r for r in daily_rets if r <= var_95]
    cvar_95 = (sum(worst) / len(worst)) * 100 if worst else var_95 * 100
    return drawdown_pct, cvar_95


def total_buy_fee(gross_value: float, buy_fee_pct: float) -> float:
    """Percentage broker fee plus the flat Rp10,000 surcharge on buys over
    Rp10,000,000 gross. Sells only ever use the plain percentage SELL_FEE
    (config.cfg.SELL_FEE) -- the user's extra fee was specified for buys."""
    fee = gross_value * buy_fee_pct
    if gross_value > EXTRA_BUY_FEE_THRESHOLD:
        fee += EXTRA_BUY_FEE_FLAT
    return fee


def get_paper_run_id(supabase) -> int:
    """Looks up the ongoing paper run's id every time rather than
    hardcoding it -- see sql/paper_trading_schema.sql's seed comment."""
    res = _retry(lambda: (
        supabase.table("backtest_runs")
        .select("id")
        .eq("version", PAPER_VERSION)
        .order("id", desc=True)
        .limit(1)
        .execute()
    ))
    if not res.data:
        raise RuntimeError(
            f"No backtest_runs row with version='{PAPER_VERSION}' -- run "
            "sql/paper_trading_schema.sql's seed statement first."
        )
    return res.data[0]["id"]


def trading_days_elapsed(supabase, since_date, as_of_date) -> int:
    """Counts distinct ihsg_eod trading dates strictly after since_date
    through as_of_date (inclusive) -- the live equivalent of the
    backtest's day_idx-based cooldown counter (src/risk.py's
    is_in_cooldown), using ihsg_eod's own calendar as the source of truth
    for what counts as a trading day."""
    if since_date is None:
        return None
    res = _retry(lambda: (
        supabase.table("ihsg_eod")
        .select("trade_date")
        .gt("trade_date", since_date.isoformat())
        .lte("trade_date", as_of_date.isoformat())
        .execute()
    ))
    return len({r["trade_date"] for r in res.data})


TELEGRAM_API = "https://api.telegram.org/bot"


def notify(text: str) -> None:
    """Same requests-based Telegram pattern as src/notifier.py, kept as
    an independent copy since notifier.py is a frozen V1 live file.
    Tags the message with PAPER_VERSION when it isn't PRIMARY_PAPER_VERSION,
    so concurrent runs sharing one Telegram chat stay distinguishable --
    all 3 runs (V3_PAPER/V3.1_PAPER/V4_PAPER) post to the SAME bot+chat
    (confirmed 2026-08-15: every trigger workflow on main references the
    identical secrets.TELEGRAM_BOT_TOKEN/secrets.TELEGRAM_USER_ID secret
    names, no per-workflow `environment:` scoping), so this tag -- not a
    separate chat -- is the only thing that ever distinguished them.
    PRIMARY_PAPER_VERSION moved from V3_PAPER to V4_PAPER 2026-08-15 when
    V3_PAPER was retired (same reason V3.1_PAPER's messages already carried
    a tag): purely cosmetic re-tagging, not a config change."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_USER_ID")
    if not token or not chat_id:
        print("WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID not set.")
        return
    if PAPER_VERSION != PRIMARY_PAPER_VERSION:
        text = f"[{PAPER_VERSION}] {text}"
    url = f"{TELEGRAM_API}{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"WARNING: Failed to send Telegram message: {e}")


def run_guarded(main_fn, script_name: str) -> None:
    """Runs main_fn(); on any uncaught exception, sends a Telegram alert
    (GitHub Actions already emails on a failed run, but that's easy to
    miss for days -- this makes a broken paper-trading job impossible to
    miss) and re-raises so the workflow still shows red.
    """
    try:
        main_fn()
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        notify(f"\U0001F6A8 *{script_name} crashed*\n```\n{tb[-500:]}\n```")
        raise
