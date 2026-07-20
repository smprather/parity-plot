# parity_plot/designer/selection.py
"""Reading an x-window out of a Plotly selection event.

Plotly describes a selection three different ways depending on how it was made
-- a dragged rectangle, a lasso outline, or just the points that fell inside --
so this normalises all three into one range. Kept pure so it can be tested
without a browser.
"""

from __future__ import annotations

from typing import Any


def range_from_selection(args: dict[str, Any] | None) -> tuple[float, float] | None:
    """The x-range a selection covers, or None if it covers nothing.

    Returning None for an empty selection is what lets a cleared brush clear
    the filter rather than leaving the previous window stuck in place.
    """
    if not args:
        return None

    # A dragged box is the user's stated intent, even if no points fell inside.
    box = _numbers((args.get("range") or {}).get("x"))
    if box:
        return min(box), max(box)

    lasso = _numbers((args.get("lassoPoints") or {}).get("x"))
    if lasso:
        return min(lasso), max(lasso)

    points = _numbers(p.get("x") for p in (args.get("points") or []))
    if points:
        return min(points), max(points)

    return None


def _numbers(values: Any) -> list[float]:
    """Every value that is genuinely a number, booleans excluded."""
    if values is None:
        return []
    found = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        found.append(float(value))
    return found