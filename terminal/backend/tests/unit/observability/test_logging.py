import io
import json
import logging

import pytest

from kterminal.config.settings import LogFormat, LoggingSettings
from kterminal.observability.context import correlation_scope, get_correlation_id
from kterminal.observability.logging import configure_logging, get_logger


@pytest.fixture
def json_logs() -> io.StringIO:
    stream = io.StringIO()
    configure_logging(
        LoggingSettings(level="DEBUG", format=LogFormat.JSON),
        service="test-svc",
        environment="test",
        stream=stream,
    )
    return stream


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_structlog_lines_are_json_with_standard_fields(
    json_logs: io.StringIO,
) -> None:
    get_logger("kterminal.test").info("trade.opened", symbol="XAUUSD")
    (line,) = _lines(json_logs)
    assert line["event"] == "trade.opened"
    assert line["symbol"] == "XAUUSD"
    assert line["level"] == "info"
    assert line["service"] == "test-svc"
    assert line["environment"] == "test"
    assert str(line["timestamp"]).endswith("Z")


def test_correlation_id_is_attached_within_scope(json_logs: io.StringIO) -> None:
    log = get_logger("kterminal.test")
    with correlation_scope("req-12345678") as cid:
        assert get_correlation_id() == cid == "req-12345678"
        log.info("inside")
    log.info("outside")
    inside, outside = _lines(json_logs)
    assert inside["correlation_id"] == "req-12345678"
    assert "correlation_id" not in outside
    assert get_correlation_id() is None


def test_secrets_are_redacted_in_structlog_and_stdlib_logs(
    json_logs: io.StringIO,
) -> None:
    get_logger("kterminal.test").info("webhook", secret="tv-secret", body='{"secret":"tv-secret"}')
    logging.getLogger("third.party").warning("dsn is postgresql://u:hunter2@db/x")
    output = json_logs.getvalue()
    assert "tv-secret" not in output
    assert "hunter2" not in output
    assert "[REDACTED]" in output


def test_exceptions_are_rendered_and_redacted(json_logs: io.StringIO) -> None:
    try:
        raise ConnectionError("cannot reach postgresql://u:hunter2@db/x")
    except ConnectionError:
        get_logger("kterminal.test").exception("db.failed")
    (line,) = _lines(json_logs)
    assert "ConnectionError" in str(line["exception"])
    assert "hunter2" not in json.dumps(line)


def test_stdlib_extra_fields_are_kept(json_logs: io.StringIO) -> None:
    logging.getLogger("kterminal.core.events").error("handler failed", extra={"event_type": "X"})
    (line,) = _lines(json_logs)
    assert line["event_type"] == "X"
    assert line["logger"] == "kterminal.core.events"


def test_level_filtering() -> None:
    stream = io.StringIO()
    configure_logging(
        LoggingSettings(level="WARNING"), service="s", environment="test", stream=stream
    )
    log = get_logger("kterminal.test")
    log.info("hidden")
    log.warning("shown")
    assert [line["event"] for line in _lines(stream)] == ["shown"]


def test_uvicorn_color_message_is_dropped(json_logs: io.StringIO) -> None:
    logging.getLogger("uvicorn.error").info(
        "Started server process [%d]", 1, extra={"color_message": "Started \x1b[36m%d\x1b[0m"}
    )
    (line,) = _lines(json_logs)
    assert line["event"] == "Started server process [1]"
    assert "color_message" not in line
