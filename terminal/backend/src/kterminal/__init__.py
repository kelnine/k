"""K Terminal — a modular algorithmic trading terminal.

The package is a modular monolith: each sub-package is one module of the
architecture (see ``terminal/docs/01-architecture.md``) and the allowed
imports between them are enforced by import-linter contracts in
``pyproject.toml``.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kterminal")
except PackageNotFoundError:  # pragma: no cover - running from an uninstalled source tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
