"""Version identity for strategies.

A strategy *version* is the immutable combination of everything that decides
which signals an instance emits: the definition's declared version, a SHA-256
of its source code, its effective parameters, instruments, timeframes and the
session windows it uses. Any change — even editing code without bumping the
declared version — yields a new ``config_hash`` and therefore a new version
row; signals and trades recorded under the old version keep pointing at it.
"""

import hashlib
from collections.abc import Iterable
from functools import cache
from pathlib import Path

import kterminal
from kterminal.core.canonical import canonical_json, hash_data, sha256_text

__all__ = [
    "canonical_json",
    "code_hash",
    "framework_fingerprint",
    "hash_data",
    "hash_files",
    "sha256_text",
    "source_files",
    "strategy_source_location",
]

_HASHED_SUFFIXES = (".py", ".pine", ".yaml", ".yml", ".json", ".txt")
_SKIP_DIRS = {"__pycache__", "tests", ".pytest_cache"}


def hash_files(paths: Iterable[Path], root: Path) -> str:
    """Hash file contents together with their paths relative to ``root`` (sorted)."""
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_files(location: Path) -> list[Path]:
    """Source files making up a strategy: a single module, or a whole package folder."""
    if location.is_file():
        return [location]
    return [
        path
        for path in location.rglob("*")
        if path.is_file()
        and path.suffix in _HASHED_SUFFIXES
        and not any(part in _SKIP_DIRS for part in path.relative_to(location).parts)
    ]


def code_hash(location: Path) -> str:
    root = location.parent if location.is_file() else location
    return hash_files(source_files(location), root)


def strategy_source_location(module_file: Path, strategies_root: Path | None = None) -> Path:
    """The unit of code that defines a strategy.

    A strategy in ``kterminal/strategies/<id>/strategy.py`` is identified by its
    whole folder (code, Pine reference source, params); a stand-alone module by
    its own file.
    """
    parent = module_file.parent
    is_package = (parent / "__init__.py").exists()
    if is_package and (strategies_root is None or parent.resolve() != strategies_root.resolve()):
        return parent
    return module_file


@cache
def framework_fingerprint() -> str:
    """Hash of the framework code that shapes signals (SDK, domain model, indicators).

    Recorded with every version for audit; it is not part of the version
    identity, so a framework refactor does not fork every strategy's history.
    """
    package_root = Path(kterminal.__file__).parent
    files: list[Path] = []
    for sub in ("strategy_engine", "domain", "indicators"):
        files.extend(source_files(package_root / sub))
    return f"{kterminal.__version__}:{hash_files(files, package_root)[:16]}"
