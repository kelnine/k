from decimal import Decimal

import pytest
from pydantic import ValidationError

from kterminal.core.registry import Registry
from kterminal.strategy_engine.instances import InstanceConfigError, InstanceSpec, resolve_instance
from kterminal.strategy_engine.registry import StrategyDefinition, definition_from_class
from tests.fixtures.instruments import INSTRUMENTS, XAUUSD
from tests.fixtures.strategies import ContextProbe, Scripted, SmaCross


@pytest.fixture
def registry() -> Registry[StrategyDefinition]:
    reg: Registry[StrategyDefinition] = Registry("strategy definition")
    for cls in (Scripted, SmaCross, ContextProbe):
        d = definition_from_class(cls)
        reg.register(d.id, d)
    return reg


def spec(**kw: object) -> InstanceSpec:
    fields: dict[str, object] = {
        "id": "sma_fast_xau",
        "strategy": "sma_cross_test",
        "params": {"fast": 5, "slow": 20},
        "instruments": ["XAUUSD"],
        "timeframe": "5",
    }
    fields.update(kw)
    return InstanceSpec(**fields)  # type: ignore[arg-type]


def test_resolve_and_version_identity(registry: Registry[StrategyDefinition]) -> None:
    resolved = resolve_instance(spec(), instruments=INSTRUMENTS, definitions=registry)
    assert resolved.timeframe.code == "5m"
    assert resolved.params_document == {"fast": 5, "slow": 20, "stop_atr": "1.5"}
    assert len(resolved.version) == 64
    assert resolved.config["definition"]["code_hash"] == registry.get("sma_cross_test").code_hash
    again = resolve_instance(spec(), instruments=INSTRUMENTS, definitions=registry)
    assert again.config_hash == resolved.config_hash  # deterministic


def test_multiple_instances_of_one_definition_have_distinct_versions(
    registry: Registry[StrategyDefinition],
) -> None:
    fast = resolve_instance(spec(), instruments=INSTRUMENTS, definitions=registry)
    slow = resolve_instance(
        spec(id="sma_slow_xau", params={"fast": 20, "slow": 50}),
        instruments=INSTRUMENTS,
        definitions=registry,
    )
    assert fast.config_hash != slow.config_hash
    assert fast.definition is slow.definition


def test_version_ignores_presentation_but_tracks_behaviour(
    registry: Registry[StrategyDefinition],
) -> None:
    base = resolve_instance(spec(), instruments=INSTRUMENTS, definitions=registry).config_hash
    renamed = resolve_instance(
        spec(name="Fast SMA", description="d", tags=("x",), host="subprocess"),
        instruments=INSTRUMENTS,
        definitions=registry,
    ).config_hash
    assert renamed == base
    defaults_spelled_out = resolve_instance(
        spec(params={"fast": 5, "slow": 20, "stop_atr": "1.5"}),
        instruments=INSTRUMENTS,
        definitions=registry,
    ).config_hash
    assert defaults_spelled_out == base  # effective params, not spelling, define the version
    for changed in (
        spec(params={"fast": 6, "slow": 20}),
        spec(instruments=["XAGUSD"]),
        spec(context_timeframes=["1h"]),
    ):
        assert (
            resolve_instance(changed, instruments=INSTRUMENTS, definitions=registry).config_hash
            != base
        )
    retick = {
        **INSTRUMENTS,
        "XAUUSD": XAUUSD.__class__(
            **{
                **{f: getattr(XAUUSD, f) for f in XAUUSD.__dataclass_fields__},
                "tick_size": Decimal("0.1"),
            }
        ),
    }
    assert resolve_instance(spec(), instruments=retick, definitions=registry).config_hash != base


def test_context_timeframes_merge_meta_and_spec(registry: Registry[StrategyDefinition]) -> None:
    resolved = resolve_instance(
        spec(id="probe_1", strategy="context_probe", params={}, context_timeframes=["15m", "5m"]),
        instruments=INSTRUMENTS,
        definitions=registry,
    )
    assert [tf.code for tf in resolved.context_timeframes] == ["15m", "1h"]  # primary excluded
    assert [tf.code for tf in resolved.timeframes] == ["5m", "15m", "1h"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"strategy": "nope"}, "no strategy definition registered"),
        ({"params": {"fast": 1}}, "invalid params"),
        ({"params": {"unknown": 1}}, "invalid params"),
        ({"instruments": ["BTCUSD"]}, "unknown instrument"),
        ({"timeframe": "15m"}, "supports timeframes 5m"),
    ],
)
def test_invalid_instances(
    registry: Registry[StrategyDefinition], overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(InstanceConfigError, match=message):
        resolve_instance(spec(**overrides), instruments=INSTRUMENTS, definitions=registry)


def test_spec_validation() -> None:
    with pytest.raises(ValidationError, match="instance id"):
        spec(id="Bad Id")
    with pytest.raises(ValidationError, match="at least one instrument"):
        spec(instruments=[])
    with pytest.raises(ValidationError, match="duplicate"):
        spec(instruments=["XAUUSD", "XAUUSD"])
