# parity_plot/designer/records.py
"""A flat, per-record view of a dataset.

The plot shows records as marks; this is the same records as rows. The inspector
uses one of these, and Phase 3's table uses all of them, so nothing here is
inspector-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..data import ParityData
from ..tolerance import Tolerance

PAIRED = "paired"
MISSING_X = "missing x"
MISSING_Y = "missing y"


@dataclass(frozen=True)
class RecordView:
    key: str
    x: float | None
    y: float | None
    error: float | None       # y - x, undefined unless both are present
    rel_error: float | None   # error / x, undefined at x = 0
    status: str
    within: bool | None       # None when unpaired or no tolerance was given


def record_views(data: ParityData, tol: Tolerance | None = None) -> list[RecordView]:
    """Every record: paired first, then those missing y, then missing x."""
    views: list[RecordView] = []

    for key, x, y in zip(data.keys, data.x, data.y):
        error = y - x
        views.append(
            RecordView(
                key=key,
                x=x,
                y=y,
                error=error,
                rel_error=(error / x) if x else None,
                status=PAIRED,
                within=tol.contains(x, y) if tol else None,
            )
        )

    for key, value in zip(data.missing_y.keys, data.missing_y.values):
        views.append(RecordView(key, value, None, None, None, MISSING_Y, None))

    for key, value in zip(data.missing_x.keys, data.missing_x.values):
        views.append(RecordView(key, None, value, None, None, MISSING_X, None))

    return views


def find_record(views: Sequence[RecordView], key: str) -> RecordView | None:
    return next((v for v in views if v.key == key), None)


def key_from_customdata(customdata: Any) -> str | None:
    """Pull a record key out of a Plotly click payload.

    The paired trace carries ``(key, diff)`` while the rug traces carry a bare
    key, so a click handler sees both shapes and must not assume either.
    """
    if customdata is None:
        return None
    if isinstance(customdata, str):
        return customdata
    if isinstance(customdata, (list, tuple)):
        return str(customdata[0]) if customdata else None
    return str(customdata)