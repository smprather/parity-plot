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
from ..tolerances import NamedTolerance, failures, pass_fail, verdict_text

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
    # Names of every pass/fail tolerance this record breaks, in declared order.
    # None when the record was never judged -- unpaired, or no pass/fail
    # criteria exist. An empty tuple means judged and passed. The two are
    # different facts and the table shows them differently (blank vs "pass").
    failed: tuple[str, ...] | None = None

    @property
    def verdict(self) -> str:
        """How the verdict reads in the table and the inspector.

        Blank when the record was never judged; otherwise the failing tolerance
        names joined by ", ", or "pass" when there are none.
        """
        if self.failed is None:
            return ""
        return verdict_text(self.failed)


def record_views(
    data: ParityData,
    tolerances: Sequence[NamedTolerance] = (),
) -> list[RecordView]:
    """Every record: paired first, then those missing y, then missing x."""
    views: list[RecordView] = []
    criteria = pass_fail(tolerances)

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
                # None when there is nothing to judge against; an empty tuple
                # would read as "judged and passed", which is a different fact.
                failed=failures(tolerances, x, y) if criteria else None,
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

    The paired trace carries ``(key, diff, verdict)`` while the rug traces carry
    a bare key, so a click handler sees both shapes and must not assume either.
    """
    if customdata is None:
        return None
    if isinstance(customdata, str):
        return customdata
    if isinstance(customdata, (list, tuple)):
        return str(customdata[0]) if customdata else None
    return str(customdata)