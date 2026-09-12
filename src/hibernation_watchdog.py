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

import hashlib
import io
import json
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

# HOLDOUT_PROTOCOL.md Rule 7. Scored "once, at the threshold" only works if
# somebody is told the threshold was crossed; nothing counted closed positions
# before this. 60 is the fail-only gate, 87 the point promotion becomes
# licensed (Rule 5). The message carries the COUNT ONLY -- never win rate,
# profit factor or P&L -- because being told the gate is open must not become
# the early read of the result that Rule 5 forbids.
GATE_THRESHOLDS = (60, 87)

# Which columns of a CLOSED position can never legitimately change again.
# Fetched as ::text so the hash is exact: PostgREST renders `numeric` as a JSON
# number, and a float round-trip could move the digest without the data moving.
ATTESTED_COLUMNS = (
    "id", "stock_code", "signal_date", "entry_date", "exit_date",
    "entry_price_original::text", "avg_price::text", "total_lots",
    "exit_price::text", "exit_reason", "pnl::text", "pnl_pct::text",
)

# Where the expected digest lives. In the repo on purpose -- git makes the
# baseline itself tamper-evident, which a value stored next to the data it
# attests would not be.
ATTESTATION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "docs", "attestation_v4_closed.json")


def gate_notices(closed_count: int) -> list[str]:
    """HOLDOUT_PROTOCOL Rule 7. Count only, deliberately.

    Fires every day once a threshold is passed rather than only on the crossing
    day. That is a choice, not an oversight: there is no state store here, and a
    gate that matters once in five months should nag rather than risk being
    missed because the one day it spoke was the one day nobody read Telegram.
    """
    out = []
    for t in GATE_THRESHOLDS:
        if closed_count >= t:
            out.append(
                f"V4_PAPER has reached {closed_count} closed positions, past the {t} mark. "
                f"See HOLDOUT_PROTOCOL.md -- 60 can only rule OUT, promotion needs 87."
            )
    return out


def attestation_faults(expected: dict | None, actual: dict) -> list[str]:
    """T-10. Closed positions are the published track record; once a position
    is closed its numbers are history and must never move again. This compares
    the live rows against a digest committed to the repo.

    Only rows closed on or before the baseline's own cutoff are hashed, so
    ordinary new closures append past the cutoff and leave the digest alone. A
    mismatch therefore means a historical row was edited or deleted -- the one
    thing that should never happen.
    """
    if expected is None:
        return ["No attestation baseline found (`docs/attestation_v4_closed.json`). The published track record is unverified."]
    if expected.get("cutoff") != actual.get("cutoff"):
        return [f"Attestation cutoff mismatch: baseline {expected.get('cutoff')}, computed {actual.get('cutoff')}. Cannot compare."]
    if expected.get("rowcount") != actual.get("rowcount"):
        return [
            f"**The closed-position history changed.** Baseline held {expected.get('rowcount')} rows "
            f"closed on or before {expected.get('cutoff')}; there are now {actual.get('rowcount')}. "
            f"Rows that were already closed must never be added or removed."
        ]
    if expected.get("sha256") != actual.get("sha256"):
        return [
            f"**The closed-position history changed.** Row count still {actual.get('rowcount')}, but the digest "
            f"differs: baseline `{str(expected.get('sha256'))[:12]}`, computed `{str(actual.get('sha256'))[:12]}`. "
            f"An already-closed position's numbers were edited."
        ]
    return []


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


def _v4_run_id(url: str, key: str) -> str | None:
    r = requests.get(
        f"{url}/rest/v1/backtest_runs",
        params={"select": "id", "version": "eq.V4_PAPER", "limit": "1"},
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=30,
    )
    r.raise_for_status()
    rows = r.json()
    return str(rows[0]["id"]) if rows else None


def _closed_positions(url: str, key: str, run_id: str, cutoff: str) -> list[dict]:
    r = requests.get(
        f"{url}/rest/v1/paper_positions",
        params={
            "select": ",".join(ATTESTED_COLUMNS),
            "run_id": f"eq.{run_id}",
            "status": "eq.CLOSED",
            "exit_date": f"lte.{cutoff}",
            "order": "id.asc",
        },
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _closed_count(url: str, key: str, run_id: str) -> int:
    r = requests.get(
        f"{url}/rest/v1/paper_positions",
        params={"select": "id", "run_id": f"eq.{run_id}", "status": "eq.CLOSED"},
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Prefer": "count=exact", "Range": "0-0"},
        timeout=30,
    )
    r.raise_for_status()
    return int(r.headers.get("content-range", "0-0/0").split("/")[-1])


def digest(rows: list[dict], cutoff: str) -> dict:
    """Canonical, order-stable digest. Column order is ATTESTED_COLUMNS, rows
    are ordered by id by the query, and every value is already text or an
    integer -- so the same database state always produces the same hash."""
    names = [c.split("::")[0] for c in ATTESTED_COLUMNS]
    lines = ["|".join("" if r.get(n) is None else str(r.get(n)) for n in names) for r in rows]
    payload = "\n".join(lines).encode("utf-8")
    return {"cutoff": cutoff, "rowcount": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}


def _load_baseline() -> dict | None:
    try:
        with io.open(ATTESTATION_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _safe_print(text: str) -> None:
    """A console that cannot render the character must not take the message down
    with it. Found by running the failure path rather than the happy one: the
    emoji prefix raised UnicodeEncodeError on a cp1252 terminal, inside the
    notifier, so the alert was lost AND the traceback replaced it."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = (sys.stdout.encoding or "ascii")
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def _notify(text: str) -> None:
    """Never raises. A notifier that throws is the failure it exists to report:
    the caller still returns non-zero, but the message has to get out first.
    Every path here also prints, so the Actions log carries the alert even when
    Telegram is down."""
    bot = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_USER_ID")
    if not bot or not chat:
        _safe_print("[WATCHDOG] no Telegram credentials -- printing instead")
        _safe_print(text)
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            data={"chat_id": chat, "parse_mode": "Markdown", "text": text},
            timeout=30,
        )
        if r.status_code != 200:
            _safe_print(f"[WATCHDOG] Telegram refused the message ({r.status_code}) -- printing instead")
            _safe_print(text)
    except Exception as exc:  # noqa: BLE001 -- the alert matters more than the transport
        _safe_print(f"[WATCHDOG] Telegram send failed ({type(exc).__name__}) -- printing instead")
        _safe_print(text)


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        # Cannot check, so say so rather than exit 0 and look healthy. A
        # watchdog that goes quiet when it breaks is worse than no watchdog.
        _notify("🚨 *[WATCHDOG] Cannot run* -- SUPABASE_URL/SUPABASE_KEY missing. The unattended health check is BLIND.")
        return 1

    baseline = _load_baseline()
    try:
        latest_eod = _latest_date(url, key, "ihsg_eod", "trade_date")
        latest_scoreboard = _latest_date(url, key, "daily_scoreboard", "trade_date")
        hours = _hours_since_last_monitor_run()
        run_id = _v4_run_id(url, key)
        closed_count = _closed_count(url, key, run_id) if run_id else 0
        attested = None
        if run_id and baseline:
            rows = _closed_positions(url, key, run_id, baseline["cutoff"])
            attested = digest(rows, baseline["cutoff"])
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
    if run_id is None:
        faults.append("No V4_PAPER run found in `backtest_runs` -- the live arm is unidentifiable.")
    else:
        faults += attestation_faults(baseline, attested or {})

    notices = gate_notices(closed_count)

    if notices:
        body = "\n".join(f"• {n}" for n in notices)
        _notify(f"📋 *[HOLDOUT] Sample threshold reached*\n\n{body}")
        print("[WATCHDOG] NOTICES:\n" + body)

    if not faults:
        print(f"[WATCHDOG] healthy -- eod={latest_eod} scoreboard={latest_scoreboard} "
              f"monitor_age={hours} closed={closed_count} attested={bool(attested)}")
        return 0

    body = "\n".join(f"• {f}" for f in faults)
    _notify(f"🚨 *[WATCHDOG] The unattended system needs attention*\n\n{body}\n\nSee `docs/HIBERNATION_STATE.md`.")
    print("[WATCHDOG] FAULTS:\n" + body)
    return 1


def emit_attestation(cutoff: str) -> int:
    """Writes the baseline this check compares against. Run by hand, reviewed in
    the diff, committed -- never regenerated automatically, because a baseline
    that rewrites itself attests nothing."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_KEY required")
        return 1
    run_id = _v4_run_id(url, key)
    if run_id is None:
        print("no V4_PAPER run found")
        return 1
    rows = _closed_positions(url, key, run_id, cutoff)
    out = digest(rows, cutoff)
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    out["columns"] = list(ATTESTED_COLUMNS)
    out["note"] = (
        "T-10. Digest of V4_PAPER positions CLOSED on or before `cutoff`. Those rows are the "
        "published track record and must never change again; new closures land past the cutoff "
        "and do not affect this. A mismatch means history was edited. Advance the cutoff "
        "deliberately, in a reviewed commit, never automatically."
    )
    with io.open(ATTESTATION_FILE, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {ATTESTATION_FILE}: {out['rowcount']} rows, sha256 {out['sha256'][:16]}...")
    return 0


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

    # --- HOLDOUT_PROTOCOL Rule 7: the gate announces itself, count only ---
    assert gate_notices(11) == [], "11 closed is not a threshold"
    assert gate_notices(59) == []
    assert len(gate_notices(60)) == 1, "60 must announce"
    assert len(gate_notices(87)) == 2, "87 is past both marks"
    for msg in gate_notices(87):
        low = msg.lower()
        for banned in ("win rate", "profit factor", "pnl", "p&l", "alpha", "%"):
            assert banned not in low, f"gate notice leaked a performance figure: {banned}"

    # --- T-10 attestation ---
    base = {"cutoff": "2026-09-11", "rowcount": 2, "sha256": "abc"}
    assert attestation_faults(base, {"cutoff": "2026-09-11", "rowcount": 2, "sha256": "abc"}) == []
    assert attestation_faults(None, {}), "a missing baseline is itself a fault"
    assert any("history changed" in f for f in attestation_faults(
        base, {"cutoff": "2026-09-11", "rowcount": 1, "sha256": "abc"})), "a deleted row must fault"
    assert any("history changed" in f for f in attestation_faults(
        base, {"cutoff": "2026-09-11", "rowcount": 2, "sha256": "zzz"})), "an edited row must fault"
    assert any("cutoff mismatch" in f for f in attestation_faults(
        base, {"cutoff": "2026-09-10", "rowcount": 2, "sha256": "abc"}))

    # digest is order-stable and reacts to any field moving
    r1 = [{"id": 1, "stock_code": "AAA", "pnl": "10.5000"}, {"id": 2, "stock_code": "BBB", "pnl": None}]
    r2 = [{"id": 1, "stock_code": "AAA", "pnl": "10.5000"}, {"id": 2, "stock_code": "BBB", "pnl": None}]
    assert digest(r1, "x")["sha256"] == digest(r2, "x")["sha256"], "same data must hash the same"
    r3 = [{"id": 1, "stock_code": "AAA", "pnl": "10.5001"}, {"id": 2, "stock_code": "BBB", "pnl": None}]
    assert digest(r1, "x")["sha256"] != digest(r3, "x")["sha256"], "a 0.0001 change must move the hash"

    # --- the notifier must survive a console that cannot render the message ---
    # Regression guard for a real crash: the emoji prefix raised
    # UnicodeEncodeError on cp1252, inside _notify, losing the alert entirely.
    import contextlib, io as _io
    buf = _io.TextIOWrapper(_io.BytesIO(), encoding="cp1252", errors="strict")
    with contextlib.redirect_stdout(buf):
        _notify("\U0001f6a8 alarm with an emoji in it")
    buf.seek(0)
    assert "alarm with an emoji" in buf.read(), "the alert text must survive an unrenderable character"

    print("hibernation_watchdog selftest: all checks passed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif "--emit-attestation" in sys.argv:
        i = sys.argv.index("--emit-attestation")
        raise SystemExit(emit_attestation(sys.argv[i + 1]))
    else:
        raise SystemExit(main())
