"""Argument checks shared by the indicator classes."""


def check_int(name: str, value: int, minimum: int) -> int:
    """Return ``value`` if it is an ``int`` (not ``bool``) of at least ``minimum``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def check_float(name: str, value: float) -> float:
    """Return ``value`` as a finite float."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number, got {value!r}")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return result
