"""Strategy definitions: registration, discovery and isolation checks.

Internal strategies register with ``@register_strategy``; external
(TradingView) strategies are declared in configuration and registered with
:func:`register_external`. Both live in one namespace of definition ids.

Registration enforces the isolation rules that can be checked statically:

* ``meta`` is a valid :class:`StrategyMeta` and ``Params`` a strict, frozen model;
* the class holds **no mutable class-level state** (lists, dicts, sets, arrays …)
  that two instances of the same strategy could share — checked deeply: inside
  tuples, frozensets, frozen dataclasses/models, nested classes and function
  default arguments too. Per-instance state belongs in ``on_start``;
* ``on_bar`` is implemented.

Module-level globals cannot be checked statically: a definition that keeps
state in its module shares it between its in-process instances. Run such (or
any untrusted) definitions with ``host: subprocess``, which gives every
instance its own interpreter.
"""

import dataclasses
import importlib.util
import inspect
import re
from dataclasses import dataclass
from datetime import date, time, timedelta
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

_IMMUTABLE_SCALARS = (
    str,
    bytes,
    int,
    float,
    complex,
    bool,
    type(None),
    Enum,
    Decimal,
    re.Pattern,
    date,  # includes datetime
    time,
    timedelta,
    range,
)
_MAX_DEPTH = 8
# Interpreter-managed class attributes that are not strategy state.
_CLASS_MACHINERY = frozenset(
    {
        "__module__",
        "__qualname__",
        "__doc__",
        "__dict__",
        "__weakref__",
        "__annotations__",
        "__annotate_func__",
        "__annotations_cache__",
        "__orig_bases__",
        "__parameters__",
        "__type_params__",
        "__firstlineno__",
        "__static_attributes__",
        "__abstractmethods__",
        "_abc_impl",
    }
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
    offenders: list[str] = []
    for klass in cls.__mro__:
        if klass in (Strategy, object) or klass.__module__ == "abc":
            continue
        offenders.extend(_class_body_offenders(klass, klass.__name__, 0))
    params = getattr(cls, "Params", None)
    if isinstance(params, type) and issubclass(params, StrategyParams):
        # Class variables of the Params model are shared by every instance's params.
        for name in sorted(getattr(params, "__class_vars__", ())):
            value = getattr(params, name, None)
            offenders.extend(_mutable_parts(value, f"{params.__name__}.{name}", 1))
    return offenders


def _class_body_offenders(klass: type, path: str, depth: int) -> list[str]:
    offenders: list[str] = []
    for name, value in vars(klass).items():
        if name in _CLASS_MACHINERY or name in {"meta", "Params"}:
            continue
        offenders.extend(_mutable_parts(value, f"{path}.{name}", depth))
    return offenders


def _mutable_parts(value: object, path: str, depth: int) -> list[str]:
    """Paths of the mutable objects reachable from a class attribute (empty = immutable)."""
    if depth > _MAX_DEPTH:
        return [f"{path} (nested too deeply to verify)"]
    if isinstance(value, _IMMUTABLE_SCALARS):
        return []
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    if hasattr(value, "cache_info") or hasattr(value, "cache_clear"):
        return [f"{path} (cached function: its cache is shared by every instance)"]
    if isinstance(value, FunctionType):
        defaults = [*(value.__defaults__ or ()), *(value.__kwdefaults__ or {}).values()]
        return [
            part
            for i, default in enumerate(defaults)
            for part in _mutable_parts(default, f"{path}(default #{i})", depth + 1)
        ]
    if isinstance(value, property):
        return []
    if isinstance(value, type):
        if issubclass(value, (Enum, StrategyParams)) or value.__module__ in {"builtins", "abc"}:
            return []
        return [
            part
            for klass in value.__mro__
            if klass is not object
            for part in _class_body_offenders(klass, f"{path}.{klass.__name__}", depth + 1)
        ]
    if inspect.isdatadescriptor(value) or inspect.ismethoddescriptor(value):
        return []
    if isinstance(value, (tuple, frozenset)):
        return [
            part
            for i, item in enumerate(value)
            for part in _mutable_parts(item, f"{path}[{i}]", depth + 1)
        ]
    fields = _frozen_fields(value)
    if fields is not None:
        return [
            part
            for name in fields
            for part in _mutable_parts(getattr(value, name), f"{path}.{name}", depth + 1)
        ]
    return [f"{path} ({type(value).__name__})"]


def _frozen_fields(value: object) -> list[str] | None:
    """Field names of a frozen dataclass / frozen pydantic model instance, else None."""
    params = getattr(type(value), "__dataclass_params__", None)
    if params is not None and getattr(params, "frozen", False):
        return [f.name for f in dataclasses.fields(value)]  # type: ignore[arg-type]
    config = getattr(type(value), "model_config", None)
    if isinstance(config, dict) and config.get("frozen"):
        return list(getattr(type(value), "model_fields", {}))
    return None


def _source_locations(cls: type, strategies_root: Path | None) -> list[Path]:
    """The code units that define a strategy's behaviour: its own folder/module first,
    then those of every strategy base class it inherits logic from."""
    locations: list[Path] = []
    for klass in cls.__mro__:
        if not (isinstance(klass, type) and issubclass(klass, Strategy)) or klass is Strategy:
            continue
        if klass.__module__.startswith("kterminal.strategy_engine"):
            continue
        location = strategy_source_location(Path(inspect.getfile(klass)), strategies_root)
        if location not in locations:
            locations.append(location)
    return locations


def _combined_code_hash(locations: list[Path]) -> str:
    if len(locations) == 1:
        return code_hash(locations[0])
    parts = [f"{loc.name}:{code_hash(loc)}" for loc in locations]
    return sha256_text("\n".join(parts))


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
    strategies_root = _strategies_root()
    locations = _source_locations(cls, strategies_root)
    location = locations[0]
    return StrategyDefinition(
        id=meta.id,
        kind=StrategyKind.INTERNAL,
        meta=meta,
        code_hash=_combined_code_hash(locations),
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
