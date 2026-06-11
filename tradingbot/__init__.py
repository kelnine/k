"""Multi-instrument paper-trading bot.

Mean reversion on S&P 500 / NASDAQ (15m), momentum breakouts on Bitcoin (1h),
trend following on gold / oil (4h). ATR-based sizing, hard 1% stop per trade,
correlation filter across risk groups. Paper trading only.
"""

__version__ = "0.1.0"
