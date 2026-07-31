"""paper_common.py -- shared helpers for the live paper-trading engine
(src/paper_signal_scan.py, src/paper_monitor.py). Not imported by any V1
live file; kept separate from notifier.py/config.py deliberately since
those are frozen production files (see CLAUDE.md).

Governance: the paper run trades the exact configuration recorded as
"current best validated V3 configuration" in docs/V3_FINDINGS_LOG.md at
launch (2026-08-03) and that configuration is frozen for the run's
lifetime -- see the "Live paper trading" section of that log. Further
algorithm research continues on the backtest side only; an improvement
only ever ships as a new run (e.g. V3.1_PAPER), never a silent edit here.
"""

import os
import requests

PAPER_VERSION = "V3_PAPER"

# Real broker fee structure reported by the user, on top of config.py's
# existing percentage BUY_FEE/SELL_FEE (0.18% / 0.28%) -- a flat surcharge
# on any single buy transaction over Rp10,000,000. Paper-trading-specific:
# does not touch config.py, which is shared with V1's live pipeline.
EXTRA_BUY_FEE_FLAT = 10_000
EXTRA_BUY_FEE_THRESHOLD = 10_000_000


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
    res = (
        supabase.table("backtest_runs")
        .select("id")
        .eq("version", PAPER_VERSION)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
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
    res = (
        supabase.table("ihsg_eod")
        .select("trade_date")
        .gt("trade_date", since_date.isoformat())
        .lte("trade_date", as_of_date.isoformat())
        .execute()
    )
    return len({r["trade_date"] for r in res.data})


TELEGRAM_API = "https://api.telegram.org/bot"


def notify(text: str) -> None:
    """Same requests-based Telegram pattern as src/notifier.py, kept as
    an independent copy since notifier.py is a frozen V1 live file."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_USER_ID")
    if not token or not chat_id:
        print("WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID not set.")
        return
    url = f"{TELEGRAM_API}{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"WARNING: Failed to send Telegram message: {e}")
