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

Every instance gets its own account built from ``defaults.account`` merged
with its own ``account`` overrides.
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from kterminal.domain.accounts import AccountSettings
from kterminal.domain.timeframes import Timeframe
from kterminal.strategy_engine.base import StrategyMeta
from kterminal.strategy_engine.instances import InstanceSpec


class LabDefaults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: Literal["in_process", "subprocess"] = "in_process"
    account: dict[str, Any] = Field(default_factory=dict)


class ExternalStrategyConfig(StrategyMeta):
    """An EXTERNAL (TradingView) definition; ``pine_source`` is hashed for versioning."""

    pine_source: str | None = None


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
    def load(cls, path: str | Path) -> "LabConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
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
        )

    @property
    def enabled_instances(self) -> tuple[LabInstance, ...]:
        return tuple(i for i in self.instances if i.enabled)
