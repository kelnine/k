import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ─── Safety Lock ──────────────────────────────────────────────────────────────
LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

if LIVE_TRADING:
    print("\n" + "=" * 70)
    print("  DANGER: LIVE_TRADING=true detected.")
    print("  This bot places REAL MONEY options orders. There is NO undo.")
    print("=" * 70 + "\n")
    answer = input("Type exactly 'I ACCEPT FULL RESPONSIBILITY FOR REAL MONEY TRADES': ").strip()
    if answer != "I ACCEPT FULL RESPONSIBILITY FOR REAL MONEY TRADES":
        print("Confirmation failed. Exiting for your safety.")
        sys.exit(1)
    print("Live trading confirmed. Proceeding with extreme caution.\n")

# ─── Broker ───────────────────────────────────────────────────────────────────
BROKER = os.getenv("BROKER", "tradier").lower()

TRADIER_TOKEN = os.getenv("TRADIER_TOKEN", "")
TRADIER_ACCOUNT_ID = os.getenv("TRADIER_ACCOUNT_ID", "")
TRADIER_BASE_URL = (
    "https://api.tradier.com" if LIVE_TRADING else "https://sandbox.tradier.com"
)

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = (
    "https://api.alpaca.markets" if LIVE_TRADING else "https://paper-api.alpaca.markets"
)
ALPACA_DATA_URL = "https://data.alpaca.markets"

# ─── Unusual Whales ───────────────────────────────────────────────────────────
UNUSUAL_WHALES_TOKEN = os.getenv("UNUSUAL_WHALES_TOKEN", "")
UNUSUAL_WHALES_BASE_URL = "https://api.unusualwhales.com"

# ─── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Strategy ─────────────────────────────────────────────────────────────────
WATCHLIST = ["SPY", "QQQ", "NVDA", "TSLA", "AMD", "AAPL", "META", "MSFT"]

MIN_PREMIUM = 100_000          # Minimum total premium in USD
MAX_DTE = 14                   # Maximum days to expiration
MIN_DTE = 0                    # 0DTE included
VALID_FLOW_TYPES = ["sweep", "block"]
REPEAT_FLOW_WINDOW_MINUTES = 30    # Window to look for repeated same-direction flow
REPEAT_FLOW_MIN_COUNT = 2          # How many same-direction signals to confirm

# ─── Risk Management ──────────────────────────────────────────────────────────
STARTING_BALANCE = 5_000.0
MAX_RISK_PCT = 0.02            # 2% of account per trade
MAX_TRADES_PER_DAY = 3
STOP_LOSS_PCT = -0.30          # -30% of entry value triggers exit
TP1_PCT = 0.30                 # +30% first target
TP2_PCT = 0.60                 # +60% second target
TRAIL_AFTER_TP1 = True         # Trail stop after TP1 hit
NO_TRADE_MINUTES_AFTER_OPEN = 5   # Blackout period after market open

# ─── Scanning ─────────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS = 30
POSITION_CHECK_INTERVAL_SECONDS = 60
FLOW_FETCH_LIMIT = 100
