"""Hypothesis strategies shared by the indicator tests."""

from hypothesis import strategies as st

Ohlc = tuple[list[float], list[float], list[float]]


@st.composite
def ohlc_bars(draw: st.DrawFn, min_size: int = 0, max_size: int = 80) -> Ohlc:
    """Consistent random bars on a quarter-tick grid (so equal highs/lows and flat bars occur)."""
    rows = draw(
        st.lists(
            st.tuples(
                st.integers(-40, 40),  # drift of the bar's midpoint
                st.integers(0, 8),  # distance high - mid
                st.integers(0, 8),  # distance mid - low
                st.integers(0, 4),  # close position in the range, in quarters
            ),
            min_size=min_size,
            max_size=max_size,
        )
    )
    highs, lows, closes = [], [], []
    mid = 1000
    for drift, up, down, position in rows:
        mid += drift
        high, low = (mid + up) / 4, (mid - down) / 4
        highs.append(high)
        lows.append(low)
        closes.append(low + (high - low) * position / 4)
    return highs, lows, closes
