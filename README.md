# Neira — IHSG Accumulation Detector

Screener saham IHSG berbasis Supabase (`ihsg_eod`, `index_eod`), jalan
harian via GitHub Actions dan kirim sinyal ke Telegram.

## Struktur

```
src/
  config.py       parameter strategi (threshold, sizing, TP/SL, dst)
  strategy.py      satu-satunya sumber logic sinyal — dipakai screener.py & backtest.py
  screener.py      entry point live (jalan tiap hari via run_screener.yml)
  backtest.py      entry point backtest historis (jalan via backtest.yml)
  notifier.py      kirim hasil screener ke Telegram
reference/          referensi Pine Script (UT Bot, SMC, Lorentzian) yang diadaptasi
.github/workflows/  backtest.yml (mingguan) + run_screener.yml (harian)
reports/             output backtest.py (grafik HTML + txt) — generated, gitignored
```

`strategy.py` wajib jadi satu-satunya tempat logic sinyal berubah — jangan
duplikasi ke `screener.py` atau `backtest.py`, supaya sinyal live selalu
konsisten dengan yang sudah divalidasi backtest.

## Menjalankan

```
pip install -r requirements.txt
SUPABASE_URL=... SUPABASE_KEY=... python src/backtest.py
SUPABASE_URL=... SUPABASE_KEY=... TELEGRAM_BOT_TOKEN=... TELEGRAM_USER_ID=... python src/screener.py
```

`backtest.py` menerima override periode via env `BACKTEST_START` /
`BACKTEST_END` (format `YYYY-MM-DD`) untuk uji out-of-sample.
