# parity_plot/designer/panels/table.py
"""The record table and the filter switches that narrow it.

Paged on the server. The table used to hold every record client-side, so each
refresh built, serialized and shipped every row -- on the event loop, for a
widget that shows fifteen -- and NiceGUI walks every row again on each send.
Now the rows arrive already built (off the loop, in :mod:`..view`), only the
visible page goes to the browser, and a header click sorts in a worker thread.
"""

from __future__ import annotations

from typing import Any, Callable

from ..filters import FilterSet
from ..io import offload
from ..state import DesignerState
from ..table_rows import (
    COLUMNS,
    UNSORTED,
    TableSort,
    last_page,
    page_of,
    sort_rows,
)
from ..view import View

# Rows per page on offer. No "All": that is the full-dataset payload paging
# exists to avoid.
PAGE_SIZES = (15, 50, 100)


def summary_text(showing: int, total: int) -> str:
    """How much of the data is on screen.

    Always states both numbers when anything is hidden: a filtered view that
    looks unfiltered invites the wrong conclusion about the data.
    """
    if showing == total:
        return f"{total:,} records"
    return f"showing {showing:,} of {total:,}"


class TablePanel:
    """The table's rows, sort and page, kept here and shown one page at a time."""

    def __init__(self, state: DesignerState, table: Any, summary: Any) -> None:
        self._state = state
        self._table = table
        self._summary = summary
        self._rows: list[dict[str, Any]] = []
        self._rows_sort: TableSort = UNSORTED
        self._by_key: dict[str, dict[str, Any]] = {}
        # Bumped whenever a new row set arrives, so a sort that finishes after
        # it cannot put the old rows back.
        self._generation = 0
        self._pagination: dict[str, Any] = {
            "sortBy": None,
            "descending": False,
            "page": 1,
            "rowsPerPage": PAGE_SIZES[0],
        }

    @property
    def sort(self) -> TableSort:
        """The order the user last asked for; a refresh builds rows in it."""
        return (
            self._pagination.get("sortBy") or None,
            bool(self._pagination.get("descending")),
        )

    @property
    def rows(self) -> list[dict[str, Any]]:
        """Every visible row, in :attr:`sort` order once any re-sort lands."""
        return self._rows

    async def show(self, view: View, sort: TableSort) -> None:
        """Take a refresh's rows (built in ``sort`` order) and paint a page."""
        self._rows, self._rows_sort, self._by_key = view.rows, sort, view.rows_by_key
        self._generation += 1
        self._summary.text = summary_text(view.showing, view.total)
        # A header click can land while the view was computing: the rows are
        # in the order the snapshot saw, not the one now asked for.
        await self._ensure_sorted()
        self._paint()

    async def request(self, pagination: dict[str, Any]) -> None:
        """Quasar's server-side ``request``: a page, page size or sort change."""
        for key in ("sortBy", "descending", "page", "rowsPerPage"):
            if key in pagination:
                self._pagination[key] = pagination[key]
        await self._ensure_sorted()
        self._paint()

    def show_selection(self) -> None:
        """Highlight the pinned record, wherever it came from (plot or table)."""
        self._table.selected = self._selected_rows()
        self._table.update()

    async def _ensure_sorted(self) -> None:
        while self._rows_sort != self.sort:
            want, rows, generation = self.sort, self._rows, self._generation
            self._table.props("loading")
            try:
                ordered = await offload(sort_rows, rows, *want)
            finally:
                self._table.props(remove="loading")
            if generation == self._generation:
                self._rows, self._rows_sort = ordered, want
            # else: newer rows arrived meanwhile, with their own order; the
            # loop re-checks them against the sort now wanted.

    def _selected_rows(self) -> list[dict[str, Any]]:
        key = self._state.selection
        row = self._by_key.get(key) if key is not None else None
        return [row] if row is not None else []

    def _paint(self) -> None:
        per_page = int(self._pagination.get("rowsPerPage") or 0)
        page = min(
            max(int(self._pagination.get("page") or 1), 1),
            last_page(len(self._rows), per_page),
        )
        self._pagination["page"] = page
        self._table.rows = page_of(self._rows, page, per_page)
        # rowsNumber is what puts Quasar in server-side mode: it pages and
        # sorts by asking (the ``request`` event), not by itself.
        self._table.pagination = {**self._pagination, "rowsNumber": len(self._rows)}
        self._table.selected = self._selected_rows()
        self._table.update()


def build_table(
    state: DesignerState,
    on_select: Callable[[str | None], None],
    on_filter_change: Callable[[], Any],
) -> TablePanel:
    """Render the filters and the table. Returns the panel the refresh feeds."""
    from nicegui import ui

    with ui.column().classes("w-full gap-2"):
        with ui.row().classes("items-center gap-4"):
            failures = ui.switch("Failures only")
            unpaired = ui.switch("Include unpaired", value=True)
            summary = ui.label("").classes("text-sm opacity-70")

        table = (
            ui.table(
                columns=COLUMNS,
                rows=[],
                row_key="key",
                selection="single",
                # Complete from the start: Quasar normalizes a partial
                # pagination on mount and reports it back, and NiceGUI stores
                # the report -- a stale rowsNumber over the real one.
                pagination={
                    "sortBy": None,
                    "descending": False,
                    "page": 1,
                    "rowsPerPage": PAGE_SIZES[0],
                    "rowsNumber": 0,
                },
            )
            .classes("w-full")
            .props(f':rows-per-page-options="{list(PAGE_SIZES)}"')
        )

    panel = TablePanel(state, table, summary)

    def apply_filters() -> None:
        state.filters = FilterSet(
            outside_tolerance_only=bool(failures.value),
            show_unpaired=bool(unpaired.value),
            show_paired=state.filters.show_paired,
            x_range=state.filters.x_range,
        )
        on_filter_change()

    failures.on_value_change(lambda _: apply_filters())
    unpaired.on_value_change(lambda _: apply_filters())

    def handle_selection(event) -> None:
        rows = event.selection or []
        on_select(rows[0]["key"] if rows else None)

    table.on_select(handle_selection)
    table.on(
        "request",
        lambda e: panel.request((e.args or {}).get("pagination") or {}),
        ["pagination"],
    )
    # Should the client report a pagination of its own anyway, NiceGUI has
    # already stored it; take its page/sort as a request, which repaints with
    # the server's row count.
    table.on_pagination_change(lambda e: panel.request(e.value or {}))
    return panel
