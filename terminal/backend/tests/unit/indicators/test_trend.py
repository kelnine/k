import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import Change, Dmi, Sar, SuperTrend, SuperTrendValue, feed
from tests.unit.indicators.reference import (
    assert_series_close,
    ref_dmi,
    ref_sar,
    ref_supertrend,
)
from tests.unit.indicators.strategies import Ohlc, ohlc_bars

NAN = math.nan


# ── ta.dmi ───────────────────────────────────────────────────────────────────────────


def test_dmi_hand_vector() -> None:
    # up/down moves: b1 +2/-1, b2 -1/+2, b3 +2/-3, b4 -1/-1 → +DM 2,0,2,0  −DM 0,2,0,0
    # ta.tr (na on bar 0): 3, 4, 5, 1 → RMA2: 3.5, 4.25, 2.625
    # +DM RMA2: 1, 1.5, 0.75; −DM RMA2: 1, 0.5, 0.25 → DI+ 200/7, 600/17, 200/7; DI− 200/7,
    # 200/17, 200/21; |DI+ − DI−| / sum: 0, 0.5, 0.5 → ADX RMA2 seeded on bar 3: 25, 37.5
    highs, lows = [10.0, 12.0, 11.0, 13.0, 12.0], [8.0, 9.0, 7.0, 10.0, 11.0]
    closes = [9.0, 11.0, 8.0, 12.0, 11.5]
    out = feed(Dmi(2, 2).update, highs, lows, closes)
    assert_series_close([v.plus for v in out], [NAN, NAN, 200 / 7, 600 / 17, 200 / 7], 1e-12)
    assert_series_close([v.minus for v in out], [NAN, NAN, 200 / 7, 200 / 17, 200 / 21], 1e-12)
    assert_series_close([v.adx for v in out], [NAN, NAN, NAN, 25.0, 37.5], 1e-12)


def test_dmi_directional_movement_uses_the_pine_tolerance() -> None:
    # high 1.1 → 1.4 and low 0.7 → 0.4: both moves are 0.3, but the float differences
    # disagree in the 17th digit (down is 5.5e-17 larger); Pine sees equal moves: no DM
    assert (1.4 - 1.1) != (0.7 - 0.4)
    out = feed(Dmi(1, 1).update, [1.1, 1.4], [0.7, 0.4], [0.9, 0.9])
    assert out[1].plus == 0.0 and out[1].minus == 0.0


def test_dmi_flat_start_is_fixed_by_fixnan() -> None:
    # a perfectly flat start: trur = 0 → 0/0 is na → fixnan has nothing to carry yet
    flat = feed(Dmi(2, 2).update, [5.0] * 4, [5.0] * 4, [5.0] * 4)
    assert all(math.isnan(v.plus) for v in flat)
    # bar 1 moves up (DI+ 100); bar 2 is flat at the previous close (TR 0 → 0/0 = na),
    # so fixnan carries the previous DI values instead of dropping to na
    out = feed(Dmi(1, 1).update, [5.0, 6.0, 6.0], [4.0, 5.0, 6.0], [5.0, 6.0, 6.0])
    assert (out[1].plus, out[1].minus) == (100.0, 0.0)
    assert (out[2].plus, out[2].minus) == (100.0, 0.0)


def test_dmi_lengths_must_be_positive() -> None:
    with pytest.raises(ValueError, match="di_length must be >= 1"):
        Dmi(0, 14)
    with pytest.raises(ValueError, match="adx_smoothing must be >= 1"):
        Dmi(14, 0)


@given(ohlc_bars(), st.integers(1, 6), st.integers(1, 6))
def test_dmi_matches_reference(bars: Ohlc, n: int, smooth: int) -> None:
    highs, lows, closes = bars
    out = feed(Dmi(n, smooth).update, highs, lows, closes)
    plus, minus, adx = ref_dmi(highs, lows, closes, n, smooth)
    assert_series_close([v.plus for v in out], plus, tol=1e-8)
    assert_series_close([v.minus for v in out], minus, tol=1e-8)
    assert_series_close([v.adx for v in out], adx, tol=1e-8)


# ── ta.sar ───────────────────────────────────────────────────────────────────────────

HIGHS = [10.0, 11.0, 12.0, 11.0, 10.0, 9.0, 10.0, 11.0, 12.0, 13.0]
LOWS = [h - 1 for h in HIGHS]
CLOSES = [h - 0.5 for h in HIGHS]


def test_sar_hand_vector() -> None:
    # bar 1: close up → long, SAR = low[1] = 9, EP 11; projected 9.04 clamped to low[1] = 9
    # bar 2: new high 12 → EP 12, af .04; SAR min(9.04, 10, 9) = 9
    # bar 3: 9 + .04 * (12 - 9) = 9.12
    # bar 4: 9.12 + .04 * 2.88 = 9.2352 > low 9 → reverse short: SAR = max(high, EP) = 12, EP 9
    # bar 5: 12 + .02 * (9 - 12) = 11.94; new low 8 → EP 8, af .04
    # bars 6-7: 11.7824, 11.631104; bar 8: projected 11.48585984 < high 12 → long at min(11, 8)
    # bar 9: 8 + .02 * (12 - 8) = 8.08
    expected = [NAN, 9.0, 9.0, 9.12, 12.0, 11.94, 11.7824, 11.631104, 8.0, 8.08]
    assert_series_close(feed(Sar().update, HIGHS, LOWS, CLOSES), expected, tol=1e-12)


def test_sar_starts_short_when_the_second_close_is_not_higher() -> None:
    sar = Sar()
    before_bar_one = sar.is_long
    out = feed(sar.update, [10.0, 9.5, 9.0], [9.0, 8.5, 8.0], [9.5, 9.0, 8.5])
    # bar 1: short at high[1] = 10, projected 9.97 clamped up to 10; bar 2: EP 8, af .04
    assert_series_close(out, [NAN, 10.0, 10.0])
    assert before_bar_one is None
    assert sar.is_long is False
    assert sar.extreme_point == 8.0 and sar.acceleration == pytest.approx(0.04)
    assert sar.projected() == pytest.approx(10 + 0.04 * (8 - 10))


def test_sar_can_reverse_on_the_initialisation_bar() -> None:
    # pine_sar runs the projection and reversal test on bar 1 too: the long start at 9
    # projects 9.06 > low 8, so bar 1 already flips short at max(high, EP) = 12
    sar = Sar()
    out = feed(sar.update, [10.0, 12.0], [9.0, 8.0], [9.5, 10.0])
    assert_series_close(out, [NAN, 12.0])
    assert sar.is_long is False


def test_sar_acceleration_is_capped() -> None:
    sar = Sar(0.1, 0.1, 0.25)
    highs = [10.0 + i for i in range(8)]
    feed(sar.update, highs, [h - 1 for h in highs], [h - 0.5 for h in highs])
    assert sar.is_long is True and sar.acceleration == 0.25


def test_sar_skips_na_bars() -> None:
    sar = Sar()
    assert math.isnan(sar.update(10.0, 9.0, 9.5))
    assert math.isnan(sar.update(NAN, 9.0, 9.5))
    assert math.isnan(sar.value)
    assert sar.update(11.0, 10.0, 10.5) == 9.0  # the na bar did not count as bar 1


def test_sar_parameters_must_be_finite_numbers() -> None:
    with pytest.raises(ValueError, match="start must be finite"):
        Sar(start=NAN)
    with pytest.raises(ValueError, match="maximum must be a number"):
        Sar(maximum="0.2")  # type: ignore[arg-type]


@given(
    ohlc_bars(),
    st.sampled_from([(0.02, 0.02, 0.2), (0.1, 0.05, 0.3), (0.25, 0.25, 0.13)]),
)
def test_sar_matches_reference(bars: Ohlc, params: tuple[float, float, float]) -> None:
    highs, lows, closes = bars
    out = feed(Sar(*params).update, highs, lows, closes)
    assert_series_close(out, ref_sar(highs, lows, closes, *params), tol=0.0)


# ── ta.supertrend ────────────────────────────────────────────────────────────────────


def test_supertrend_hand_vector() -> None:
    # ATR(2) via TR 2, 2, 2.5, 2, 3.5, 3 → -, 2, 2.25, 2.125, 2.8125, 2.90625; factor 1
    # b0: nz(prev bands) = 0 → (0, 1); b1: up 12 (direction forced to 1 while atr[1] is na)
    # b2: upper ratchets at 12, close 12.5 > 12 → up trend (-1), line = lower 9.75   ← BUY
    # b3: lower 10.875; b4: lower holds at 10.875, close 10.5 < it → down trend, line =
    # upper 14.3125 ← SELL; b5: upper 12.40625
    highs, lows = [10.0, 11.0, 13.0, 14.0, 13.0, 11.0], [8.0, 9.0, 11.0, 12.0, 10.0, 8.0]
    closes = [9.0, 10.5, 12.5, 13.5, 10.5, 8.5]
    supertrend = SuperTrend(factor=1.0, atr_period=2)
    out = feed(supertrend.update, highs, lows, closes)
    assert out == [
        SuperTrendValue(0.0, 1),
        SuperTrendValue(12.0, 1),
        SuperTrendValue(9.75, -1),
        SuperTrendValue(10.875, -1),
        SuperTrendValue(14.3125, 1),
        SuperTrendValue(12.40625, 1),
    ]
    assert supertrend.atr == 2.90625
    # Jetstream's flip = ta.change(dir): -2 is BUY, +2 is SELL
    flips = feed(Change().update, [float(v.direction) for v in out])
    assert_series_close(flips, [NAN, 0.0, -2.0, 0.0, 2.0, 0.0])


def test_supertrend_warm_up() -> None:
    out = feed(SuperTrend(3.0, 3).update, HIGHS[:4], LOWS[:4], CLOSES[:4])
    assert out[0] == SuperTrendValue(0.0, 1)  # Pine's nz(band[1]) = 0 on the first bar
    assert math.isnan(out[1].supertrend) and out[1].direction == 1
    assert out[2] == SuperTrendValue(11.5 + 3 * (4 / 3), 1)  # first ATR: (1 + 1.5 + 1.5) / 3


def test_supertrend_factor_must_be_finite() -> None:
    with pytest.raises(ValueError, match="factor must be finite"):
        SuperTrend(factor=math.inf)


@given(ohlc_bars(), st.sampled_from([0.5, 1.0, 3.0]), st.integers(1, 6))
def test_supertrend_matches_reference(bars: Ohlc, factor: float, period: int) -> None:
    highs, lows, closes = bars
    out = feed(SuperTrend(factor, period).update, highs, lows, closes)
    line, direction = ref_supertrend(highs, lows, closes, factor, period)
    assert [v.direction for v in out] == direction
    assert_series_close([v.supertrend for v in out], line, tol=1e-9)
