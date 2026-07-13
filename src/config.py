"""Shared configuration for the Quant Screener pipeline."""

# ----------------------------------------------------------------------
# Data range
# ----------------------------------------------------------------------
LOOKBACK_DAYS = 280                   # ~200 hari bursa — cukup untuk SMA200 (samakan dgn backtest)

# ----------------------------------------------------------------------
# Red‑flag filters
# ----------------------------------------------------------------------
MIN_LIQUIDITY_VOL = 100_000
SLEEPING_PRICE = 50
SLEEPING_FLAT_DAYS = 10

# ----------------------------------------------------------------------
# Squeeze & volume thresholds (relaxed for bear market)
# ----------------------------------------------------------------------
MA_SQUEEZE_THRESHOLD = 6.0      # was 3.0 → 6.0
BB_SQUEEZE_THRESHOLD = 10.0     # was 5.0 → 10.0
VOL_SPIKE_MULT = 1.5            # was 2.0 → 1.5

# ----------------------------------------------------------------------
# Price constraint
# ----------------------------------------------------------------------
FLAT_RANGE = 0.02               # ±2% daily return

# ----------------------------------------------------------------------
# Scoring caps
# ----------------------------------------------------------------------
SCORE_MA_SPREAD_MAX = 8.0
SCORE_BB_WIDTH_MAX = 12.0
SCORE_VOL_MULT_MAX = 5.0

# ----------------------------------------------------------------------
# UT Bot (ATR trailing stop) — adapted from TradingView ut_bot.pine
# ----------------------------------------------------------------------
UT_ATR_PERIOD = 10               # ATR lookback
UT_MULTIPLIER = 1                 # sensitivity (a in the Pine script)
UT_ATR_ESTIMATE = "close_change"  # we lack high/low, so use |close-prev|

# ----------------------------------------------------------------------
# SMC (Smart Money Concepts) — adapted from LuxAlgo
# ----------------------------------------------------------------------
SMC_SWING_PERIOD = 5            # lookback for swing high/low detection
SMC_OB_BUFFER_PCT = 0.02        # ±2% zone around swing low = buy area

# ----------------------------------------------------------------------
# Market regime multipliers
# ----------------------------------------------------------------------
MARKET_BULLISH_MULT = 1.0
MARKET_NEUTRAL_MULT = 0.8
MARKET_BEARISH_MULT = 0.5

# ----------------------------------------------------------------------
# Supabase table names
# ----------------------------------------------------------------------
TABLE_IHSG_EOD = "ihsg_eod"
TABLE_INDEX_EOD = "index_eod"

# ----------------------------------------------------------------------
# Lorentzian-inspired multi-feature filters
# ----------------------------------------------------------------------
RSI_PERIOD = 14
RSI_OVERSOLD = 30                     # RSI di atas ini = tidak oversold
ADX_PERIOD = 14
ADX_THRESHOLD = 20                    # ADX > 20 = trending
SMA_TREND_PERIOD = 200                # harga di atas SMA200 = uptrend

# ----------------------------------------------------------------------
# Entry & exit parameters
# ----------------------------------------------------------------------
MAX_HOLD_DAYS = 20                    # time-based exit setelah 20 hari
MIN_CONFIDENCE_THRESHOLD = 35.0       # abaikan sinyal di bawah skor ini
ATR_TP_MULTIPLIER = 1.5              # TP = entry + 1.5 × ATR
ATR_SL_MULTIPLIER = 1.5              # SL = entry - 1.5 × ATR (lebih longgar)

# ----------------------------------------------------------------------
# Regime-adaptive parameters
# ----------------------------------------------------------------------
# Threshold confidence: minimum confidence untuk entry di tiap regime
CONF_BULLISH = 20                     # lebih longgar di bullish
CONF_NEUTRAL = 40
CONF_BEARISH = 60

# Max posisi per regime
MAX_POS_BULLISH = 6                  # 6 posisi di bull
MAX_POS_NEUTRAL = 3
MAX_POS_BEARISH = 2

# Alokasi maksimum per posisi (% dari equity, bukan cash — lihat backtest_runner)
ALLOC_BULLISH = 0.30                 # max 30% equity per posisi di bull
ALLOC_NEUTRAL = 0.20                 # max 20% di neutral
ALLOC_BEARISH = 0.10                 # max 10% di bearish

# SL/TP multiplier per regime
# Bullish: SL ketat (proteksi profit), trailing stop untuk profit
# Bearish: SL ketat, TP dekat
SL_BULLISH = 1.5
SL_NEUTRAL = 1.5
SL_BEARISH = 1.5
TP_BULLISH = 2.0                     # TP1 di bullish
TP_NEUTRAL = 1.5
TP_BEARISH = 1.5

# ----------------------------------------------------------------------
# TP1 + Trailing Stop (Enhancement 1)
# ----------------------------------------------------------------------
TP1_PCT = 0.10                       # ambil 10% profit di TP1 (sisanya ride trailing)
TP1_MULT = 1.5                       # TP1 = 1.5 × ATR
TRAILING_PCT = 0.08                  # trailing stop 8% dari harga tertinggi

# ----------------------------------------------------------------------
# Eksekusi realistis (Enhancement 5)
# ----------------------------------------------------------------------
GAP_MAX = 0.10                       # skip entry jika open T+1 gap >10% dari close sinyal
LIQ_CAP_PCT = 0.10                   # posisi maks 10% dari avg volume 20 hari
RISK_PCT = 0.04                      # risiko per trade maks 4% equity (jarak entry-SL)

# ----------------------------------------------------------------------
# Filter requirements per regime (Enhancement 4)
# ----------------------------------------------------------------------
# Bullish: cukup 2 dari 4 kondisi, prioritaskan foreign flow + price
# Neutral/Bearish: 4 dari 4 kondisi
BULLISH_MIN_CONDITIONS = 2
NEUTRAL_MIN_CONDITIONS = 4
BEARISH_MIN_CONDITIONS = 4

# ----------------------------------------------------------------------
# ML Ensemble parameters (disabled — tidak cocok untuk strategi ini)
# ----------------------------------------------------------------------
ML_ENABLED = False

# ----------------------------------------------------------------------
# Foreign flow (Bandamologi)
# ----------------------------------------------------------------------
FOREIGN_LOOKBACK = 5            # rata-rata foreign flow 5 hari
FOREIGN_NET_MIN = 0.0           # minimal foreign net ratio untuk sinyal positif
FOREIGN_SCORE_WEIGHT = 0.10     # bobot foreign flow di confidence scoring

# ----------------------------------------------------------------------
# Organic allocation
# ----------------------------------------------------------------------
ALLOC_BASE_PCT = 0.30           # base allocation = confidence/100 × 30% cash
ALLOC_MAX_PCT = 0.30            # maks 30% cash per posisi
ALLOC_MIN_LOTS = 1              # minimal 1 lot