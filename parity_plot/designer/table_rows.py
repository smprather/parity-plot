# parity_plot/designer/table_rows.py
"""Turning records into table rows.

Values stay numeric rather than becoming formatted strings, because the table's
reason for existing is sorting by error magnitude and strings sort lexically --
"9" would land after "100". Rounding at build time keeps the display readable
without giving up numeric ordering.
"""

from __future__ import annotations

from typing import Any, Sequence

from .records import RecordView

# Quasar column definitions. Every column sorts; the point of the table is to
# put the worst offenders at the top on demand.
COLUMNS: list[dict[str, Any]] = [
    {"name": "key", "label": "Record", "field": "key", "required": True,
     "align": "left", "sortable": True},
    {"name": "x", "label": "Reference", "field": "x", "sortable": True},
    {"name": "y", "label": "Measured", "field": "y", "sortable": True},
    {"name": "error", "label": "Error", "field": "error", "sortable": True},
    {"name": "rel_error", "label": "Error %", "field": "rel_error", "sortable": True},
    {"name": "status", "label": "Status", "field": "status", "align": "left",
     "sortable": True},
    {"name": "verdict", "label": "Tolerance", "field": "verdict", "align": "left",
     "sortable": True},
]

_DIGITS = 6


def to_rows(views: Sequence[RecordView]) -> list[dict[str, Any]]:
    """One row per record, numbers kept as numbers."""
    return [
        {
            "key": view.key,
            "x": _round(view.x),
            "y": _round(view.y),
            "error": _round(view.error),
            "rel_error": _round(None if view.rel_error is None else view.rel_error * 100),
            "status": view.status,
            "verdict": view.verdict,
        }
        for view in views
    ]


def _round(value: float | None) -> float | None:
    """Readable in the cell, still numeric for sorting."""
    if value is None:
        return None
    return float(f"{value:.{_DIGITS}g}")