# parity_plot/designer/panels/table.py
"""The record table and the filter switches that narrow it."""

from __future__ import annotations

from typing import Callable

from ..filters import FilterSet
from ..state import DesignerState
from ..table_rows import COLUMNS, to_rows


def summary_text(showing: int, total: int) -> str:
    """How much of the data is on screen.

    Always states both numbers when anything is hidden: a filtered view that
    looks unfiltered invites the wrong conclusion about the data.
    """
    if showing == total:
        return f"{total:,} records"
    return f"showing {showing:,} of {total:,}"


def build_table(
    state: DesignerState,
    on_select: Callable[[str | None], None],
    on_filter_change: Callable[[], None],
) -> Callable[[], None]:
    """Render the filters and the table. Returns a function that refreshes them."""
    from nicegui import ui

    with ui.column().classes("w-full gap-2"):
        with ui.row().classes("items-center gap-4"):
            failures = ui.switch("Failures only")
            unpaired = ui.switch("Include unpaired", value=True)
            summary = ui.label("").classes("text-sm opacity-70")

        table = ui.table(
            columns=COLUMNS,
            rows=[],
            row_key="key",
            selection="single",
            pagination=15,
        ).classes("w-full")

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

    def refresh() -> None:
        table.rows = to_rows(state.visible_records())
        showing, total = state.counts()
        summary.text = summary_text(showing, total)
        # Keep the table's highlight in step with the pinned record, so a click
        # on the plot lands here too.
        table.selected = [r for r in table.rows if r["key"] == state.selection]
        table.update()

    refresh()
    return refresh