"""Generic plug-in registry.

Strategies, broker adapters, notifiers, risk rules and market-data providers
are all plug-ins: they register themselves under a unique key (usually with a
decorator) and the core looks them up by that key. Adding a plug-in therefore
means adding a module — never editing the core.

    brokers: Registry[type[BrokerAdapter]] = Registry("broker")

    @brokers.decorator("oanda")
    class OandaAdapter(BrokerAdapter): ...

    brokers.discover("kterminal.brokers")      # import every module → decorators run
    adapter_cls = brokers.get("oanda")
"""

import difflib
import importlib
import pkgutil
import re
from collections.abc import Callable, Iterator
from importlib.metadata import entry_points
from types import ModuleType

from kterminal.core.errors import DuplicateRegistrationError, NotRegisteredError, RegistryError

DEFAULT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class Registry[T]:
    """Maps unique, slug-like keys to plug-ins of one kind."""

    def __init__(
        self,
        kind: str,
        *,
        key_func: Callable[[T], str] | None = None,
        key_pattern: re.Pattern[str] = DEFAULT_KEY_PATTERN,
    ) -> None:
        self.kind = kind
        self._key_func = key_func
        self._key_pattern = key_pattern
        self._items: dict[str, T] = {}

    # ── registration ────────────────────────────────────────────────────────
    def register(self, key: str, item: T) -> T:
        """Register ``item`` under ``key``.

        Re-registering the *same* object is a no-op (modules may be imported
        twice); registering a *different* object under an existing key is an
        error, because silently replacing a strategy or broker is dangerous.
        """
        if not self._key_pattern.fullmatch(key):
            raise RegistryError(
                f"invalid {self.kind} key {key!r}: must match {self._key_pattern.pattern}"
            )
        existing = self._items.get(key)
        if existing is not None and existing is not item:
            raise DuplicateRegistrationError(
                f"{self.kind} {key!r} is already registered to {_describe(existing)}; "
                f"refusing to replace it with {_describe(item)}"
            )
        self._items[key] = item
        return item

    def decorator(self, key: str | None = None) -> Callable[[T], T]:
        """Class/function decorator. Without ``key`` the registry's ``key_func`` is used."""

        def _register(item: T) -> T:
            if key is not None:
                return self.register(key, item)
            if self._key_func is None:
                raise RegistryError(f"{self.kind} registry has no key_func; pass a key explicitly")
            return self.register(self._key_func(item), item)

        return _register

    # ── lookup ──────────────────────────────────────────────────────────────
    def get(self, key: str) -> T:
        try:
            return self._items[key]
        except KeyError:
            hint = difflib.get_close_matches(key, self._items, n=3)
            suggestion = f" Did you mean: {', '.join(hint)}?" if hint else ""
            available = ", ".join(sorted(self._items)) or "none"
            raise NotRegisteredError(
                f"no {self.kind} registered as {key!r}.{suggestion} Available: {available}"
            ) from None

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def keys(self) -> list[str]:
        """Registered keys, sorted (deterministic iteration order)."""
        return sorted(self._items)

    def items(self) -> list[tuple[str, T]]:
        return [(key, self._items[key]) for key in self.keys()]

    # ── discovery ───────────────────────────────────────────────────────────
    def discover(self, package: str | ModuleType) -> list[str]:
        """Import every module below ``package`` so their decorators register plug-ins.

        Import errors are not swallowed: a broken plug-in must stop start-up
        rather than silently disappear from the registry.
        """
        pkg = importlib.import_module(package) if isinstance(package, str) else package
        search_path = getattr(pkg, "__path__", None)
        if search_path is None:
            return [pkg.__name__]
        imported = [pkg.__name__]
        for info in pkgutil.walk_packages(search_path, prefix=f"{pkg.__name__}."):
            leaf = info.name.rsplit(".", 1)[-1]
            if leaf.startswith("_") or leaf in {"tests", "conftest"}:
                continue
            try:
                importlib.import_module(info.name)
            except Exception as exc:
                raise RegistryError(
                    f"failed to import {self.kind} module {info.name!r}: {exc}"
                ) from exc
            imported.append(info.name)
        return imported

    def load_entry_points(self, group: str) -> list[str]:
        """Import plug-in modules advertised by installed packages under ``group``."""
        loaded = []
        for ep in entry_points(group=group):
            try:
                ep.load()
            except Exception as exc:
                raise RegistryError(
                    f"failed to load {self.kind} entry point {ep.name!r}: {exc}"
                ) from exc
            loaded.append(ep.name)
        return loaded


def _describe(item: object) -> str:
    module = getattr(item, "__module__", None)
    name = getattr(item, "__qualname__", None)
    return f"{module}.{name}" if module and name else repr(item)
