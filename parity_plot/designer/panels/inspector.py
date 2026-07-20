# parity_plot/designer/panels/inspector.py
"""The detail view for whichever point was clicked."""

from __future__ import annotations

from typing import Callable

from ...tolerance import Tolerance
from ..inspector_helpers import describe
from ..state import DesignerState


def build_inspector(
    state: DesignerState, tol_getter: Callable[[], Tolerance | None]
) -> Callable[[], None]:
    """Render the panel and return a function that refreshes it.

    The tolerance is fetched through a callable rather than passed by value,
    because the user can change it after this panel is built and the verdict
    must follow.
    """
    from nicegui import ui

    with ui.card().classes("w-full"):
        ui.label("Inspector").classes("text-base font-medium")
        body = ui.column().classes("w-full gap-1")

    def refresh() -> None:
        body.clear()
        with body:
            for label, value in describe(state.selected_record(tol_getter())):
                with ui.row().classes("w-full justify-between gap-4"):
                    if label:
                        ui.label(label).classes("opacity-70")
                    ui.label(value).classes("font-mono")

    refresh()
    return refresh