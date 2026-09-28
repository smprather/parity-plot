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
    {
        "name": "key",
        "label": "Record",
        "field": "key",
        "required": True,
        "align": "left",
        "sortable": True,
    },
    {"name": "x", "label": "Reference", "field": "x", "sortable": True},
    {"name": "y", "label": "Test", "field": "y", "sortable": True},
    {"name": "error", "label": "Error", "field": "error", "sortable": True},
    {"name": "rel_error", "label": "Error %", "field": "rel_error", "sortable": True},
    {
        "name": "status",
        "label": "Status",
        "field": "status",
        "align": "left",
        "sortable": True,
    },
    {
        "name": "verdict",
        "label": "Tolerance",
        "field": "verdict",
        "align": "left",
        "sortable": True,
    },
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
            "rel_error": _round(
                None if view.rel_error is None else view.rel_error * 100
            ),
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


# How a table is ordered: the column name it sorts by (None for record order)
# and whether descending. Quasar's own pagination object carries the same pair.
TableSort = tuple[str | None, bool]
UNSORTED: TableSort = (None, False)


def sort_rows(
    rows: Sequence[dict[str, Any]], sort_by: str | None, descending: bool
) -> list[dict[str, Any]]:
    """``rows`` ordered by one column, the way the table's header click asks.

    The table is paged server-side -- shipping every row to the browser on every
    refresh was most of a refresh's cost on a large file -- so sorting happens
    here, not in Quasar. Empty cells always sort last, whichever direction: the
    column exists to bring the largest errors to the top, and an unpaired record
    has no error to rank. Stable, so ties keep record order.
    """
    if not sort_by:
        return list(rows)
    present = [row for row in rows if row.get(sort_by) is not None]
    empty = [row for row in rows if row.get(sort_by) is None]
    present.sort(key=lambda row: row[sort_by], reverse=descending)
    return present + empty


def page_of(
    rows: Sequence[dict[str, Any]], page: int, per_page: int
) -> list[dict[str, Any]]:
    """One page of ``rows``, 1-based as Quasar numbers them.

    ``per_page`` 0 is Quasar's "all rows"; a page past the end is empty.
    """
    if per_page <= 0:
        return list(rows)
    start = (max(page, 1) - 1) * per_page
    return list(rows[start : start + per_page])


def last_page(total: int, per_page: int) -> int:
    """The highest valid 1-based page for ``total`` rows (1 when empty)."""
    if per_page <= 0 or total <= 0:
        return 1
    return (total + per_page - 1) // per_page
