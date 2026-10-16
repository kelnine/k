from pathlib import Path

import pytest

from kterminal.core.errors import DuplicateRegistrationError, NotRegisteredError, RegistryError
from kterminal.core.registry import Registry


class Broker:
    name = "base"


class Oanda(Broker):
    name = "oanda"


class Paper(Broker):
    name = "paper"


def test_register_and_get() -> None:
    brokers: Registry[type[Broker]] = Registry("broker")
    brokers.register("oanda", Oanda)
    assert brokers.get("oanda") is Oanda
    assert "oanda" in brokers
    assert len(brokers) == 1


def test_decorator_with_explicit_key_and_key_func() -> None:
    explicit: Registry[type[Broker]] = Registry("broker")
    derived: Registry[type[Broker]] = Registry("broker", key_func=lambda cls: cls.name)

    @explicit.decorator("paper_v2")
    class PaperV2(Broker):
        pass

    derived.decorator()(Oanda)
    assert explicit.get("paper_v2") is PaperV2
    assert derived.get("oanda") is Oanda


def test_decorator_without_key_requires_key_func() -> None:
    registry: Registry[type[Broker]] = Registry("broker")
    with pytest.raises(RegistryError, match="key_func"):
        registry.decorator()(Oanda)


def test_reregistering_same_object_is_idempotent_but_replacing_is_refused() -> None:
    registry: Registry[type[Broker]] = Registry("broker")
    registry.register("oanda", Oanda)
    registry.register("oanda", Oanda)
    with pytest.raises(DuplicateRegistrationError, match="refusing to replace"):
        registry.register("oanda", Paper)


@pytest.mark.parametrize("key", ["", "Oanda", "1broker", "has space", "x", "a" * 65])
def test_invalid_keys_are_rejected(key: str) -> None:
    with pytest.raises(RegistryError, match="invalid broker key"):
        Registry[type[Broker]]("broker").register(key, Oanda)


def test_lookup_error_suggests_close_matches() -> None:
    registry: Registry[type[Broker]] = Registry("broker")
    registry.register("oanda", Oanda)
    registry.register("paper", Paper)
    with pytest.raises(NotRegisteredError, match="Did you mean: oanda") as excinfo:
        registry.get("oandaa")
    assert isinstance(excinfo.value, LookupError)
    assert "Available: oanda, paper" in str(excinfo.value)


def test_iteration_is_sorted_and_deterministic() -> None:
    registry: Registry[type[Broker]] = Registry("broker")
    registry.register("paper", Paper)
    registry.register("oanda", Oanda)
    assert registry.keys() == ["oanda", "paper"]
    assert list(registry) == ["oanda", "paper"]
    assert registry.items() == [("oanda", Oanda), ("paper", Paper)]


def test_discover_imports_plugin_modules_recursively_and_skips_private() -> None:
    from tests.fixtures.sample_plugins import PLUGINS

    imported = PLUGINS.discover("tests.fixtures.sample_plugins")
    assert PLUGINS.keys() == ["alpha", "beta"]
    assert "tests.fixtures.sample_plugins.nested.beta" in imported
    assert not any(name.endswith("_private") for name in imported)


def test_discover_surfaces_broken_plugins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "broken_plugins"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "bad.py").write_text("raise ImportError('missing dependency')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(RegistryError, match=r"broken_plugins\.bad"):
        Registry[type]("sample").discover("broken_plugins")
