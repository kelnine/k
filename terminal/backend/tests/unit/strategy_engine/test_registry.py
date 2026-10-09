import functools
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import ConfigDict

from kterminal.core.enums import StrategyKind
from kterminal.domain.market import Bar
from kterminal.strategy_engine import (
    SignalOutput,
    Strategy,
    StrategyDefinitionError,
    StrategyMeta,
    StrategyParams,
)
from kterminal.strategy_engine.registry import (
    DEFINITIONS,
    definition_from_class,
    discover_strategies,
    register_external,
)
from tests.fixtures.strategies import (
    Scripted,
    SharedViaDefaultArgument,
    SharedViaFrozenDataclass,
    SharedViaNestedClass,
    SharedViaTuple,
    SmaCross,
)


def meta(id_: str = "probe") -> StrategyMeta:
    return StrategyMeta(id=id_, name="Probe", version="1.0.0")


def test_definition_from_valid_class() -> None:
    definition = definition_from_class(SmaCross)
    assert definition.id == "sma_cross_test"
    assert definition.kind is StrategyKind.INTERNAL
    assert len(definition.code_hash) == 64
    assert definition.module == "tests.fixtures.strategies"
    assert definition.params_model.__name__ == "SmaParams"


def test_mutable_class_state_is_rejected() -> None:
    class Leaky(Strategy[StrategyParams]):
        meta = StrategyMeta(id="leaky", name="Leaky", version="1.0.0")
        history: ClassVar[list[float]] = []  # shared by every instance → forbidden
        lookup: ClassVar[dict[str, int]] = {}
        THRESHOLD = 0.5  # immutable constants are fine

        def on_bar(self, bar: Bar) -> SignalOutput:
            return None

    with pytest.raises(StrategyDefinitionError, match=r"Leaky\.history .*Leaky\.lookup"):
        definition_from_class(Leaky)


@pytest.mark.parametrize(
    ("cls", "where"),
    [
        (SharedViaFrozenDataclass, r"MEMORY\.closes \(list\)"),
        (SharedViaTuple, r"SEEN\[0\] \(list\)"),
        (SharedViaNestedClass, r"Cache\.hits \(dict\)"),
        (SharedViaDefaultArgument, r"on_bar\(default #0\) \(list\)"),
    ],
)
def test_mutable_state_hidden_in_immutable_wrappers_is_rejected(cls: type, where: str) -> None:
    with pytest.raises(StrategyDefinitionError, match=where):
        definition_from_class(cls)  # type: ignore[arg-type]


def test_params_must_stay_frozen_and_strict() -> None:
    class LooseParams(StrategyParams):
        model_config = ConfigDict(frozen=False, extra="allow")

    class Loose(Strategy[LooseParams]):
        meta = StrategyMeta(id="loose", name="Loose", version="1.0.0")
        Params = LooseParams

        def on_bar(self, bar: Bar) -> SignalOutput:
            return None

    with pytest.raises(StrategyDefinitionError, match="frozen"):
        definition_from_class(Loose)


def test_on_bar_required_and_meta_required() -> None:
    class Abstract(Strategy[StrategyParams]):
        meta = StrategyMeta(id="abstract_one", name="A", version="1.0.0")

    with pytest.raises(StrategyDefinitionError, match="on_bar"):
        definition_from_class(Abstract)

    class NoMeta(Strategy[StrategyParams]):
        def on_bar(self, bar: Bar) -> SignalOutput:
            return None

    with pytest.raises(StrategyDefinitionError, match="meta"):
        definition_from_class(NoMeta)


@pytest.mark.parametrize("bad", ["X", "ab", "Has-Caps", "1abc"])
def test_meta_validation(bad: str) -> None:
    with pytest.raises(ValueError, match="strategy id"):
        StrategyMeta(id=bad, name="x", version="1.0.0")
    with pytest.raises(ValueError, match="semantic"):
        StrategyMeta(id="valid_id", name="x", version="v1")


def test_code_hash_changes_with_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "hashpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    source = (
        "from kterminal.strategy_engine import Strategy, StrategyMeta, StrategyParams\n"
        "class S(Strategy[StrategyParams]):\n"
        "    meta = StrategyMeta(id='hash_probe', name='h', version='1.0.0')\n"
        "    def on_bar(self, bar):\n"
        "        return None  # v1\n"
    )
    (pkg / "mod.py").write_text(source)
    monkeypatch.syspath_prepend(str(tmp_path))
    import importlib

    first = definition_from_class(importlib.import_module("hashpkg.mod").S)
    (pkg / "mod.py").write_text(source.replace("# v1", "# v2"))
    import sys

    del sys.modules["hashpkg.mod"]
    second = definition_from_class(importlib.import_module("hashpkg.mod").S)
    assert first.code_hash != second.code_hash  # edited code without bumping version → new hash


def test_code_hash_covers_inherited_strategy_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("inhpkg", "inhpkg/orb_base", "inhpkg/orb_xau"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text("")
    base = (
        "from kterminal.strategy_engine import Strategy, StrategyMeta, StrategyParams\n"
        "class OrbBase(Strategy[StrategyParams]):\n"
        "    def on_bar(self, bar):\n"
        "        return None  # threshold 1\n"
    )
    (tmp_path / "inhpkg/orb_base/strategy.py").write_text(base)
    (tmp_path / "inhpkg/orb_xau/strategy.py").write_text(
        "from kterminal.strategy_engine import StrategyMeta\n"
        "from inhpkg.orb_base.strategy import OrbBase\n"
        "class OrbXau(OrbBase):\n"
        "    meta = StrategyMeta(id='orb_xau_probe', name='o', version='1.0.0')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    import importlib
    import sys

    first = definition_from_class(importlib.import_module("inhpkg.orb_xau.strategy").OrbXau)
    (tmp_path / "inhpkg/orb_base/strategy.py").write_text(base.replace("1", "50"))
    for module in [m for m in sys.modules if m.startswith("inhpkg")]:
        del sys.modules[module]
    second = definition_from_class(importlib.import_module("inhpkg.orb_xau.strategy").OrbXau)
    assert first.code_hash != second.code_hash  # the inherited logic changed


def test_state_shared_through_params_dunders_or_caches_is_rejected() -> None:
    class P(StrategyParams):
        seen: ClassVar[dict[str, int]] = {}

    class Sneaky(Strategy[P]):
        meta = StrategyMeta(id="sneaky", name="Sneaky", version="1.0.0")
        Params = P
        __levels__: ClassVar[list[float]] = []

        @staticmethod
        @functools.cache
        def table() -> list[float]:
            return []

        def on_bar(self, bar: Bar) -> SignalOutput:
            return None

    with pytest.raises(StrategyDefinitionError) as excinfo:
        definition_from_class(Sneaky)
    message = str(excinfo.value)
    assert "Sneaky.__levels__ (list)" in message
    assert "Sneaky.table (cached function" in message
    assert "P.seen (dict)" in message


def test_register_external_definitions() -> None:
    external = register_external(StrategyMeta(id="tv_probe_external", name="TV", version="1.2.0"))
    assert external.kind is StrategyKind.EXTERNAL
    assert external.strategy_cls is None
    assert (
        register_external(StrategyMeta(id="tv_probe_external", name="TV", version="1.2.0"))
        == external
    )
    assert DEFINITIONS.get("tv_probe_external") is external


def test_discovery_registers_the_builtin_demo_strategies() -> None:
    ids = discover_strategies(entry_points=False)
    assert isinstance(ids, list)
    assert all(DEFINITIONS.get(i).id == i for i in ids)


def test_scripted_fixture_is_valid() -> None:
    assert definition_from_class(Scripted).meta.warmup_bars == 0
