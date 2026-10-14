"""The shared HTTP machinery: request budget, retry helpers, parsing helpers."""

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from kterminal.config.settings import MarketDataSettings
from kterminal.marketdata.providers._http import (
    PayloadError,
    ProviderOptions,
    RequestBudget,
    ceil_minute,
    decimal_field,
    floor_minute,
    from_ms,
    int_field,
    parse_retry_after,
    venue_message,
)
from tests.fixtures.marketdata import FakeTime


async def test_budget_allows_a_burst_then_paces_at_the_rate() -> None:
    clock = FakeTime()
    budget = RequestBudget(60, 3, monotonic=clock.monotonic, sleep=clock.sleep)  # 1 per second
    for _ in range(3):
        await budget.acquire()
    assert clock.sleeps == []
    await budget.acquire()
    assert clock.sleeps == [pytest.approx(1.0)]
    await budget.acquire(2)
    assert sum(clock.sleeps) == pytest.approx(3.0)


async def test_budget_refills_while_idle_but_never_beyond_the_burst() -> None:
    clock = FakeTime()
    budget = RequestBudget(60, 2, monotonic=clock.monotonic, sleep=clock.sleep)
    await budget.acquire(2)
    clock.now += 3600  # an hour idle refills only up to the burst
    await budget.acquire(2)
    assert clock.sleeps == []
    await budget.acquire(1)
    assert clock.sleeps == [pytest.approx(1.0)]


async def test_budget_cost_above_the_burst_is_capped_and_pause_blocks() -> None:
    clock = FakeTime()
    budget = RequestBudget(600, 5, monotonic=clock.monotonic, sleep=clock.sleep)
    await budget.acquire(50)  # costs the whole burst, does not wait forever
    assert clock.sleeps == []
    clock.now += 10  # refilled
    budget.pause(30)
    await budget.acquire()
    assert clock.sleeps == [pytest.approx(30.0)]


def test_budget_needs_positive_parameters() -> None:
    with pytest.raises(ValueError, match="positive"):
        RequestBudget(0, 1)


def test_options_follow_the_settings_and_back_off_exponentially() -> None:
    settings = MarketDataSettings(
        request_timeout_s=3, max_retries=2, backoff_initial_s=0.25, backoff_max_s=1, close_delay_s=5
    )
    options = ProviderOptions.from_settings(settings)
    assert options == ProviderOptions(3, 2, 0.25, 1, 5)
    assert [options.backoff(n) for n in range(4)] == [0.25, 0.5, 1, 1]


def test_minute_helpers() -> None:
    t = datetime(2026, 10, 9, 12, 0, 30, tzinfo=UTC)
    assert floor_minute(t) == datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    assert ceil_minute(t) == datetime(2026, 10, 9, 12, 1, tzinfo=UTC)
    assert ceil_minute(floor_minute(t)) == floor_minute(t)
    assert from_ms("1760011200000", "t") == datetime(2025, 10, 9, 12, 0, tzinfo=UTC)
    with pytest.raises(PayloadError, match="whole minute"):
        from_ms(1760011201000, "t")


@pytest.mark.parametrize("value", [True, 1.5, "1e3x", None, [1]])
def test_decimal_field_rejects_anything_but_numbers(value: object) -> None:
    with pytest.raises(PayloadError, match="must be a number"):
        decimal_field(value, "price")


def test_decimal_field_is_exact_and_finite() -> None:
    assert decimal_field("0.00000001", "v").as_tuple() == Decimal("0.00000001").as_tuple()
    assert decimal_field("2650.10", "v").as_tuple().exponent == -2  # trailing zero kept
    assert decimal_field(Decimal("2650.10"), "v") == Decimal("2650.10")
    assert decimal_field(7, "v") == Decimal(7)
    with pytest.raises(PayloadError, match="finite"):
        decimal_field("Infinity", "v")
    with pytest.raises(PayloadError, match="integer"):
        int_field("12a", "t")
    with pytest.raises(PayloadError, match="integer"):
        int_field(False, "t")


def test_venue_message_prefers_the_venue_fields() -> None:
    def response(**kwargs: object) -> httpx.Response:
        return httpx.Response(400, **kwargs)  # type: ignore[arg-type]

    assert venue_message(response(json={"code": -1121, "msg": "Invalid symbol."})) == (
        "Invalid symbol. (code -1121)"
    )
    assert venue_message(response(json={"retCode": 10001, "retMsg": "bad"})) == "bad (code 10001)"
    assert venue_message(response(json={"message": "NotFound"})) == "NotFound"
    assert venue_message(response(json={"errorMessage": "Bad", "errorCode": "X"})) == (
        "Bad (code X)"
    )
    assert venue_message(response(text="  plain\n text ")) == "plain text"
    long = venue_message(response(text="x" * 1000))
    assert len(long) == 300
    assert long.endswith("…")


def test_retry_after_parsing() -> None:
    def headers(value: str | None) -> httpx.Response:
        return httpx.Response(429, headers={} if value is None else {"Retry-After": value})

    assert parse_retry_after(headers("7")) == 7.0
    assert parse_retry_after(headers("1.5")) == 1.5
    assert parse_retry_after(headers(None)) is None
    assert parse_retry_after(headers("Wed, 21 Oct 2026 07:28:00 GMT")) is None
    assert parse_retry_after(headers("-1")) is None
