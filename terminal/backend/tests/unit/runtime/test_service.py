import asyncio
import os
import signal

from kterminal.runtime.service import run_until_signalled, sleep_or_stop


async def test_sleep_or_stop_times_out() -> None:
    assert await sleep_or_stop(asyncio.Event(), 0.01) is False


async def test_sleep_or_stop_returns_early_when_stopped() -> None:
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.01, stop.set)
    assert await asyncio.wait_for(sleep_or_stop(stop, 30), timeout=5) is True


async def test_sigterm_requests_graceful_stop() -> None:
    finished = asyncio.Event()

    async def main(stop: asyncio.Event) -> None:
        asyncio.get_running_loop().call_later(0.01, os.kill, os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(stop.wait(), timeout=5)
        finished.set()

    await run_until_signalled("test", main)
    assert finished.is_set()
