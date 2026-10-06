"""Strategy definitions: registration, discovery and isolation checks.

Internal strategies register with ``@register_strategy``; external
(TradingView) strategies are declared in configuration and registered with
:func:`register_external`. Both live in one namespace of definition ids.

Registration enforces the isolation rules that can be checked statically:

* ``meta`` is a valid :class:`StrategyMeta` and ``Params`` a strict, frozen model;
* the class holds **no mutable class-level state** (lists, dicts, sets, arrays …)
  that two instances of the same strategy could share — per-instance state
  belongs in ``on_start``;
* ``on_bar`` is implemented.
"""

import importlib.util
import inspect
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Any

from kterminal.core.enums import StrategyKind
from kterminal.core.errors import KTerminalError
from kterminal.core.registry import Registry
from kterminal.strategy_engine.base import Strategy, StrategyMeta, StrategyParams
from kterminal.strategy_engine.versioning import (
    code_hash,
    sha256_text,
    strategy_source_location,
)

ENTRY_POINT_GROUP = "kterminal.strategies"
STRATEGIES_PACKAGE = "kterminal.strategies"

_IMMUTABLE_TYPES = (
    str,
    bytes,
    int,
    float,
    complex,
    bool,
    type(None),
    tuple,
    frozenset,
    Enum,
    Decimal,
    re.Pattern,
)


class StrategyDefinitionError(KTerminalError):
    """A strategy class or declaration breaks the SDK rules."""


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    id: str
    kind: StrategyKind
    meta: StrategyMeta
    code_hash: str
    strategy_cls: type[Strategy[Any]] | None = None  # None for EXTERNAL definitions
    module: str | None = None
    qualname: str | None = None
    source_path: str | None = None

    @property
    def params_model(self) -> type[StrategyParams]:
        if self.strategy_cls is None:
            return StrategyParams
        return self.strategy_cls.Params


DEFINITIONS: Registry[StrategyDefinition] = Registry(
    "strategy definition", key_pattern=re.compile(r"^[a-z][a-z0-9_]{2,63}$")
)


def _mutable_class_attributes(cls: type) -> list[str]:
    offenders = []
    for klass in cls.__mro__:
        if klass in (Strategy, object) or klass.__module__ == "abc":
            continue
        for name, value in vars(klass).items():
            if name.startswith("__") or name in {"meta", "Params", "_abc_impl"}:
                continue
            if isinstance(value, (FunctionType, staticmethod, classmethod, property, type)):
                continue
            if inspect.isdatadescriptor(value) or inspect.ismethoddescriptor(value):
                continue
            if isinstance(value, _IMMUTABLE_TYPES) or _is_frozen(value):
                continue
            offenders.append(f"{klass.__name__}.{name} ({type(value).__name__})")
    return offenders


def _is_frozen(value: object) -> bool:
    params = getattr(type(value), "__dataclass_params__", None)
    if params is not None and getattr(params, "frozen", False):
        return True
    config = getattr(type(value), "model_config", None)
    return isinstance(config, dict) and bool(config.get("frozen"))


def definition_from_class(cls: type[Strategy[Any]]) -> StrategyDefinition:
    if not (isinstance(cls, type) and issubclass(cls, Strategy)):
        raise StrategyDefinitionError(f"{cls!r} is not a Strategy subclass")
    meta = getattr(cls, "meta", None)
    if not isinstance(meta, StrategyMeta):
        raise StrategyDefinitionError(f"{cls.__qualname__} must define meta = StrategyMeta(...)")
    if meta.kind is not StrategyKind.INTERNAL:
        raise StrategyDefinitionError(f"{meta.id}: Python strategies must have kind INTERNAL")
    params = cls.Params
    if not (isinstance(params, type) and issubclass(params, StrategyParams)):
        raise StrategyDefinitionError(f"{meta.id}: Params must subclass StrategyParams")
    config = params.model_config
    if not config.get("frozen") or config.get("extra") != "forbid":
        raise StrategyDefinitionError(
            f"{meta.id}: Params must stay frozen with extra='forbid' (do not override model_config)"
        )
    if inspect.isabstract(cls):
        raise StrategyDefinitionError(f"{meta.id}: on_bar must be implemented")
    offenders = _mutable_class_attributes(cls)
    if offenders:
        raise StrategyDefinitionError(
            f"{meta.id}: mutable class-level state would be shared between instances: "
            f"{', '.join(offenders)}. Initialise per-instance state in on_start()."
        )
    module_file = Path(inspect.getfile(cls))
    strategies_root = _strategies_root()
    location = strategy_source_location(module_file, strategies_root)
    return StrategyDefinition(
        id=meta.id,
        kind=StrategyKind.INTERNAL,
        meta=meta,
        code_hash=code_hash(location),
        strategy_cls=cls,
        module=cls.__module__,
        qualname=cls.__qualname__,
        source_path=str(location),
    )


def register_strategy[S: type[Strategy[Any]]](cls: S) -> S:
    """Class decorator: validate the strategy and add it to the definition registry."""
    definition = definition_from_class(cls)
    if definition.id in DEFINITIONS and DEFINITIONS.get(definition.id).strategy_cls is cls:
        return cls  # the same class imported twice: idempotent
    DEFINITIONS.register(definition.id, definition)
    return cls


def register_external(meta: StrategyMeta, *, pine_source: Path | None = None) -> StrategyDefinition:
    """Register an EXTERNAL (TradingView) definition. Its code hash is the Pine source's
    hash when provided, otherwise a hash of its declared version."""
    if meta.kind is not StrategyKind.EXTERNAL:
        meta = meta.model_copy(update={"kind": StrategyKind.EXTERNAL})
    digest = (
        code_hash(pine_source)
        if pine_source is not None
        else sha256_text(f"external:{meta.id}:{meta.version}")
    )
    definition = StrategyDefinition(
        id=meta.id,
        kind=StrategyKind.EXTERNAL,
        meta=meta,
        code_hash=digest,
        source_path=str(pine_source) if pine_source else None,
    )
    if meta.id in DEFINITIONS and DEFINITIONS.get(meta.id) == definition:
        return definition
    DEFINITIONS.register(meta.id, definition)
    return definition


def discover_strategies(
    package: str | ModuleType = STRATEGIES_PACKAGE, *, entry_points: bool = True
) -> list[str]:
    """Import every strategy module so its decorator registers it. Returns definition ids."""
    DEFINITIONS.discover(package)
    if entry_points:
        DEFINITIONS.load_entry_points(ENTRY_POINT_GROUP)
    return DEFINITIONS.keys()


def _strategies_root() -> Path | None:
    """Location of the plug-in package, found without importing it (plug-ins sit above
    the engine in the architecture, so the engine refers to them only by name)."""
    spec = importlib.util.find_spec(STRATEGIES_PACKAGE)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))
