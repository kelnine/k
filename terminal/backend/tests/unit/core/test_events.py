from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kterminal.core.events import DomainEvent, InMemoryEventBus

T0 = datetime(2026, 10, 5, 14, 30, tzinfo=UTC)


class TradeEvent(DomainEvent):
    trade_id: str


class TradeOpened(TradeEvent):
    pass


class KillSwitchActivated(DomainEvent):
    reason: str


async def test_handlers_receive_matching_events_in_subscription_order() -> None:
    bus = InMemoryEventBus()
    calls: list[str] = []

    async def first(event: TradeOpened) -> None:
        calls.append(f"first:{event.trade_id}")

    async def second(event: TradeOpened) -> None:
        calls.append(f"second:{event.trade_id}")

    bus.subscribe(TradeOpened, first)
    bus.subscribe(TradeOpened, second)
    await bus.publish(TradeOpened(occurred_at=T0, trade_id="t1"))
    await bus.publish(KillSwitchActivated(occurred_at=T0, reason="manual"))
    assert calls == ["first:t1", "second:t1"]


async def test_subscribing_to_a_base_class_receives_subclasses() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []

    async def any_trade(event: TradeEvent) -> None:
        seen.append(event.event_type)

    bus.subscribe(TradeEvent, any_trade)
    await bus.publish(TradeOpened(occurred_at=T0, trade_id="t1"))
    assert seen == ["TradeOpened"]


async def test_failing_handler_is_isolated() -> None:
    errors: list[tuple[str, str]] = []
    bus = InMemoryEventBus(on_error=lambda ev, _h, exc: errors.append((ev.event_type, str(exc))))
    delivered: list[str] = []

    async def broken(_event: TradeOpened) -> None:
        raise RuntimeError("telegram is down")

    async def healthy(event: TradeOpened) -> None:
        delivered.append(event.trade_id)

    bus.subscribe(TradeOpened, broken)
    bus.subscribe(TradeOpened, healthy)
    await bus.publish(TradeOpened(occurred_at=T0, trade_id="t1"))  # must not raise
    assert delivered == ["t1"]
    assert errors == [("TradeOpened", "telegram is down")]


async def test_default_error_hook_logs_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    bus = InMemoryEventBus()

    async def broken(_event: TradeOpened) -> None:
        raise RuntimeError("boom")

    bus.subscribe(TradeOpened, broken)
    await bus.publish(TradeOpened(occurred_at=T0, trade_id="t1"))
    assert "event handler failed" in caplog.text


async def test_unsubscribe() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []

    async def handler(event: TradeOpened) -> None:
        seen.append(event.trade_id)

    subscription = bus.subscribe(TradeOpened, handler)
    subscription.cancel()
    subscription.cancel()  # idempotent
    await bus.publish(TradeOpened(occurred_at=T0, trade_id="t1"))
    assert seen == []
    assert not subscription.active
    assert bus.subscriber_count == 0


def test_events_are_immutable_utc_and_strict() -> None:
    event = TradeOpened(occurred_at=T0, trade_id="t1")
    assert event.event_id.version == 7
    with pytest.raises(ValidationError):
        event.trade_id = "t2"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        TradeOpened(occurred_at=datetime(2026, 1, 1), trade_id="t1")  # noqa: DTZ001
    with pytest.raises(ValidationError):
        TradeOpened(occurred_at=T0, trade_id="t1", unexpected=1)  # type: ignore[call-arg]
