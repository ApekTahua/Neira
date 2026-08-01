"""disclosure_extract.py -- extracts text from disclosure PDF attachments,
so important disclosures (already curated down from ~27,000 to ~1,500 by
the nightly prune_unimportant_disclosures() Supabase job -- see
supabase/migrations in newscraper.ai) become searchable/summarizable
instead of just a headline + a PDF link.

Two-stage extraction, cheapest first:
  1. pdfplumber -- most IDX filing PDFs are native/machine-generated
     (financial statements often ship with an inlineXBRL.zip alongside,
     a strong sign the PDF itself has a real text layer), so plain text
     extraction covers the majority.
  2. pytesseract OCR (via pdf2image -> page images) as a fallback when
     stage 1 comes back empty -- catches scanned documents.
  A PDF that is actually a slide/PPT export with no real text and no
  clean page images (the user's own observation: the *second* attachment
  link is often exactly this) will still fail both stages -- expected,
  recorded as method='failed', not treated as an error.

Picks the FIRST .pdf attachment per disclosure as the representative
document (same reasoning: the first link is the one most likely to be
the actual filing, not a slide deck).

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... python src/disclosure_extract.py
"""

import io
import os
import sys

import cloudscraper
import pdfplumber
from supabase import create_client

import paper_common as pc  # run_guarded() is a generic crash-alerter, not paper-trading-specific

# IDX's static file server sits behind Cloudflare and 403s plain requests
# (a JS "Just a moment..." challenge) -- cloudscraper solves it. Confirmed
# against a real filing PDF during development; plain `requests` does not
# work here at all, not even with browser-like headers.
_scraper = cloudscraper.create_scraper()

MIN_CHARS = 50  # below this, treat pdfplumber's output as "no real text layer"
MAX_OCR_PAGES = 5  # OCR is slow -- cap it so one huge filing doesn't stall the whole run
BATCH_LIMIT = 200  # per run -- keeps each GitHub Actions job well within its time budget


def _first_pdf_url(attachments) -> str | None:
    for a in attachments or []:
        url = a.get("full_url", "")
        if url.lower().endswith(".pdf"):
            return url
    return None


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t:
                text_parts.append(t)
    return "\n".join(text_parts).strip()


def _extract_via_ocr(pdf_bytes: bytes) -> str:
    from pdf2image import convert_from_bytes
    import pytesseract

    images = convert_from_bytes(pdf_bytes, first_page=1, last_page=MAX_OCR_PAGES)
    text_parts = [pytesseract.image_to_string(img) for img in images]
    return "\n".join(t.strip() for t in text_parts if t.strip()).strip()


def main():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")
    supabase = create_client(url, key)

    done_res = supabase.table("disclosure_extracts").select("disclosure_id").execute()
    already_done = {r["disclosure_id"] for r in done_res.data}

    disclosures_res = supabase.table("disclosures_flat").select("disclosure_id, ticker, title, attachments").execute()
    pending = [r for r in disclosures_res.data if r["disclosure_id"] not in already_done]
    print(f"[EXTRACT] {len(pending)} disclosures without an extract yet (of {len(disclosures_res.data)} total).")

    for row in pending[:BATCH_LIMIT]:
        pdf_url = _first_pdf_url(row.get("attachments"))
        record = {
            "disclosure_id": row["disclosure_id"], "ticker": row["ticker"], "title": row["title"],
            "source_url": pdf_url,
        }
        if pdf_url is None:
            record.update(method="failed", extracted_text=None, char_count=0)
            supabase.table("disclosure_extracts").insert(record).execute()
            continue

        try:
            resp = _scraper.get(pdf_url, timeout=30)
            resp.raise_for_status()
            pdf_bytes = resp.content
        except Exception as e:
            print(f"  [SKIP] {row['ticker']} {row['disclosure_id']}: download failed ({e})")
            record.update(method="failed", extracted_text=None, char_count=0)
            supabase.table("disclosure_extracts").insert(record).execute()
            continue

        text, method = "", "failed"
        try:
            text = _extract_pdf_text(pdf_bytes)
            if len(text) >= MIN_CHARS:
                method = "pdf_text"
        except Exception as e:
            print(f"  [WARN] {row['ticker']}: pdfplumber failed ({e})")

        if method == "failed":
            try:
                text = _extract_via_ocr(pdf_bytes)
                if len(text) >= MIN_CHARS:
                    method = "ocr"
            except Exception as e:
                print(f"  [WARN] {row['ticker']}: OCR failed ({e})")

        record.update(method=method, extracted_text=text or None, char_count=len(text))
        supabase.table("disclosure_extracts").insert(record).execute()
        print(f"  [{method.upper()}] {row['ticker']} {row['title'][:60]!r} ({len(text)} chars)")

    print(f"[EXTRACT] done. Processed {min(len(pending), BATCH_LIMIT)}/{len(pending)}.")


if __name__ == "__main__":
    pc.run_guarded(main, "disclosure_extract.py")
