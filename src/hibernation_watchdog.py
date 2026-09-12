"""Dead-man's switch for the unattended period.

An automated system with no failure alarm is not safe to leave running against
real-money decisions. Everything else in this repo shouts when it crashes; the
case none of it covers is the one where a component simply STOPS BEING CALLED
-- nothing errors, nothing runs, and the pages keep serving yesterday's numbers
as if they were today's.

The most likely instance of that: the GitHub PAT inside n8n's `Trigger Paper
Monitor` node expires. n8n's own run still succeeds, GitHub never hears from it,
and open positions quietly stop being checked against their stop and target.

So this check runs on **GitHub's own schedule**, not on anything n8n dispatches.
If the PAT dies, this still fires.

WHAT IT DOES NOT USE, and why it matters
----------------------------------------
`paper_positions.updated_at` looks like the obvious liveness signal and is not
one. The column defaults to now() but has NO trigger, and `paper_monitor.py`
never writes it on its per-poll `day_high`/`day_low` update -- so it sits still
for days while the monitor is running perfectly. Measured 2026-09-12: OPEN rows
last stamped 2026-09-10 17:45 (40.9 hours) on a system that was working. An
alarm built on it would have cried wolf on day one and been muted by day three.

The three signals below all move on every healthy day.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests

# The market's own clock. A Saturday with no new EOD row is not a fault.
WIB = timezone(timedelta(hours=7))

# How far behind the newest EOD row may fall before it is a fault. Three
# calendar days clears a normal weekend; IDX holiday runs longer than that are
# rare and produce one message, not a stream -- this runs once a day.
MAX_EOD_LAG_DAYS = 3

# A monitor run older than this on a trading day means the 15-minute cadence
# stopped. Generous on purpose: GitHub delays scheduled runs under load, and an
# alarm that fires on ordinary lateness gets ignored, which is worse than none.
MAX_MONITOR_GAP_HOURS = 24


def decide(
    *,
    today: date,
    latest_eod: date | None,
    latest_scoreboard: date | None,
    hours_since_monitor: float | None,
    is_weekday: bool,
) -> list[str]:
    """Pure decision. Returns one line per fault, empty when healthy.

    Split out from the I/O so it can be checked without a network, a database,
    or waiting for a real outage to happen.
    """
    faults: list[str] = []

    if latest_eod is None:
        return ["`ihsg_eod` returned no rows at all -- the price history is unreadable."]

    eod_lag = (today - latest_eod).days
    if eod_lag > MAX_EOD_LAG_DAYS:
        faults.append(
            f"No new market data for {eod_lag} days (newest `ihsg_eod` is {latest_eod}). "
            f"n8n's 17:30 WIB EOD job is the first place to look."
        )

    # Scored one day per trading day, for every liquid ticker -- so it falling
    # behind EOD means the 18:10 signal scan did not run or did not finish,
    # which is invisible from the site because the pages just show yesterday.
    if latest_scoreboard is None:
        faults.append("`daily_scoreboard` returned no rows at all.")
    elif latest_eod is not None and latest_scoreboard < latest_eod:
        faults.append(
            f"The daily scan is behind the market data: newest scoreboard {latest_scoreboard}, "
            f"newest EOD {latest_eod}. `paper_signal_scan_v4_trigger.yml` did not complete."
        )

    # Only meaningful on a day the market actually traded.
    market_traded_recently = eod_lag <= MAX_EOD_LAG_DAYS
    if is_weekday and market_traded_recently:
        if hours_since_monitor is None:
            faults.append(
                "No successful V4 monitor run found at all in recent history. Open positions "
                "are not being checked against their stop or target."
            )
        elif hours_since_monitor > MAX_MONITOR_GAP_HOURS:
            faults.append(
                f"No successful V4 monitor run for {hours_since_monitor:.1f} hours. Open positions "
                f"are not being checked against their stop or target. Most likely cause: the "
                f"GitHub token inside n8n's `Trigger Paper Monitor` node has expired."
            )

    return faults


def _latest_date(url: str, key: str, table: str, column: str) -> date | None:
    r = requests.get(
        f"{url}/rest/v1/{table}",
        params={"select": column, "order": f"{column}.desc", "limit": "1"},
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    return datetime.fromisoformat(str(rows[0][column])[:10]).date()


def _hours_since_last_monitor_run() -> float | None:
    """Age of the newest SUCCESSFUL V4 monitor run, from the Actions API.

    Uses the workflow-provided GITHUB_TOKEN, so it is independent of the n8n
    PAT -- which is the whole point: the failure being watched for is that PAT
    being dead.
    """
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    r = requests.get(
        f"https://api.github.com/repos/{repo}/actions/workflows/paper_monitor_v4_trigger.yml/runs",
        params={"status": "success", "per_page": "1"},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    r.raise_for_status()
    runs = r.json().get("workflow_runs", [])
    if not runs:
        return None
    started = datetime.fromisoformat(runs[0]["run_started_at"].replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - started).total_seconds() / 3600


def _notify(text: str) -> None:
    bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_USER_ID")
    if not bot or not chat:
        print("[WATCHDOG] no Telegram credentials -- printing instead")
        print(text)
        return
    requests.post(
        f"https://api.telegram.org/bot{bot}/sendMessage",
        data={"chat_id": chat, "parse_mode": "Markdown", "text": text},
        timeout=30,
    )


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        # Cannot check, so say so rather than exit 0 and look healthy. A
        # watchdog that goes quiet when it breaks is worse than no watchdog.
        _notify("🚨 *[WATCHDOG] Cannot run* -- SUPABASE_URL/SUPABASE_KEY missing. The unattended health check is BLIND.")
        return 1

    try:
        latest_eod = _latest_date(url, key, "ihsg_eod", "trade_date")
        latest_scoreboard = _latest_date(url, key, "daily_scoreboard", "trade_date")
        hours = _hours_since_last_monitor_run()
    except Exception as exc:  # noqa: BLE001 -- any failure here must be loud
        _notify(f"🚨 *[WATCHDOG] Health check itself failed*: `{type(exc).__name__}: {exc}`. Treat the system as unverified.")
        return 1

    now_wib = datetime.now(WIB)
    faults = decide(
        today=now_wib.date(),
        latest_eod=latest_eod,
        latest_scoreboard=latest_scoreboard,
        hours_since_monitor=hours,
        is_weekday=now_wib.weekday() < 5,
    )

    if not faults:
        print(f"[WATCHDOG] healthy -- eod={latest_eod} scoreboard={latest_scoreboard} monitor_age={hours}")
        return 0

    body = "\n".join(f"• {f}" for f in faults)
    _notify(f"🚨 *[WATCHDOG] The unattended system needs attention*\n\n{body}\n\nSee `docs/HIBERNATION_STATE.md`.")
    print("[WATCHDOG] FAULTS:\n" + body)
    return 1


def _selftest() -> None:
    """One runnable check per branch, so a refactor cannot silently disarm this."""
    t = date(2026, 9, 12)  # a Saturday

    assert decide(today=t, latest_eod=date(2026, 9, 11), latest_scoreboard=date(2026, 9, 11),
                  hours_since_monitor=2.0, is_weekday=True) == []

    # The real measured state on the day this was written: monitor 40.9h of
    # `updated_at` staleness is NOT a fault, because the age below comes from
    # the Actions API, not from that column.
    assert decide(today=t, latest_eod=date(2026, 9, 11), latest_scoreboard=date(2026, 9, 11),
                  hours_since_monitor=40.9, is_weekday=True), "a 40.9h monitor gap must fault"

    # Weekend: EOD one day old, no monitor runs -- healthy, the market is shut.
    assert decide(today=t, latest_eod=date(2026, 9, 11), latest_scoreboard=date(2026, 9, 11),
                  hours_since_monitor=None, is_weekday=False) == []

    # Long IDX holiday: 4 days is past the lag limit and must speak up.
    assert any("No new market data" in f for f in decide(
        today=t, latest_eod=date(2026, 9, 8), latest_scoreboard=date(2026, 9, 8),
        hours_since_monitor=1.0, is_weekday=True))

    # Scan behind the market: the silent failure the pages cannot show.
    assert any("daily scan is behind" in f for f in decide(
        today=t, latest_eod=date(2026, 9, 11), latest_scoreboard=date(2026, 9, 10),
        hours_since_monitor=1.0, is_weekday=True))

    # Never any rows at all.
    assert decide(today=t, latest_eod=None, latest_scoreboard=None,
                  hours_since_monitor=1.0, is_weekday=True)

    print("hibernation_watchdog selftest: all checks passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        raise SystemExit(main())
