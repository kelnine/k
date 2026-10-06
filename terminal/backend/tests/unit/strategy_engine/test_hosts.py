"""Host isolation: in-process and subprocess hosts produce identical results, and a
crashing / hanging instance is faulted without affecting any other instance."""

import os
from collections.abc import Sequence

import pytest

from kterminal.core.registry import Registry
from kterminal.domain.market import Bar
from kterminal.domain.timeframes import M1, M5
from kterminal.marketdata.aggregator import aggregate_stream
from kterminal.strategy_engine.hosts import HostState, InProcessHost, SubprocessHost
from kterminal.strategy_engine.instances import InstanceSpec, ResolvedInstance, resolve_instance
from kterminal.strategy_engine.model import RunnerOutput
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from tests.fixtures.instruments import INSTRUMENTS, gold_minutes
from tests.fixtures.strategies import Crasher, SmaCross

REGISTRY: Registry[StrategyDefinition] = Registry("strategy definition")
for _cls in (SmaCross, Crasher):
    _d = definition_from_class(_cls)
    REGISTRY.register(_d.id, _d)


def resolved(instance_id: str, strategy: str, **params: object) -> ResolvedInstance:
    spec = InstanceSpec(
        id=instance_id, strategy=strategy, params=params, instruments=("XAUUSD",), timeframe="5m"
    )
    return resolve_instance(spec, instruments=INSTRUMENTS, definitions=REGISTRY)


def five_minute_batches(count: int = 1_500) -> list[list[Bar]]:
    return list(aggregate_stream(gold_minutes(count, seed=3), M1, [M5]))


def run(
    host: InProcessHost | SubprocessHost, batches: Sequence[Sequence[Bar]]
) -> list[RunnerOutput]:
    outputs: list[RunnerOutput] = []
    host.start()
    for batch in batches:
        outputs.extend(host.on_bars(batch))
    host.stop()
    return outputs


def signals_of(outputs: list[RunnerOutput]) -> list[object]:
    return [s for o in outputs for s in o.signals]


def test_in_process_host_runs_instance() -> None:
    host = InProcessHost(resolved("sma_a", "sma_cross_test"), INSTRUMENTS)
    outputs = run(host, five_minute_batches())
    assert host.state is HostState.STOPPED
    assert signals_of(outputs)


def test_subprocess_host_matches_in_process_exactly() -> None:
    batches = five_minute_batches()
    inproc = run(InProcessHost(resolved("sma_a", "sma_cross_test"), INSTRUMENTS), batches)
    sub = SubprocessHost(resolved("sma_a", "sma_cross_test"), INSTRUMENTS)
    outputs = run(sub, batches)
    assert signals_of(outputs) == signals_of(inproc)
    assert sub.state is HostState.STOPPED


def test_exception_in_one_instance_does_not_affect_another() -> None:
    batches = five_minute_batches(300)
    healthy = InProcessHost(resolved("sma_a", "sma_cross_test"), INSTRUMENTS)
    broken = InProcessHost(resolved("crash_a", "crasher", crash_on=4), INSTRUMENTS)
    reference = run(InProcessHost(resolved("sma_a", "sma_cross_test"), INSTRUMENTS), batches)
    healthy.start()
    broken.start()
    healthy_out: list[RunnerOutput] = []
    for batch in batches:
        for host in (broken, healthy):
            host.dispatch(batch)
        broken.collect()
        healthy_out.extend(healthy.collect())
    assert broken.state is HostState.FAULTED
    assert broken.fault is not None and broken.fault.error_type == "ZeroDivisionError"
    assert healthy.state is HostState.RUNNING
    assert signals_of(healthy_out) == signals_of(reference)


@pytest.mark.parametrize(("mode", "expected"), [("exit", "died"), ("hang", "no response")])
def test_subprocess_contains_hard_crashes_and_infinite_loops(mode: str, expected: str) -> None:
    batches = five_minute_batches(200)
    victim = SubprocessHost(
        resolved("crash_b", "crasher", crash_on=3, mode=mode), INSTRUMENTS, call_timeout_s=2.0
    )
    bystander = SubprocessHost(resolved("sma_b", "sma_cross_test"), INSTRUMENTS)
    victim.start()
    bystander.start()
    pid = victim.pid
    bystander_out: list[RunnerOutput] = []
    for batch in batches:
        victim.dispatch(batch)
        bystander.dispatch(batch)
        victim.collect()
        bystander_out.extend(bystander.collect())
    assert victim.state is HostState.FAULTED
    assert victim.fault is not None and expected in victim.fault.message
    assert pid is not None
    with pytest.raises(ProcessLookupError):  # the child process is gone (killed or exited)
        os.kill(pid, 0)
    assert bystander.state is HostState.RUNNING
    bystander.stop()
    reference = run(InProcessHost(resolved("sma_b", "sma_cross_test"), INSTRUMENTS), batches)
    assert signals_of(bystander_out) == signals_of(reference)


def test_time_budget_runs_from_dispatch_whatever_the_collection_order() -> None:
    """A slow instance is faulted (or not) on its own merits: being collected after
    another slow instance must not extend its budget."""
    batches = five_minute_batches(40)

    def fate(order: Sequence[str]) -> dict[str, HostState]:
        sleeps = {"slow_a": 0.6, "slow_b": 1.5}
        hosts = {
            name: SubprocessHost(
                resolved(name, "crasher", crash_on=2, mode="sleep", sleep_s=sleeps[name]),
                INSTRUMENTS,
                call_timeout_s=1.0,
            )
            for name in order
        }
        for host in hosts.values():
            host.start()
        for batch in batches[:15]:  # three 5-minute bars
            for host in hosts.values():
                host.dispatch(batch)
            for host in hosts.values():
                host.collect()
        states = {name: host.state for name, host in hosts.items()}
        for host in hosts.values():
            host.stop()
        return states

    assert fate(["slow_b"]) == {"slow_b": HostState.FAULTED}
    assert fate(["slow_a", "slow_b"]) == {"slow_a": HostState.RUNNING, "slow_b": HostState.FAULTED}
