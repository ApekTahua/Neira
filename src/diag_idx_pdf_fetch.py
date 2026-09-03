"""Why does the disclosure PDF fetch 403 on GitHub Actions but not locally?

`disclosure_extract.py` has written `method='failed'` for 1,661 of 1,661 rows
since 2026-08-03 -- a month of total, silent failure. The Actions log gives the
reason plainly:

    [SKIP] MORA ...: download failed (403 Client Error: Forbidden for url:
    https://www.idx.co.id/StaticData/.../5df236df34_076591ea64.pdf)

The same URL, with the same `cloudscraper` call, returns 200 and a real
`%PDF-1.4` on a local Indonesian connection, and pdfplumber pulls 3,656
characters out of it. So the download code is not wrong; the runner is being
blocked. That points at IDX filtering datacenter IP ranges, which is not
something a local test can ever reproduce.

Before concluding "this can only run from a non-datacenter IP", it is worth
checking whether the block is beatable from inside Actions. Four strategies,
cheapest first. Only the result matters -- run this ON a runner, not locally,
where every strategy trivially passes.

  1. plain requests, no headers        (the naive baseline)
  2. requests + browser headers        (the code comment claims this fails)
  3. cloudscraper, cold               (what production does today)
  4. cloudscraper, warmed             (GET the site root first so the
                                       Cloudflare clearance cookie is set,
                                       then request the PDF on that session --
                                       the one thing production never tries)

If 4 works, the fix is three lines in disclosure_extract.py. If nothing works,
the fetch has to move to a host IDX does not block -- the self-hosted n8n box
already scrapes IDX successfully for the disclosure list itself, so it is the
obvious candidate.

Read-only diagnostic. Writes nothing, changes no config.
"""

import sys

URLS = [
    "https://www.idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/"
    "From_EREP/202609/5df236df34_076591ea64.pdf",
    "https://www.idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/"
    "From_EREP/202609/e56946def9_6efe4bf252.pdf",
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "application/pdf;q=0.8,*/*;q=0.7",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/",
    "Upgrade-Insecure-Requests": "1",
}


def verdict(resp) -> str:
    body = resp.content[:8]
    ok = resp.status_code == 200 and body.startswith(b"%PDF")
    return (f"{'PASS' if ok else 'FAIL'}  status={resp.status_code} "
            f"type={resp.headers.get('content-type', '?')[:30]} "
            f"bytes={len(resp.content)} head={body!r}")


def main() -> None:
    import requests
    import cloudscraper

    print("Where am I fetching from?")
    try:
        ip = requests.get("https://api.ipify.org", timeout=15).text
        print(f"  egress IP: {ip}")
    except Exception as e:
        print(f"  egress IP: unknown ({e})")
    print()

    for url in URLS:
        print(f"--- {url.rsplit('/', 1)[-1]} ---")

        try:
            print("  1 plain requests      :", verdict(requests.get(url, timeout=30)))
        except Exception as e:
            print(f"  1 plain requests      : EXC {type(e).__name__}: {str(e)[:80]}")

        try:
            print("  2 requests + headers  :",
                  verdict(requests.get(url, headers=BROWSER_HEADERS, timeout=30)))
        except Exception as e:
            print(f"  2 requests + headers  : EXC {type(e).__name__}: {str(e)[:80]}")

        try:
            s = cloudscraper.create_scraper()
            print("  3 cloudscraper cold   :", verdict(s.get(url, timeout=30)))
        except Exception as e:
            print(f"  3 cloudscraper cold   : EXC {type(e).__name__}: {str(e)[:80]}")

        try:
            s = cloudscraper.create_scraper()
            # Warm the session on the site root first, so any clearance cookie
            # is issued before the static-file request. Production never does
            # this -- it goes straight at the PDF with a cold session.
            root = s.get("https://www.idx.co.id/", headers=BROWSER_HEADERS, timeout=30)
            print(f"  4 cloudscraper warmed : (root {root.status_code}, "
                  f"{len(s.cookies)} cookies) ", end="")
            print(verdict(s.get(url, headers=BROWSER_HEADERS, timeout=30)))
        except Exception as e:
            print(f"  4 cloudscraper warmed : EXC {type(e).__name__}: {str(e)[:80]}")
        print()

    print("PASS on any strategy = fixable inside GitHub Actions.")
    print("All FAIL = the fetch must move to a host IDX does not block.")


if __name__ == "__main__":
    sys.exit(main())
