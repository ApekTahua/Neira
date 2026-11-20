"""External heartbeat for Neira data freshness (audit L-004).

Runs on GitHub Actions, independent of n8n. Reads DB1 over the public REST API
with the anon key (SELECT only). Exits 1 with a clear message on any failure,
which makes GitHub email the repo owner.

Env: HEARTBEAT_DB1_URL, HEARTBEAT_DB1_ANON_KEY
"""
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))
URL = os.environ["HEARTBEAT_DB1_URL"].rstrip("/")
KEY = os.environ["HEARTBEAT_DB1_ANON_KEY"]


def get(path):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}",
                                 headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.load(r)
    if not rows:
        sys.exit(f"Cek data harian gagal: tabel {path.split('?')[0]} kosong. Cek database.")
    return rows[0]


def last_weekday_on_or_before(d):
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def weekdays_between(a, b):
    """Weekdays in (a, b]."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        n += d.weekday() < 5
    return n


now = datetime.now(WIB)
today = now.date()
evening = now.hour >= 20
# Last trading day we expect data for. Evening run: today. Morning run: yesterday.
expected = last_weekday_on_or_before(today if evening else today - timedelta(days=1))

eod = date.fromisoformat(get("ihsg_eod?select=trade_date&stock_code=eq.BBCA&order=trade_date.desc&limit=1")["trade_date"])
idx = date.fromisoformat(get("index_eod?select=trade_date&index_code=eq.COMPOSITE&order=trade_date.desc&limit=1")["trade_date"])
gate = get("daily_gate_summary?select=trade_date,regime,trend_strength&order=trade_date.desc&limit=1")
gate_d = date.fromisoformat(gate["trade_date"])
sb_d = date.fromisoformat(get("daily_scoreboard?select=trade_date&order=trade_date.desc&limit=1")["trade_date"])
rt = datetime.fromisoformat(get("ihsg_realtime?select=updated_at&order=updated_at.desc&limit=1")["updated_at"])

print(f"now_wib={now:%Y-%m-%d %H:%M} expected_last_trading_day<={expected} ihsg_eod={eod} "
      f"index_eod={idx} gate={gate_d}({gate['regime']}, trend={gate['trend_strength']}) "
      f"scoreboard={sb_d} realtime={rt.astimezone(WIB):%Y-%m-%d %H:%M}")

fails, warns = [], []

# (b) prices and index: fail only when 2+ business days behind (allows one holiday)
for name, d in (("ihsg_eod", eod), ("index_eod", idx)):
    lag = weekdays_between(d, expected)
    if lag >= 2:
        fails.append(f"Data {name} terakhir {d}, tertinggal {lag} hari bursa dari {expected}. Pengisian data (n8n) mungkin mati.")

# (c) gate + scoreboard must follow ihsg_eod, and the gate must not be the fabricated default
for name, d in (("daily_gate_summary", gate_d), ("daily_scoreboard", sb_d)):
    if d < eod:
        msg = f"{name} terakhir {d}, padahal harga saham sudah sampai {eod}. Scan harian belum menulis hari itu."
        # Evening run: the scan has catch-up slots until 22:10 WIB, so a 1-day lag is only a warning.
        (warns if evening and eod == today and weekdays_between(d, eod) == 1 else fails).append(msg)
if gate["regime"] == "NEUTRAL" and float(gate["trend_strength"]) == 0.0:
    fails.append(f"Status pasar tanggal {gate_d} berisi nilai bawaan (NETRAL, tren 0), bukan hasil hitung. Data indeks IHSG belum ada saat scan jalan.")

# (a) ihsg_realtime freshness: n8n writes it every 15 min 09:00-17:00 WIB on trading days.
# After a trading day it must hold a write from at least 14:00 WIB that day. Skip weekends and
# when the last EOD is behind the expected day (market was closed / holiday).
if today.weekday() >= 5:
    print("realtime check skipped: weekend")
elif eod < expected:
    print(f"realtime check skipped: no EOD for {expected} (holiday or ingest lag, covered by check b)")
else:
    need = datetime(eod.year, eod.month, eod.day, 14, 0, tzinfo=WIB)
    if rt < need:
        fails.append(f"Harga live terakhir masuk {rt.astimezone(WIB):%Y-%m-%d %H:%M} WIB, seharusnya ada setelah {need:%Y-%m-%d %H:%M}. Pengisian harga live (n8n) mungkin mati.")

for w in warns:
    print(f"::warning::{w}")
if fails:
    for f in fails:
        print(f"::error::Cek data harian gagal: {f}")
    run = os.environ.get("GITHUB_RUN_ID")
    if run:
        print(f"Log lengkap: {os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
              f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{run}")
    sys.exit(1)
print("Cek data harian: OK")
