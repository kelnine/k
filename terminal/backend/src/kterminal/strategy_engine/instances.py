"""Strategy instances: configured, independently measured lab subjects.

One definition (e.g. ``sma_cross``) can be run as many instances with
different parameters, instruments or timeframes (``sma_fast_xau``,
``sma_slow_xau`` …). Each instance has its own id, account and metrics.

:func:`resolve_instance` validates an :class:`InstanceSpec` against its
definition and the instrument catalog and computes the instance's version
identity: a canonical document of everything that determines its signals,
and the SHA-256 of that document (``config_hash``). The config hash is
stamped on every signal as ``strategy_version``.
"""

import contextlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from kterminal.core.canonical import canonical_data, decimal_text
from kterminal.core.errors import KTerminalError
from kterminal.core.registry import Registry
from kterminal.domain.instruments import Instrument
from kterminal.domain.timeframes import Timeframe
from kterminal.strategy_engine.base import StrategyParams
from kterminal.strategy_engine.registry import DEFINITIONS, StrategyDefinition
from kterminal.strategy_engine.versioning import hash_data

INSTANCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class InstanceConfigError(KTerminalError):
    """An instance configuration is invalid for its definition or the catalog."""


class InstanceSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    strategy: str = Field(description="Definition id")
    name: str | None = None
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    instruments: tuple[str, ...]
    timeframe: str
    context_timeframes: tuple[str, ...] = ()
    host: Literal["in_process", "subprocess"] = "in_process"
    enabled: bool = True
    tags: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not INSTANCE_ID_PATTERN.fullmatch(value):
            raise ValueError(f"instance id {value!r} must match {INSTANCE_ID_PATTERN.pattern}")
        return value

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, value: str) -> str:
        return Timeframe.parse(value).code

    @field_validator("context_timeframes")
    @classmethod
    def _context(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(Timeframe.parse(tf).code for tf in value))

    @model_validator(mode="after")
    def _instruments(self) -> "InstanceSpec":
        if not self.instruments:
            raise ValueError("an instance needs at least one instrument")
        if len(set(self.instruments)) != len(self.instruments):
            raise ValueError("duplicate instruments")
        return self

    @property
    def display_name(self) -> str:
        return self.name or self.id


@dataclass(frozen=True, slots=True)
class ResolvedInstance:
    spec: InstanceSpec
    definition: StrategyDefinition
    params: StrategyParams
    timeframe: Timeframe
    context_timeframes: tuple[Timeframe, ...]
    config: dict[str, Any]
    config_hash: str

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def version(self) -> str:
        """The value stamped on signals as ``strategy_version``."""
        return self.config_hash

    @property
    def timeframes(self) -> tuple[Timeframe, ...]:
        return tuple(sorted({self.timeframe, *self.context_timeframes}))

    @property
    def params_document(self) -> dict[str, Any]:
        return self.params.model_dump(mode="json")


def resolve_instance(
    spec: InstanceSpec,
    *,
    instruments: Mapping[str, Instrument],
    sessions: Any | None = None,
    definitions: Registry[StrategyDefinition] = DEFINITIONS,
) -> ResolvedInstance:
    """Validate ``spec`` and compute its version identity."""
    try:
        definition = definitions.get(spec.strategy)
    except LookupError as exc:
        raise InstanceConfigError(f"instance {spec.id}: {exc}") from None
    meta = definition.meta

    try:
        params = definition.params_model.model_validate(spec.params)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        )
        raise InstanceConfigError(f"instance {spec.id}: invalid params — {problems}") from None

    resolved_instruments: dict[str, Instrument] = {}
    for symbol in spec.instruments:
        if symbol not in instruments:
            raise InstanceConfigError(f"instance {spec.id}: unknown instrument {symbol!r}")
        instrument = instruments[symbol]
        if meta.instruments is not None and symbol not in meta.instruments:
            raise InstanceConfigError(
                f"instance {spec.id}: {meta.id} supports only {', '.join(meta.instruments)}"
            )
        if meta.asset_classes is not None and instrument.asset_class not in meta.asset_classes:
            raise InstanceConfigError(
                f"instance {spec.id}: {meta.id} does not trade {instrument.asset_class} instruments"
            )
        resolved_instruments[symbol] = instrument

    timeframe = Timeframe.parse(spec.timeframe)
    if meta.timeframes and timeframe.code not in meta.timeframes:
        raise InstanceConfigError(
            f"instance {spec.id}: {meta.id} supports timeframes {', '.join(meta.timeframes)}, "
            f"not {timeframe}"
        )
    context = tuple(
        sorted(
            {Timeframe.parse(tf) for tf in (*meta.context_timeframes, *spec.context_timeframes)}
            - {timeframe}
        )
    )
    for tf in (timeframe, *context):
        if not tf.is_intraday:
            raise InstanceConfigError(
                f"instance {spec.id}: timeframe {tf} is not supported yet — bars are built "
                "from the intraday base stream; session-anchored daily/weekly bars arrive "
                "with the market-data layer"
            )

    session_docs: dict[str, Any] = {}
    classification: list[dict[str, Any]] = []
    if sessions is not None:
        # ctx.session() is always available, so the classification is part of every
        # version: the ordered window ids and what each window is.
        for window_id in getattr(sessions, "classification", ()):
            classification.append({"id": window_id, **_behaviour(sessions.window(window_id))})
    if meta.sessions:
        if sessions is None:
            raise InstanceConfigError(
                f"instance {spec.id}: {meta.id} uses sessions {meta.sessions} but no session "
                "book is configured"
            )
        for window_id in meta.sessions:
            try:
                session_docs[window_id] = _behaviour(sessions.window(window_id))
            except KeyError as exc:
                raise InstanceConfigError(f"instance {spec.id}: {exc}") from None
    trading_days: dict[str, Any] = {}
    if sessions is not None:
        for instrument in resolved_instruments.values():
            with contextlib.suppress(KeyError):  # instruments without a configured rule
                trading_days[instrument.trading_day] = _behaviour(
                    sessions.trading_day_rule(instrument.trading_day)
                )

    config: dict[str, Any] = {
        "definition": {
            "id": definition.id,
            "kind": definition.kind.value,
            "version": meta.version,
            "code_hash": definition.code_hash,
        },
        "params": canonical_data(params.model_dump()),
        "instruments": {
            symbol: {
                "tick_size": decimal_text(inst.tick_size),
                "quote_currency": inst.quote_currency,
                "trading_day": inst.trading_day,
            }
            for symbol, inst in sorted(resolved_instruments.items())
        },
        "timeframe": timeframe.code,
        "context_timeframes": [tf.code for tf in context],
        "sessions": session_docs,
        "session_classification": classification,
        "trading_day_rules": trading_days,
        "behaviour": {
            "on_opposite_signal": meta.on_opposite_signal,
            "max_pyramiding": meta.max_pyramiding,
            "warmup_bars": meta.warmup_bars,
        },
    }
    return ResolvedInstance(
        spec=spec,
        definition=definition,
        params=params,
        timeframe=timeframe,
        context_timeframes=context,
        config=config,
        config_hash=hash_data(config),
    )


def _behaviour(item: Any) -> dict[str, Any]:
    """What a session window / trading-day rule *does* — its labels (name, description)
    cannot change a signal, so editing them must not create a new version."""
    return {k: v for k, v in item.to_dict().items() if k not in {"name", "description"}}
