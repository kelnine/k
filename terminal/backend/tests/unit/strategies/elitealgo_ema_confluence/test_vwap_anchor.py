"""The VWAP check's anchor: ``ta.vwap(hlc3)`` restarts on each trading day of the instrument
(doc 13 D8) — 17:00 New York for metals/FX/CFDs/CME (DST-correct), 00:00 UTC for crypto."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from kterminal.domain.market import Bar
from kterminal.strategies.elitealgo_ema_confluence import EliteAlgoEmaConfluence
from kterminal.strategy_engine import SignalOutput
from tests.fixtures.catalog import lab_catalog
from tests.unit.strategies.pine_port_support import make_bars, run, strategy_object

NEAR = lab_catalog().instrument("NEARUSD")


class VwapProbe(EliteAlgoEmaConfluence):
    """The strategy unchanged, recording its VWAP after every bar."""

    def on_start(self) -> None:
        super().on_start()
        self.vwaps: list[float] = []

    def on_bar(self, bar: Bar) -> SignalOutput:
        output = super().on_bar(bar)
        self.vwaps.append(self._vwap.value.vwap)
        return output


def rows(count: int, volume: float = 10) -> list[tuple[float, float, float, float, float]]:
    """Distinct bars: hlc3 of bar i is 100 + i."""
    return [(100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i, volume) for i in range(count)]


def vwaps(bars: list[Bar], **kwargs: object) -> list[float]:
    result = run(VwapProbe, bars, **kwargs)  # type: ignore[arg-type]
    assert result.fault is None
    probe = strategy_object(result)
    assert isinstance(probe, VwapProbe)
    return probe.vwaps


@pytest.mark.parametrize(
    ("label", "rollover_utc"),
    [
        ("winter (EST, UTC-5)", datetime(2026, 1, 6, 22, 0, tzinfo=UTC)),
        ("summer (EDT, UTC-4)", datetime(2026, 7, 7, 21, 0, tzinfo=UTC)),
    ],
)
def test_new_york_1700_anchor_follows_daylight_saving(label: str, rollover_utc: datetime) -> None:
    """Bars from 30 minutes before 17:00 New York: the VWAP is na until the first trading
    day boundary, restarts on the 17:00 bar and then accumulates."""
    start = rollover_utc - timedelta(minutes=30)
    values = vwaps(make_bars(rows(10), start=start))
    assert all(math.isnan(v) for v in values[:6]), label  # before the first anchor
    assert values[6] == 106.0  # the 17:00 bar alone (hlc3 = 106)
    assert values[7] == pytest.approx(106.5)  # (106 + 107) / 2 with equal volumes
    assert values[9] == pytest.approx(107.5)


def test_an_hour_off_would_be_wrong() -> None:
    """In summer 22:00 UTC is 18:00 New York, an hour into the trading day: no anchor."""
    start = datetime(2026, 7, 7, 21, 30, tzinfo=UTC)
    values = vwaps(make_bars(rows(12), start=start))
    assert all(math.isnan(v) for v in values)


def test_crypto_anchors_at_utc_midnight() -> None:
    start = datetime(2026, 1, 6, 23, 30, tzinfo=UTC)
    values = vwaps(make_bars(rows(10), start=start, instrument="NEARUSD"), instrument=NEAR)
    assert all(math.isnan(v) for v in values[:6])
    assert values[6] == 106.0


def test_a_weekend_gap_starts_a_new_trading_day() -> None:
    """Friday's last bars, then Sunday 18:00 New York: Monday's trading day starts there."""
    friday = make_bars(rows(4), start=datetime(2026, 1, 9, 21, 40, tzinfo=UTC))  # 16:40-17:00
    sunday = make_bars(rows(3), start=datetime(2026, 1, 11, 23, 0, tzinfo=UTC))  # 18:00 NY
    warm = make_bars(rows(3), start=datetime(2026, 1, 8, 21, 55, tzinfo=UTC))  # Thu 16:55 →
    values = vwaps(warm + friday + sunday)
    assert math.isnan(values[0]) and values[1] == 101.0  # Thursday 17:00 anchors Friday
    assert values[3 + len(friday)] == 100.0  # Sunday's first bar restarts the VWAP


def test_zero_volume_has_no_vwap_and_counts_bearish() -> None:
    """0 / 0 is na (doc 14.4): on a feed without volume the VWAP check is never bullish."""
    start = datetime(2026, 1, 6, 21, 30, tzinfo=UTC)
    values = vwaps(make_bars(rows(10, volume=0), start=start))
    assert all(math.isnan(v) for v in values)
