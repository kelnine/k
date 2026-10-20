"""Hand-built bar sequences for the ``smc_sniper`` golden tests.

They run with the script's shortest lengths (``bos_len`` 5, ``ob_len`` 3) so a
swing is a 5/5 pivot and an order block a 3/3 one; every pivot, gap and cross is
noted next to the row that makes it. Rows are ``(open, high, low, close)``.
"""

from typing import Any

Row = tuple[float, float, float, float]

SHORT_LENGTHS: dict[str, Any] = {"bos_len": 5, "ob_len": 3}


def rising(n: int, start: float = 100.0) -> list[Row]:
    """``n`` bullish bars closing ``start + 1 … start + n``, open at the previous close."""
    rows: list[Row] = []
    for k in range(1, n + 1):
        close = start + k
        rows.append((close - 1, close + 0.3, close - 1.2, close))
    return rows


# A bullish BOS on bar 23 with three points: structure (upt starts true), a bullish
# order block holding the close, and momentum. EMA200 is still na, so no trend point.
BASE: list[Row] = [
    (100, 100.5, 99.5, 100),  # 0
    *rising(9),  # 1-9: closes 101 … 109 (each leaves a small bullish gap)
    (109, 109.2, 104.8, 105),  # 10: bearish candle at a 3/3 pivot low → OB body 105-109
    (105, 106.2, 104.9, 106),  # 11
    (106, 107.2, 105.9, 107),  # 12
    (107, 107.5, 106.8, 107.3),  # 13: the OB of bar 10 is pushed
    (107.3, 108.0, 107.1, 107.8),  # 14
    (107.8, 108.4, 107.6, 108.2),  # 15
    (108.2, 108.6, 108.0, 108.3),  # 16: 5/5 pivot high 108.6
    (108.3, 108.4, 107.7, 107.8),  # 17
    (107.8, 107.9, 107.2, 107.4),  # 18
    (107.4, 107.5, 106.9, 107.0),  # 19
    (107.2, 107.3, 106.8, 107.0),  # 20: bearish, 3/3 and 5/5 pivot low 106.8
    (107.2, 107.6, 107.1, 107.5),  # 21: lsh = 108.6 (bar 16 confirmed)
    (107.5, 108.0, 107.4, 107.9),  # 22: close 107.9 <= 108.6
    (107.9, 109.0, 107.8, 108.8),  # 23: close 108.8 > 108.6 → BOS, inside the OB 105-109
]
SIGNAL_BAR = 23
LSH = 108.6

# A stale swing high (102, bar 5) below a later swing low (111.0, bar 18): the crash on
# bar 25 breaks the swing low with its stop at 102 + 0.5 ATR, under the close; the
# rebound on bar 27 breaks 102 with its stop at 111 − 0.5 ATR, above the close.
WRONG_SIDE: list[Row] = [
    *[(100, 100.4, 99.6, 100)] * 5,  # 0-4
    (100, 102, 99.9, 101.5),  # 5: 5/5 pivot high 102
    (101.5, 101.6, 100.5, 100.8),  # 6
    (100.8, 101.0, 100.2, 100.5),  # 7
    (100.5, 100.9, 100.1, 100.6),  # 8
    (100.6, 101.2, 100.4, 101.0),  # 9
    (101.0, 101.5, 100.7, 101.3),  # 10: lsh = 102
    (101.3, 101.9, 101.2, 101.8),  # 11
    (101.8, 112.4, 101.7, 112.2),  # 12: BOS of 102 while ATR(14) is still na
    (112.2, 112.8, 111.9, 112.5),  # 13
    (112.5, 113.0, 112.1, 112.6),  # 14
    (112.6, 112.9, 111.8, 112.0),  # 15
    (112.0, 112.7, 111.6, 112.4),  # 16
    (112.4, 112.6, 111.4, 111.7),  # 17
    (111.7, 111.9, 111.0, 111.3),  # 18: 5/5 pivot low 111.0
    (111.3, 113.2, 111.2, 113.0),  # 19
    (113.0, 115.2, 112.9, 115.0),  # 20
    (115.0, 117.2, 114.9, 117.0),  # 21
    (117.0, 119.2, 116.9, 119.0),  # 22
    (119.0, 121.2, 118.9, 121.0),  # 23: lsl = 111.0
    (121.0, 122.0, 120.5, 121.5),  # 24
    (121.5, 121.6, 104.9, 105.0),  # 25: crash through 111.0 → bearish BOS (CHoCH)
    (105.0, 105.2, 100.8, 101.0),  # 26: below 102
    (101.0, 103.6, 100.9, 103.5),  # 27: back above 102 → bullish BOS (CHoCH)
    (103.5, 104.0, 103.0, 103.8),  # 28
]


def mirror(rows: list[Row], axis: float = 200.0) -> list[Row]:
    """The sequence reflected around ``axis``: every bullish rule becomes its bearish
    twin (highs ↔ lows, gains ↔ losses), and ATR is unchanged."""
    return [
        (round(axis - o, 6), round(axis - low, 6), round(axis - h, 6), round(axis - c, 6))
        for o, h, low, c in rows
    ]


def ramp(n: int, start: float, end: float) -> list[Row]:
    """``n`` bars rising (or falling) evenly from ``start`` to just before ``end``, with
    wicks too small to leave gaps or pivots."""
    step = (end - start) / n
    rows: list[Row] = []
    previous = start
    for k in range(1, n + 1):
        close = round(start + k * step, 6)
        rows.append(
            (
                previous,
                round(max(previous, close) + 0.05, 6),
                round(min(previous, close) - 0.05, 6),
                close,
            )
        )
        previous = close
    return rows
