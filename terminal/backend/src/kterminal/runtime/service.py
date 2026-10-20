"""Lifecycle helpers for long-running process roles (engine, worker)."""

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable

from kterminal.observability.logging import get_logger

_log = get_logger(__name__)


async def run_until_signalled(name: str, main: Callable[[asyncio.Event], Awaitable[None]]) -> None:
    """Run ``main(stop)`` until it returns; SIGINT/SIGTERM set ``stop`` for a graceful exit."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Not available on Windows or outside the main thread; Ctrl-C still works there.
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)
    _log.info("service.starting", role=name)
    try:
        await main(stop)
    finally:
        _log.info("service.stopped", role=name)


async def sleep_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    """Sleep for up to ``seconds``. Returns True as soon as a stop is requested."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True
