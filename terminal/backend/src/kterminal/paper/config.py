"""Lab configuration (``terminal/config/lab.yaml``).

    base_timeframe: 1m
    equity_snapshot_minutes: 15
    defaults:
      host: in_process
      account: {starting_balance: 50000, currency: USD, venue_profile: lab_default,
                risk_per_trade_pct: 0.5, max_open_positions: 1}
    external_strategies:          # TradingView scripts, declared not coded
      - {id: breakout_retest_tv, name: ..., version: 1.0.0, timeframes: [5m]}
    instances:
      - id: sma_fast_xau
        strategy: sma_cross
        params: {fast: 9, slow: 21}
        instruments: [XAUUSD]
        timeframe: 5m
        context_timeframes: [15m, 1h]
        account: {starting_balance: 100000}     # optional per-instance override
        on_opposite_signal: ignore               # optional; default: the strategy's meta
        skip_entry_beyond_levels: true           # optional; default: the strategy's meta

Every instance gets its own account built from ``defaults.account`` merged
with its own ``account`` overrides. ``on_opposite_signal`` and
``skip_entry_beyond_levels`` override the definition's position rules for this
instance (its theoretical book and its account alike); they are part of the
instance's version.

Forward paper trading (``kterminal paper start``, the engine) also reads every
``*.yaml`` / ``*.yml`` file in ``instances.d/`` next to ``lab.yaml``, in file-name
order: each holds a YAML list of instance entries with the schema above, added
after ``lab.yaml``'s own instances. An id defined twice is an error naming both
files. The optional ``forward`` section tunes the forward runtime::

    forward:
      warmup_days: 10        # how far back warm-up history may reach (cap)
      poll_delay_s: 2        # first poll this long after a minute closed
      batch_timeout_s: 20    # then process the minute without instruments still missing
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from kterminal.domain.accounts import AccountSettings
from kterminal.domain.timeframes import Timeframe
from kterminal.strategy_engine.base import StrategyMeta
from kterminal.strategy_engine.instances import InstanceSpec
from kterminal.strategy_engine.model import OppositeSignalPolicy


class LabDefaults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: Literal["in_process", "subprocess"] = "in_process"
    account: dict[str, Any] = Field(default_factory=dict)


class ExternalStrategyConfig(StrategyMeta):
    """An EXTERNAL (TradingView) definition; ``pine_source`` is hashed for versioning."""

    pine_source: str | None = None


class ForwardConfig(BaseModel):
    """Forward-runtime tuning (``forward:`` in lab.yaml). Not part of a session's
    identity: changing it never stops an open session from resuming."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    warmup_days: float = Field(default=10.0, ge=0, le=366)
    poll_delay_s: float = Field(default=2.0, ge=0, le=50)
    batch_timeout_s: float = Field(default=20.0, gt=0, le=55)


class LabInstance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    strategy: str
    name: str | None = None
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    instruments: tuple[str, ...]
    timeframe: str
    context_timeframes: tuple[str, ...] = ()
    host: Literal["in_process", "subprocess"] | None = None
    enabled: bool = True
    tags: tuple[str, ...] = ()
    account: dict[str, Any] = Field(default_factory=dict)
    on_opposite_signal: OppositeSignalPolicy | None = None  # None = the definition's meta
    skip_entry_beyond_levels: bool | None = None  # None = the definition's meta


class ExperimentMember(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instance: str
    label: str  # e.g. "A", "A+EMA", "A+B+LIQ"


class ExperimentConfig(BaseModel):
    """A set of instances compared under identical conditions (Experiment mode, Phase 4+).

    Variants such as "A + EMA filter" are separate instances (of a composite
    definition), never modifications of A, so each stays independently measurable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str = ""
    members: tuple[ExperimentMember, ...]


class LabConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_timeframe: str = "1m"
    equity_snapshot_minutes: int = Field(default=15, ge=1, le=1_440)
    defaults: LabDefaults = Field(default_factory=LabDefaults)
    external_strategies: tuple[ExternalStrategyConfig, ...] = ()
    instances: tuple[LabInstance, ...] = ()
    experiments: tuple[ExperimentConfig, ...] = ()
    forward: ForwardConfig = Field(default_factory=ForwardConfig)

    @model_validator(mode="after")
    def _unique_and_valid(self) -> "LabConfig":
        Timeframe.parse(self.base_timeframe)
        ids = [i.id for i in self.instances]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate instance ids: {', '.join(duplicates)}")
        for instance in self.instances:
            self.account_settings(instance)  # validate merged account settings early
            self.instance_spec(instance)
        by_id = {i.id: i for i in self.instances}
        for experiment in self.experiments:
            unknown = [m.instance for m in experiment.members if m.instance not in by_id]
            if unknown:
                raise ValueError(f"experiment {experiment.id}: unknown instances {unknown}")
            conditions = {
                self.account_settings(by_id[m.instance]).document_json() for m in experiment.members
            }
            if len(conditions) > 1:
                raise ValueError(
                    f"experiment {experiment.id}: members must share identical account "
                    "settings (balance, currency, venue profile, risk, limits)"
                )
        return self

    @classmethod
    def load(cls, path: str | Path, *, instances_dir: str | Path | None = None) -> "LabConfig":
        """``lab.yaml``, plus the instance files in ``instances_dir`` when given (a missing
        or empty directory adds nothing)."""
        file = Path(path)
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        if instances_dir is not None:
            if not isinstance(data, dict):
                raise InstanceFileError(f"{file.name}: expected a mapping")
            data = {**data, "instances": _merged_instances(file, data, Path(instances_dir))}
        return cls.model_validate(data)

    def account_settings(self, instance: LabInstance) -> AccountSettings:
        return AccountSettings.model_validate({**self.defaults.account, **instance.account})

    def instance_spec(self, instance: LabInstance) -> InstanceSpec:
        return InstanceSpec(
            id=instance.id,
            strategy=instance.strategy,
            name=instance.name,
            description=instance.description,
            params=instance.params,
            instruments=instance.instruments,
            timeframe=instance.timeframe,
            context_timeframes=instance.context_timeframes,
            host=instance.host or self.defaults.host,
            enabled=instance.enabled,
            tags=instance.tags,
            on_opposite_signal=instance.on_opposite_signal,
            skip_entry_beyond_levels=instance.skip_entry_beyond_levels,
        )

    @property
    def enabled_instances(self) -> tuple[LabInstance, ...]:
        return tuple(i for i in self.instances if i.enabled)


INSTANCES_DIR = "instances.d"


def load_forward_config(lab_path: str | Path) -> LabConfig:
    """The configuration forward paper trading runs: ``lab.yaml`` plus the instance files
    in ``instances.d/`` beside it."""
    path = Path(lab_path)
    return LabConfig.load(path, instances_dir=path.parent / INSTANCES_DIR)


class InstanceFileError(ValueError):
    """An ``instances.d`` file cannot be used (not a list, bad entry, duplicate id)."""


def instance_files(directory: Path) -> list[Path]:
    """The instance files of ``directory`` in the order they are read (by file name)."""
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix in (".yaml", ".yml")),
        key=lambda p: p.name,
    )


def _merged_instances(lab_file: Path, data: dict[str, Any], directory: Path) -> list[Any]:
    entries: list[Any] = list(data.get("instances") or [])
    origin: dict[str, str] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            origin.setdefault(entry["id"], lab_file.name)
    for file in instance_files(directory):
        where = f"{directory.name}/{file.name}"
        try:
            loaded = yaml.safe_load(file.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise InstanceFileError(f"{where}: invalid YAML: {exc}") from None
        if loaded is None:
            continue
        if not isinstance(loaded, list):
            raise InstanceFileError(f"{where}: expected a YAML list of instance entries")
        for index, entry in enumerate(loaded, start=1):
            try:
                instance = LabInstance.model_validate(entry)
            except ValidationError as exc:
                problems = "; ".join(
                    f"{'.'.join(str(part) for part in error['loc']) or 'entry'}: {error['msg']}"
                    for error in exc.errors(include_input=False, include_url=False)
                )
                raise InstanceFileError(f"{where}: entry {index}: {problems}") from None
            if instance.id in origin:
                first = origin[instance.id]
                raise InstanceFileError(
                    f"instance id {instance.id!r} is defined twice in {where}"
                    if first == where
                    else f"instance id {instance.id!r} is defined in both {first} and {where}"
                )
            origin[instance.id] = where
            entries.append(entry)
    return entries
