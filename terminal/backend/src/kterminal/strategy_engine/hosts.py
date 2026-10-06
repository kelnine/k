"""Strategy hosts: where an instance's code actually runs.

``InProcessHost``
    Runs the instance's runners in the calling process. Fast and deterministic
    — the default for backtests. Exceptions are contained by the runner.

``SubprocessHost``
    Runs the instance in its **own operating-system process**. Besides
    exceptions it contains crashes, runaway memory and infinite loops: each
    batch of bars has a time budget, and an instance that exceeds it (or whose
    process dies) is killed and marked faulted while every other instance keeps
    running. Bars, instruments and signals cross the process boundary as
    pickles of immutable value objects, so the child never shares memory with
    the lab or with other instances.

Both expose ``dispatch(bars)`` / ``collect()`` so the lab can hand a bar batch
to every host first and then gather results in a fixed order: subprocess
hosts compute in parallel, outputs stay deterministic.
"""

import multiprocessing as mp
import multiprocessing.connection as mpc
import traceback
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Protocol

from kterminal.domain.instruments import Instrument
from kterminal.domain.market import Bar
from kterminal.domain.signals import Signal
from kterminal.strategy_engine.instances import ResolvedInstance
from kterminal.strategy_engine.model import Fault, RunnerOutput
from kterminal.strategy_engine.runner import DEFAULT_TIME_BUDGET_MS, StrategyRunner


class HostState(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    FAULTED = "FAULTED"
    STOPPED = "STOPPED"


class StrategyHost(Protocol):
    @property
    def instance_id(self) -> str: ...

    @property
    def state(self) -> HostState: ...

    @property
    def fault(self) -> Fault | None: ...

    def start(self) -> None: ...

    def warmup(self, bars: Sequence[Bar]) -> None: ...

    def dispatch(self, bars: Sequence[Bar]) -> None: ...

    def collect(self) -> list[RunnerOutput]: ...

    def on_bars(self, bars: Sequence[Bar]) -> list[RunnerOutput]: ...

    def submit_external(self, signal: Signal) -> list[RunnerOutput]: ...

    def stop(self) -> None: ...


# ── shared core: the runners of one instance ────────────────────────────────
class _InstanceCore:
    """All runners (one per instrument) of one instance. An instance faults as a whole."""

    def __init__(
        self,
        resolved: ResolvedInstance,
        instruments: Mapping[str, Instrument],
        sessions: Any | None,
        time_budget_ms: float,
    ) -> None:
        self.resolved = resolved
        self.runners = [
            StrategyRunner(
                resolved, instruments[symbol], sessions=sessions, time_budget_ms=time_budget_ms
            )
            for symbol in resolved.spec.instruments
        ]
        self.fault: Fault | None = None

    def start(self) -> Fault | None:
        for runner in self.runners:
            if fault := runner.start():
                self.fault = fault
                break
        return self.fault

    def warmup(self, bars: Sequence[Bar]) -> Fault | None:
        for runner in self.runners:
            runner.warmup(bars)
            if runner.fault is not None:
                self.fault = runner.fault
                break
        return self.fault

    def process(self, bars: Sequence[Bar]) -> list[RunnerOutput]:
        if self.fault is not None:
            return []
        outputs = []
        for runner in self.runners:
            output = runner.process(bars)
            if output is None:
                continue
            outputs.append(output)
            if output.fault is not None:
                self.fault = output.fault
                break
        return outputs

    def submit_external(self, signal: Signal) -> list[RunnerOutput]:
        if self.fault is not None:
            return []
        for runner in self.runners:
            if runner.instrument.symbol == signal.symbol:
                return [runner.submit_external(signal)]
        return []

    def stop(self) -> None:
        for runner in self.runners:
            runner.stop()


class InProcessHost:
    def __init__(
        self,
        resolved: ResolvedInstance,
        instruments: Mapping[str, Instrument],
        sessions: Any | None = None,
        *,
        time_budget_ms: float = DEFAULT_TIME_BUDGET_MS,
    ) -> None:
        self.instance_id = resolved.id
        self.state = HostState.CREATED
        self._core = _InstanceCore(resolved, instruments, sessions, time_budget_ms)
        self._pending: list[RunnerOutput] = []

    @property
    def fault(self) -> Fault | None:
        return self._core.fault

    def _sync_state(self) -> None:
        if self._core.fault is not None:
            self.state = HostState.FAULTED

    def start(self) -> None:
        self._core.start()
        self.state = HostState.RUNNING
        self._sync_state()

    def warmup(self, bars: Sequence[Bar]) -> None:
        self._core.warmup(bars)
        self._sync_state()

    def dispatch(self, bars: Sequence[Bar]) -> None:
        self._pending = self._core.process(bars) if self.state is HostState.RUNNING else []
        self._sync_state()

    def collect(self) -> list[RunnerOutput]:
        outputs, self._pending = self._pending, []
        return outputs

    def on_bars(self, bars: Sequence[Bar]) -> list[RunnerOutput]:
        self.dispatch(bars)
        return self.collect()

    def submit_external(self, signal: Signal) -> list[RunnerOutput]:
        return self._core.submit_external(signal) if self.state is HostState.RUNNING else []

    def stop(self) -> None:
        if self.state is HostState.RUNNING:
            self._core.stop()
        self.state = HostState.STOPPED if self.state is not HostState.FAULTED else self.state


# ── subprocess host ─────────────────────────────────────────────────────────
def _child_main(
    conn: mpc.Connection,
    resolved: ResolvedInstance,
    instruments: Mapping[str, Instrument],
    sessions: Any | None,
    time_budget_ms: float,
) -> None:  # pragma: no cover - runs in the child process (exercised by integration tests)
    core = _InstanceCore(resolved, instruments, sessions, time_budget_ms)
    while True:
        try:
            command, payload = conn.recv()
        except (EOFError, OSError):
            return
        try:
            if command == "start":
                conn.send(("ok", core.start()))
            elif command == "warmup":
                conn.send(("ok", core.warmup(payload)))
            elif command == "bars":
                conn.send(("ok", (core.process(payload), core.fault)))
            elif command == "external":
                conn.send(("ok", (core.submit_external(payload), core.fault)))
            elif command == "stop":
                core.stop()
                conn.send(("ok", None))
                return
            else:
                conn.send(("error", f"unknown command {command!r}"))
        except Exception as exc:
            conn.send(("error", "".join(traceback.format_exception(exc))[-8_000:]))


class SubprocessHost:
    def __init__(
        self,
        resolved: ResolvedInstance,
        instruments: Mapping[str, Instrument],
        sessions: Any | None = None,
        *,
        time_budget_ms: float = DEFAULT_TIME_BUDGET_MS,
        call_timeout_s: float = 10.0,
        start_timeout_s: float = 60.0,
        start_method: str = "spawn",
    ) -> None:
        self.instance_id = resolved.id
        self.state = HostState.CREATED
        self.fault: Fault | None = None
        self.call_timeout_s = call_timeout_s
        self.start_timeout_s = start_timeout_s
        self._resolved = resolved
        self._instruments = {s: instruments[s] for s in resolved.spec.instruments}
        self._sessions = sessions
        self._time_budget_ms = time_budget_ms
        self._ctx: Any = mp.get_context(start_method)
        self._conn: mpc.Connection | None = None
        self._process: Any = None
        self._awaiting = False

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def start(self) -> None:
        parent, child = self._ctx.Pipe(duplex=True)
        self._process = self._ctx.Process(
            target=_child_main,
            args=(child, self._resolved, self._instruments, self._sessions, self._time_budget_ms),
            name=f"kterminal-strategy-{self.instance_id}",
            daemon=True,
        )
        self._process.start()
        child.close()
        self._conn = parent
        self.state = HostState.RUNNING
        result = self._call("start", None, timeout=self.start_timeout_s)
        if isinstance(result, Fault):
            self._set_fault(result)

    def warmup(self, bars: Sequence[Bar]) -> None:
        if self.state is not HostState.RUNNING:
            return
        result = self._call("warmup", list(bars), timeout=max(self.call_timeout_s, 120.0))
        if isinstance(result, Fault):
            self._set_fault(result)

    def dispatch(self, bars: Sequence[Bar]) -> None:
        if self.state is not HostState.RUNNING or self._conn is None:
            return
        try:
            self._conn.send(("bars", list(bars)))
            self._awaiting = True
        except (OSError, ValueError) as exc:
            self._host_fault("IPC send failed", exc)

    def collect(self) -> list[RunnerOutput]:
        if not self._awaiting:
            return []
        self._awaiting = False
        outputs, fault = self._receive(self.call_timeout_s)
        if fault is not None:
            self._set_fault(fault)
        return outputs

    def on_bars(self, bars: Sequence[Bar]) -> list[RunnerOutput]:
        self.dispatch(bars)
        return self.collect()

    def submit_external(self, signal: Signal) -> list[RunnerOutput]:
        if self.state is not HostState.RUNNING:
            return []
        result = self._call("external", signal, timeout=self.call_timeout_s)
        if result is None:
            return []
        outputs, fault = result
        if fault is not None:
            self._set_fault(fault)
        return list(outputs)

    def stop(self) -> None:
        if self.state is HostState.RUNNING:
            self._call("stop", None, timeout=self.call_timeout_s)
            if self.state is HostState.RUNNING:
                self.state = HostState.STOPPED
        self._terminate()

    # ── internals ───────────────────────────────────────────────────────────
    def _call(self, command: str, payload: Any, *, timeout: float) -> Any:
        if self._conn is None:
            return None
        try:
            self._conn.send((command, payload))
        except (OSError, ValueError) as exc:
            self._host_fault("IPC send failed", exc)
            return None
        status, result = self._recv(timeout)
        if status == "ok":
            return result
        if status == "error":
            self._set_fault(self._make_fault("HostError", str(result)))
        return None

    def _receive(self, timeout: float) -> tuple[list[RunnerOutput], Fault | None]:
        status, result = self._recv(timeout)
        if status != "ok" or result is None:
            if status == "error":
                self._set_fault(self._make_fault("HostError", str(result)))
            return [], None
        outputs, fault = result
        return list(outputs), fault

    def _recv(self, timeout: float) -> tuple[str, Any]:
        conn = self._conn
        if conn is None:
            return "dead", None
        try:
            if not conn.poll(timeout):
                self._host_fault(
                    f"no response within {timeout:.1f}s (time budget exceeded or hung)", None
                )
                return "timeout", None
            message: tuple[str, Any] = conn.recv()
            return message
        except (EOFError, OSError) as exc:
            code = self._process.exitcode if self._process is not None else None
            self._host_fault(f"strategy process died (exit code {code})", exc)
            return "dead", None

    def _host_fault(self, message: str, exc: BaseException | None) -> None:
        detail = f"{message}: {type(exc).__name__}: {exc}" if exc else message
        self._set_fault(self._make_fault("HostFailure", detail))
        self._terminate()

    def _make_fault(self, error_type: str, message: str) -> Fault:
        return Fault(
            instance_id=self.instance_id,
            instrument=",".join(self._resolved.spec.instruments),
            time=None,
            stage="host",
            error_type=error_type,
            message=message[:2_000],
        )

    def _set_fault(self, fault: Fault) -> None:
        if self.fault is None:
            self.fault = fault
        self.state = HostState.FAULTED

    def _terminate(self) -> None:
        process, self._process = self._process, None
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if process is not None and process.is_alive():
            process.kill()
            process.join(timeout=5)
