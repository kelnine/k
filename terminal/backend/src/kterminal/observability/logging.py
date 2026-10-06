"""Structured logging.

Every process logs one JSON object per line to stdout (or coloured console
output in development). structlog and the standard library share a single
processor chain, so uvicorn, SQLAlchemy and asyncio logs get the same
timestamps, service name, correlation IDs and secret redaction as our own.
"""

import logging
import sys
from typing import Any, TextIO

import structlog
from structlog.typing import EventDict, Processor

from kterminal.config.settings import LogFormat, LoggingSettings
from kterminal.observability.redaction import redaction_processor


def _static_fields(**fields: str) -> Processor:
    def add(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
        for key, value in fields.items():
            event_dict.setdefault(key, value)
        return event_dict

    return add


def _drop_color_message(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """uvicorn duplicates its message with ANSI colour codes; keep only the plain one."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(
    settings: LoggingSettings, *, service: str, environment: str, stream: TextIO | None = None
) -> None:
    """Configure structlog + stdlib logging for this process. Safe to call more than once.

    Logs go to ``stream`` (default: stdout, where container runtimes collect them).
    """
    output = stream or sys.stdout
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        _drop_color_message,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _static_fields(service=service, environment=environment),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redaction_processor,  # last before rendering: nothing unredacted reaches the output
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if settings.format is LogFormat.JSON
        else structlog.dev.ConsoleRenderer(colors=output.isatty())
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(output)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.level)

    # Route third-party loggers through the root handler instead of their own.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy", "asyncio"):
        lib_logger = logging.getLogger(name)
        lib_logger.handlers.clear()
        lib_logger.propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # we log requests ourselves
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str | None = None, **initial: Any) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger.bind(**initial) if initial else logger
