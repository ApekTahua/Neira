"""
Send formatted results to Telegram via bot API.
"""

import os
import requests

TELEGRAM_API = "https://api.telegram.org/bot"

W = [6, 5, 9, 6, 6]


def _row(*cells):
    return " ".join(c.ljust(w) for c, w in zip(cells, W))


def send_screener_results(top10, latest_date, market_label, market_multiplier):
    """Send the top-10 accumulation candidates to a Telegram chat."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_USER_ID")
    if not token or not chat_id:
        print("WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID not set.")
        return

    sep = "\u2500" * (sum(W) + len(W) - 1)
    lines = [
        "\U0001F4CC *Neira \u2014 Quant Result*",
        "\U0001F4C5 `{}`".format(latest_date),
        "",
        "`{}`".format(_row("Ticker", "Score", "Buy Zone", "TP", "SL")),
        "`{}`".format(sep),
    ]
    for _, row in top10.iterrows():
        lines.append(
            "`{}`".format(
                _row(row["stock_code"], "{}%".format(row["confidence"]),
                     row["buy_zone"], str(row["tp_target"]), str(row["sl_target"]))
            )
        )

    text = "\n".join(lines)
    url = "{}{}/sendMessage".format(TELEGRAM_API, token)
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=15)
        resp.raise_for_status()
        print("Telegram notification sent.")
    except Exception as e:
        print("WARNING: Failed to send Telegram message: {}".format(e))