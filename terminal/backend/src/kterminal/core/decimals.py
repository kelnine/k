"""A private decimal context for money arithmetic.

Python's decimal context is per thread and mutable: any code on the thread —
a strategy running in-process, a library — can change precision, rounding or
traps. Money code therefore never relies on the ambient context; it runs in
:data:`EXACT_CONTEXT` via :func:`exact`.
"""

import functools
from collections.abc import Callable
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

EXACT_CONTEXT = Context(
    prec=60, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow]
)


def exact[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """Run ``function`` in :data:`EXACT_CONTEXT`, whatever the caller's context is."""

    @functools.wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with localcontext(EXACT_CONTEXT):
            return function(*args, **kwargs)

    return wrapper


__all__ = ["EXACT_CONTEXT", "exact"]
