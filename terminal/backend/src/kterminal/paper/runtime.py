"""The forward paper-trading runtime: live bars in, paper trades out, until stopped.

:class:`PaperRuntime` is what ``kterminal paper start`` runs in the foreground
and what the ``engine`` process runs once it is the leader. It

1. takes the paper-runtime advisory lock (one runtime per database: a second
   one would write the same session twice);
2. resumes the open forward session (replay + verification) or starts a new
   one — ``new_session`` first ends the open session, closing its positions;
3. loops: the next minute from the :class:`~kterminal.paper.feed.LiveFeed`,
   the kill switches as the database holds them now, the minute through the
   lab, one commit; and
4. publishes its status to ``system_state`` (key ``paper.runtime``) after
   every minute and on every state change, for the dashboard.

LIVE execution does not exist here: every account is a PAPER account, fills are
simulated, and no broker adapter is ever constructed.

Status document (``system_state['paper.runtime']``)::

    {
      "session_id": "...",          # this runtime process's attachment (new on every start)
      "run_id": "...",              # the forward session (runs.id, kind FORWARD)
      "status": "running",          # starting | warming_up | running | stopped | error
      "started_at": "...",          # when the forward session began (its first live minute)
      "updated_at": "...",
      "last_batch_close": "...",    # close of the newest processed minute (null before the first)
      "instruments": {"XAUUSD": {"provider": "oanda", "last_bar_open": "...",
                                 "lag_seconds": 4.2, "state": "ok", "last_error": null}},
      "instances": {"demo_sma_fast": {"state": "RUNNING", "fault": null, "account_id": "..."}},
      "kill_switch": {"global": false, "accounts": [], "strategies": []},
      "error": null                 # the reason, when status is "error"
    }
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from kterminal.core.clock import Clock, SystemClock
from kterminal.core.errors import KTerminalError, LeadershipLostError
from kterminal.core.ids import uuid7
from kterminal.core.registry import Registry
from kterminal.db.locks import AdvisoryLock
from kterminal.db.session import Database
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.domain.sessions import TradingCalendar
from kterminal.marketdata.base import MarketDataProvider
from kterminal.observability.logging import get_logger
from kterminal.paper.config import LabConfig
from kterminal.paper.feed import FeedConfig, LiveFeed, Wait
from kterminal.paper.forward import ForwardSession, close_session
from kterminal.paper.kill_switch import NO_KILL_SWITCHES, KillSwitchState
from kterminal.paper.pg_forward import PostgresForwardStore
from kterminal.strategy_engine.registry import DEFINITIONS, StrategyDefinition

_log = get_logger("kterminal.paper.runtime")

PAPER_RUNTIME_LOCK = "kterminal.paper.runtime"


class RuntimeLockedError(KTerminalError):
    """Another paper runtime (``kterminal paper start`` or the engine) is running."""


@dataclass(frozen=True, slots=True)
class RuntimeOptions:
    """``None`` takes the value from the lab configuration's ``forward`` section."""

    new_session: bool = False  # end the open session (closing its positions) and start anew
    warmup_days: float | None = None  # cap on how far back warm-up history reaches
    feed: FeedConfig | None = None
    commit_attempts: int = 3
    session_name: str = "paper-forward"


async def end_open_sessions(
    database: Database, *, reason: str = "ended by the operator"
) -> list[tuple[UUID, int]]:
    """End every open forward session (positions closed at their last processed price)
    while no runtime runs: (run id, positions closed) per session."""
    lock = AdvisoryLock(database.engine, PAPER_RUNTIME_LOCK)
    if not await lock.try_acquire():
        raise RuntimeLockedError(
            "a paper runtime is running against this database (kterminal paper start, or "
            "the engine service) — stop it first, or use kterminal paper start --new-session"
        )
    try:
        store = PostgresForwardStore(database)
        return [
            (stored.run_id, await close_session(store, stored, reason=reason))
            for stored in await store.open_sessions()
        ]
    finally:
        await lock.release()


async def publish_failure(database: Database, error: str, *, now: datetime) -> None:
    """Publish an ``error`` status for a runtime that could not be built (e.g. an invalid
    data source map) — unless another runtime holds the lock: its status stands."""
    lock = AdvisoryLock(database.engine, PAPER_RUNTIME_LOCK)
    try:
        if not await lock.try_acquire():
            return
        try:
            await PostgresForwardStore(database).write_status(
                PaperRuntime.failure_document(error, now), now=now
            )
        finally:
            await lock.release()
    except Exception as exc:  # informational only
        _log.warning("paper.status_not_written", error=f"{type(exc).__name__}: {exc}"[:300])


async def wait_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    """Sleep for up to ``seconds``; True as soon as a stop is requested."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


class PaperRuntime:
    def __init__(
        self,
        *,
        config: LabConfig,
        catalog: InstrumentCatalog,
        database: Database,
        providers: Mapping[str, MarketDataProvider],
        clock: Clock | None = None,
        options: RuntimeOptions | None = None,
        definitions: Registry[StrategyDefinition] = DEFINITIONS,
        discover: bool = True,
        config_dir: Path | None = None,
        wait: Wait | None = None,
        unavailable: Mapping[str, str] | None = None,
    ) -> None:
        """``providers``: canonical instrument → its market-data provider; instruments
        without one deliver no bars (``unavailable`` says why, for the status)."""
        self.config = config
        self.catalog = catalog
        self.database = database
        self.providers = dict(providers)
        self.unavailable = dict(unavailable or {})
        self.clock = clock or SystemClock()
        self.options = options or RuntimeOptions()
        forward = config.forward
        self.warmup_days = (
            self.options.warmup_days
            if self.options.warmup_days is not None
            else forward.warmup_days
        )
        self.feed_config = self.options.feed or FeedConfig(
            poll_delay_s=forward.poll_delay_s, batch_timeout_s=forward.batch_timeout_s
        )
        self.definitions = definitions
        self.discover = discover
        self.config_dir = config_dir
        self._wait = wait
        self.store = PostgresForwardStore(database)
        self.attach_id: UUID = uuid7()
        self.status = "starting"
        self.session: ForwardSession | None = None
        self.feed: LiveFeed | None = None
        self.kill_switches: KillSwitchState = NO_KILL_SWITCHES
        self.error: str | None = None

    async def run(self, stop: asyncio.Event) -> None:
        """Run until ``stop`` is set (graceful) or an error occurs (raised)."""
        lock = AdvisoryLock(self.database.engine, PAPER_RUNTIME_LOCK)
        if not await lock.try_acquire():
            raise RuntimeLockedError(
                "another paper runtime is already running against this database "
                "(kterminal paper start, or the engine service) — stop it first"
            )
        try:
            await self._run(stop, lock)
        finally:
            await lock.release()

    async def _run(self, stop: asyncio.Event, lock: AdvisoryLock) -> None:
        wait = self._wait or (lambda seconds: wait_or_stop(stop, seconds))
        await self._publish("starting")
        try:
            session = await self._open_session()
            self.session = session
            # Switches already active apply from the first live minute on.
            self.kill_switches = KillSwitchState.from_records(
                await self.store.kill_switch_records()
            )
            session.lab.set_kill_switches(self.kill_switches)
            calendars = self._calendars(session.instruments)
            self.feed = LiveFeed(
                session.instruments,
                self.providers,
                calendars,
                start=session.processed_through,
                clock=self.clock,
                wait=wait,
                config=self.feed_config,
                last_bars=session.last_bars,
                unavailable=self.unavailable,
            )
            await self._publish("running")
            while not stop.is_set():
                batch = await self.feed.next_batch()
                if batch is None:
                    break
                if not await lock.verify():
                    raise LeadershipLostError("the paper runtime lock was lost — stopping at once")
                self.kill_switches = KillSwitchState.from_records(
                    await self.store.kill_switch_records()
                )
                session.lab.set_kill_switches(self.kill_switches)
                await session.process_minute(
                    batch, now=self.clock.now(), attempts=self.options.commit_attempts
                )
                await self._publish("running")
        except BaseException as exc:
            self.error = f"{type(exc).__name__}: {exc}"[:2_000]
            if not isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
                _log.error("paper.runtime_failed", error=self.error)
            await self._publish("error")
            raise
        finally:
            if self.session is not None:
                self.session.abort()
        await self._publish("stopped")

    async def _open_session(self) -> ForwardSession:
        open_sessions = await self.store.open_sessions()
        if self.options.new_session:
            for stored in open_sessions:
                await close_session(self.store, stored, reason="replaced by a new session")
            open_sessions = []
        await self._publish("warming_up")
        if len(open_sessions) > 1:
            raise KTerminalError(
                f"{len(open_sessions)} forward sessions are RUNNING; end them with "
                "kterminal paper start --new-session"
            )
        if open_sessions:
            return await ForwardSession.resume(
                open_sessions[0],
                self.config,
                self.catalog,
                self.store,
                self.providers,
                definitions=self.definitions,
                discover=self.discover,
                config_dir=self.config_dir,
            )
        return await ForwardSession.start(
            self.config,
            self.catalog,
            self.store,
            self.providers,
            now=self.clock.now(),
            warmup_days=self.warmup_days,
            name=self.options.session_name,
            definitions=self.definitions,
            discover=self.discover,
            config_dir=self.config_dir,
        )

    def _calendars(self, instruments: tuple[str, ...]) -> dict[str, TradingCalendar]:
        return {
            symbol: self.catalog.sessions.calendar(self.catalog.instrument(symbol).trading_hours)
            for symbol in instruments
        }

    # ── status ──────────────────────────────────────────────────────────────
    def status_document(self, now: datetime) -> dict[str, Any]:
        session = self.session
        last_close = None
        if session is not None and session.progress.processed_through > session.plan.live_start:
            last_close = session.progress.processed_through.isoformat()
        return {
            "session_id": str(self.attach_id),
            "run_id": None if session is None else str(session.run_id),
            "status": self.status,
            "started_at": None if session is None else session.plan.live_start.isoformat(),
            "updated_at": now.isoformat(),
            "last_batch_close": last_close,
            "instruments": {} if self.feed is None else self.feed.status(),
            "instances": {} if session is None else session.instances_status(),
            "kill_switch": self.kill_switches.summary(),
            "error": self.error if self.status == "error" else None,
        }

    @staticmethod
    def failure_document(error: str, now: datetime) -> dict[str, Any]:
        """The status of a runtime that could not even be built (e.g. an invalid data
        source map): ``error`` with nothing running."""
        return {
            "session_id": None,
            "run_id": None,
            "status": "error",
            "started_at": None,
            "updated_at": now.isoformat(),
            "last_batch_close": None,
            "instruments": {},
            "instances": {},
            "kill_switch": NO_KILL_SWITCHES.summary(),
            "error": error[:2_000],
        }

    async def _publish(self, status: str) -> None:
        self.status = status
        now = self.clock.now()
        try:
            await self.store.write_status(self.status_document(now), now=now)
        except Exception as exc:  # the status is informational: never fail trading over it
            _log.warning("paper.status_not_written", error=f"{type(exc).__name__}: {exc}"[:300])


__all__ = [
    "PAPER_RUNTIME_LOCK",
    "PaperRuntime",
    "RuntimeLockedError",
    "RuntimeOptions",
    "end_open_sessions",
    "publish_failure",
    "wait_or_stop",
]
