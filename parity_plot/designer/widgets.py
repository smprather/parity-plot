"""Small helpers for reading designer widgets defensively.

Browser-free and dependency-free, so the panels that use these stay testable
without a page.

The rule these encode: a number the *user* typed is untrusted until parsed, and
a failure to parse is a normal intermediate state, not an exception. A
``ui.number`` field is briefly empty, ``-``, or ``1e`` on the way to a real
value, and the panel reading it must not blow up in the middle of an edit.
"""

from __future__ import annotations

import math
from typing import Any


def as_float(value: Any, default: float | None = None) -> float | None:
    """``value`` as a finite float, or ``default`` when it is not one.

    Rejects booleans explicitly: ``isinstance(True, int)`` is True in Python,
    so a switch's value would otherwise silently read as 1.0. Rejects NaN and
    infinity, because plot data is required to be finite and a field is the
    other way that rule gets violated.
    """
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except TypeError, ValueError:
        return default
    if not math.isfinite(number):
        return default
    return number


def as_int(value: Any, default: int | None = None) -> int | None:
    """``value`` as an int, or ``default`` when it is not one.

    A float from a number field is truncated toward zero, which is what
    ``math.trunc`` states outright; ``as_float`` has already rejected NaN and
    infinity, so this cannot fail either.
    """
    number = as_float(value)
    if number is None:
        return default
    return math.trunc(number)
