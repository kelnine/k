import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kterminal.indicators import Vwap, VwapValue, feed
from tests.unit.indicators.reference import assert_series_close, ref_vwap

NAN = math.nan


def test_vwap_hand_vector_with_bands_and_reset() -> None:
    sources = [1.0, 2.0, 3.0, 4.0, 4.0, 6.0]
    volumes = [1.0, 1.0, 2.0, 0.0, 1.0, 3.0]
    anchors = [False, True, False, False, True, False]
    out = feed(Vwap().update, sources, volumes, anchors)
    # bar 0: before the first anchor → na
    assert math.isnan(out[0].vwap) and math.isnan(out[0].stdev)
    # bar 1: 2·1 / 1 = 2, σ 0; bar 2: (2 + 6) / 3 = 8/3, σ² = (4 + 18) / 3 − (8/3)² = 2/9
    assert out[1] == VwapValue(2.0, 0.0)
    assert out[2].vwap == pytest.approx(8 / 3) and out[2].stdev == pytest.approx(math.sqrt(2 / 9))
    assert out[3] == out[2]  # zero volume adds nothing
    # bar 4 re-anchors: 4; bar 5: (4 + 18) / 4 = 5.5, σ² = (16 + 108) / 4 − 30.25 = 0.75
    assert out[4] == VwapValue(4.0, 0.0)
    assert out[5].vwap == 5.5 and out[5].stdev == pytest.approx(math.sqrt(0.75))
    assert out[5].upper(2.0) == pytest.approx(5.5 + 2 * math.sqrt(0.75))
    assert out[5].lower(1.0) == pytest.approx(5.5 - math.sqrt(0.75))


def test_zero_volume_has_no_vwap_until_volume_arrives() -> None:
    out = feed(Vwap().update, [5.0, 6.0], [0.0, 2.0], [True, False])
    assert math.isnan(out[0].vwap)  # 0 / 0 is na in Pine
    assert out[1] == VwapValue(6.0, 0.0)


def test_na_volume_poisons_the_period_until_the_next_anchor() -> None:
    out = feed(
        Vwap().update, [1.0, 2.0, 3.0, 4.0], [1.0, NAN, 1.0, 1.0], [True, False, False, True]
    )
    assert out[0] == VwapValue(1.0, 0.0)
    assert math.isnan(out[1].vwap) and math.isnan(out[2].vwap)
    assert out[3] == VwapValue(4.0, 0.0)


def test_na_source_changes_nothing_not_even_the_anchor() -> None:
    out = feed(Vwap().update, [1.0, NAN, 3.0], [1.0, 1.0, 1.0], [True, True, False])
    assert out[0] == VwapValue(1.0, 0.0)
    assert math.isnan(out[1].vwap)
    assert out[2].vwap == 2.0  # still accumulating from bar 0


@given(
    st.lists(
        st.tuples(
            st.one_of(st.integers(80, 120).map(float), st.just(NAN)),
            st.one_of(st.integers(0, 50).map(float), st.just(NAN)),
            st.booleans(),
        ),
        max_size=50,
    )
)
def test_vwap_matches_reference(rows: list[tuple[float, float, bool]]) -> None:
    sources = [source for source, _, _ in rows]
    volumes = [volume for _, volume, _ in rows]
    anchors = [anchor for _, _, anchor in rows]
    out = feed(Vwap().update, sources, volumes, anchors)
    vwap, stdev = ref_vwap(sources, volumes, anchors)
    assert_series_close([v.vwap for v in out], vwap, tol=1e-9)
    assert_series_close([v.stdev for v in out], stdev, tol=1e-6)
