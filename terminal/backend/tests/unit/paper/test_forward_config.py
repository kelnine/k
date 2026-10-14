"""What forward sessions read from the configuration: lab.yaml plus instances.d, the
``forward`` section, the parts of the configuration a session depends on, and how much
warm-up each instrument needs."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from kterminal.core.registry import Registry
from kterminal.paper.config import (
    ForwardConfig,
    InstanceFileError,
    LabConfig,
    instance_files,
    load_forward_config,
)
from kterminal.paper.forward import (
    instance_settings_hash,
    lab_config_hash,
    period_levels_used,
    warmup_need,
)
from kterminal.paper.lab import Lab
from kterminal.paper.store import InMemoryLabStore
from kterminal.strategy_engine.periods import Period, period_warmup_bars
from kterminal.strategy_engine.registry import (
    DEFINITIONS,
    StrategyDefinition,
    definition_from_class,
    discover_strategies,
)
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.engine_strategies import Recorder

discover_strategies(entry_points=False)

LAB = {
    "defaults": {"account": {"starting_balance": 50000}},
    "instances": [
        {
            "id": "sma_gold",
            "strategy": "demo_sma_cross",
            "params": {"fast": 9, "slow": 21},
            "instruments": ["XAUUSD"],
            "timeframe": "5m",
        }
    ],
}


def entry(instance_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": instance_id,
        "strategy": "demo_breakout",
        "params": {"channel_bars": 20},
        "instruments": ["NEARUSD"],
        "timeframe": "5m",
        **extra,
    }


def write_lab(root: Path, lab: dict[str, Any] | None = None) -> Path:
    path = root / "lab.yaml"
    path.write_text(yaml.safe_dump(lab or LAB), encoding="utf-8")
    return path


def write_instances(root: Path, name: str, content: Any) -> Path:
    directory = root / "instances.d"
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text(content if isinstance(content, str) else yaml.safe_dump(content), "utf-8")
    return path


# ── instances.d ──────────────────────────────────────────────────────────────
def test_instance_files_are_added_after_lab_yaml_in_file_name_order(tmp_path: Path) -> None:
    lab = write_lab(tmp_path)
    write_instances(tmp_path, "20-jetstream.yaml", [entry("jet_near")])
    write_instances(tmp_path, "10-orb.yml", [entry("orb_near"), entry("orb_near_slow")])
    write_instances(tmp_path, "notes.txt", "not an instance file")
    write_instances(tmp_path, "30-empty.yaml", "")  # an empty file adds nothing

    config = load_forward_config(lab)
    assert [i.id for i in config.instances] == ["sma_gold", "orb_near", "orb_near_slow", "jet_near"]
    assert [p.name for p in instance_files(tmp_path / "instances.d")] == [
        "10-orb.yml",
        "20-jetstream.yaml",
        "30-empty.yaml",
    ]
    # every instance gets its account from lab.yaml's defaults, like lab.yaml's own
    assert config.account_settings(config.instances[-1]).starting_balance == 50000
    # the plain loader (simulations) reads lab.yaml only
    assert [i.id for i in LabConfig.load(lab).instances] == ["sma_gold"]


def test_a_missing_or_empty_directory_adds_nothing(tmp_path: Path) -> None:
    lab = write_lab(tmp_path)
    assert [i.id for i in load_forward_config(lab).instances] == ["sma_gold"]
    (tmp_path / "instances.d").mkdir()
    assert [i.id for i in load_forward_config(lab).instances] == ["sma_gold"]


def test_a_duplicate_id_names_both_files(tmp_path: Path) -> None:
    lab = write_lab(tmp_path)
    write_instances(tmp_path, "a.yaml", [entry("orb_near")])
    write_instances(tmp_path, "b.yaml", [entry("orb_near")])
    both = r"'orb_near' is defined in both instances.d/a.yaml and instances.d/b.yaml"
    with pytest.raises(InstanceFileError, match=both):
        load_forward_config(lab)

    (tmp_path / "instances.d" / "b.yaml").unlink()
    write_instances(tmp_path, "c.yaml", [entry("sma_gold")])
    with pytest.raises(InstanceFileError, match=r"defined in both lab.yaml and instances.d/c.yaml"):
        load_forward_config(lab)

    (tmp_path / "instances.d" / "c.yaml").unlink()
    write_instances(tmp_path, "d.yaml", [entry("twice"), entry("twice")])
    with pytest.raises(InstanceFileError, match=r"'twice' is defined twice in instances.d/d.yaml"):
        load_forward_config(lab)


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ({"id": "x"}, r"instances.d/bad.yaml: expected a YAML list of instance entries"),
        ([entry("ok_one"), {"id": "no_strategy"}], r"instances.d/bad.yaml: entry 2: strategy"),
        ([entry("typo", timeframes="5m")], r"entry 1: timeframes: Extra inputs"),
        ("- [unclosed", r"instances.d/bad.yaml: invalid YAML"),
    ],
)
def test_a_bad_instance_file_is_named(tmp_path: Path, content: Any, error: str) -> None:
    lab = write_lab(tmp_path)
    write_instances(tmp_path, "bad.yaml", content)
    with pytest.raises(InstanceFileError, match=error):
        load_forward_config(lab)


def test_the_forward_section_has_defaults_and_bounds() -> None:
    assert LabConfig.model_validate(LAB).forward == ForwardConfig(
        warmup_days=10, poll_delay_s=2, batch_timeout_s=20
    )
    config = LabConfig.model_validate({**LAB, "forward": {"warmup_days": 3}})
    assert config.forward.warmup_days == 3
    with pytest.raises(ValueError, match="warmup_days"):
        LabConfig.model_validate({**LAB, "forward": {"warmup_days": -1}})
    with pytest.raises(ValueError, match="Extra inputs"):
        LabConfig.model_validate({**LAB, "forward": {"warmup": 3}})


# ── what a session depends on ────────────────────────────────────────────────
def test_the_session_fingerprint_ignores_what_does_not_change_results() -> None:
    base = LabConfig.model_validate(LAB)
    tuned = LabConfig.model_validate(
        {
            **LAB,
            "forward": {"warmup_days": 2, "batch_timeout_s": 30},
            "instances": [
                *LAB["instances"],
                entry("parked", enabled=False),  # a disabled instance
                entry("sma_gold_b", enabled=False),
            ],
            "experiments": [
                {
                    "id": "e",
                    "name": "E",
                    "members": [{"instance": "parked", "label": "A"}],
                }
            ],
        }
    )
    assert lab_config_hash(tuned) == lab_config_hash(base)
    snapshots = LabConfig.model_validate({**LAB, "equity_snapshot_minutes": 5})
    assert lab_config_hash(snapshots) != lab_config_hash(base)

    (gold,) = base.instances
    subprocess = LabConfig.model_validate(
        {**LAB, "instances": [{**LAB["instances"][0], "host": "subprocess"}]}
    )
    assert instance_settings_hash(subprocess, subprocess.instances[0]) == (
        instance_settings_hash(base, gold)
    )
    richer = LabConfig.model_validate(
        {**LAB, "instances": [{**LAB["instances"][0], "account": {"starting_balance": 100000}}]}
    )
    assert instance_settings_hash(richer, richer.instances[0]) != (
        instance_settings_hash(base, gold)
    )


# ── warm-up ──────────────────────────────────────────────────────────────────
def registry() -> Registry[StrategyDefinition]:
    reg: Registry[StrategyDefinition] = Registry("strategy definition")
    for definition_id, definition in DEFINITIONS.items():
        reg.register(definition_id, definition)
    recorder = definition_from_class(Recorder)
    reg.register(recorder.id, recorder)
    return reg


def test_period_levels_are_read_from_the_strategy_code() -> None:
    reg = registry()
    assert period_levels_used(reg.get("recorder")) == (Period.DAY,)  # ctx.periods.previous("D")
    assert period_levels_used(reg.get("demo_sma_cross")) == ()


async def test_each_instrument_warms_up_for_the_largest_need_of_its_instances() -> None:
    config = LabConfig.model_validate(
        {
            "instances": [
                {  # warmup_bars 50 of its largest timeframe (1h): (50 + 1) x 60 base bars
                    "id": "sma_gold",
                    "strategy": "demo_sma_cross",
                    "params": {"fast": 3, "slow": 8},
                    "instruments": ["XAUUSD"],
                    "timeframe": "5m",
                    "context_timeframes": ["1h"],
                },
                {  # warmup_bars 0, but it reads the previous trading day on 5m bars
                    "id": "levels_gold",
                    "strategy": "recorder",
                    "instruments": ["XAUUSD", "NEARUSD"],
                    "timeframe": "5m",
                },
                {
                    "id": "sma_near",
                    "strategy": "demo_sma_cross",
                    "params": {"fast": 3, "slow": 8},
                    "instruments": ["NEARUSD"],
                    "timeframe": "1m",
                },
            ]
        }
    )
    lab = Lab(config, lab_catalog(), InMemoryLabStore(), definitions=registry(), discover=False)
    await lab.setup()
    levels = period_warmup_bars("D", "5m") * 5  # 601 five-minute bars of 1m bars
    assert warmup_need(lab) == {"XAUUSD": max(51 * 60, levels), "NEARUSD": levels}
    assert levels == 3_005 < 51 * 60
