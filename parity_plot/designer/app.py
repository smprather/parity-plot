# parity_plot/designer/app.py
"""NiceGUI assembly.

This module owns layout and event wiring only. Anything worth a test belongs in
`state.py`, `session.py`, or `serialize.py`, which need no browser.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..config import ParityConfig
from ..data import ParityData
from .panels.controls import build_controls
from .panels.data_panel import build_data_panel
from .panels.encoding import build_encoding_panel
from .panels.inspector import build_inspector
from .panels.table import build_table
from .panels.tolerances import build_tolerances_panel
from .records import key_from_customdata
from .selection import range_from_selection
from .session import Session, StaleFileError
from .state import DesignerState


def select_record(state: DesignerState, key: str | None, *refreshers) -> None:
    """Pin a record and tell every panel to catch up.

    Both the plot and the table route through here rather than each setting
    `state.selection` themselves, so neither can end up showing a different
    record from the other.
    """
    state.selection = key
    for refresh in refreshers:
        if refresh is not None:
            refresh()


def apply_brush(state: DesignerState, args: dict | None, *refreshers) -> None:
    """Narrow the view to the brushed x-window, or clear it when empty.

    Only `x_range` is replaced; the other switches are carried across, so
    brushing does not silently undo a "failures only" filter the user set.
    """
    state.filters = replace(state.filters, x_range=range_from_selection(args))
    for refresh in refreshers:
        if refresh is not None:
            refresh()


def build_app(session: Session, config: ParityConfig, data: ParityData) -> DesignerState:
    """Register the designer page and return the state it drives."""
    from nicegui import ui

    state = DesignerState(config=config, data=data)

    @ui.page("/")
    def page() -> None:
        ui.dark_mode(True)

        with ui.header().classes("items-center justify-between"):
            ui.label("parity-plot designer").classes("text-lg font-medium")
            status = ui.label("").classes("text-sm opacity-70")

        with ui.row().classes("w-full no-wrap gap-4"):
            with ui.column().classes("w-80 shrink-0"):
                # Every panel is a peer top-level expansion -- Data, Tolerances,
                # then the Appearance/Statistics/Output groups. No "Settings"
                # wrapper, since the whole column is settings.
                build_data_panel(state, lambda: reload_everything())
                build_tolerances_panel(state, lambda: refresh())
                build_encoding_panel(state, lambda: refresh())
                build_controls(state, lambda: refresh())
                ui.separator()
                with ui.row():
                    ui.button("Save", on_click=lambda: save(None))
                    ui.button("Save As…", on_click=lambda: ask_where_to_save())

            with ui.column().classes("grow"):
                # Drag zooms, which is Plotly's default and what people expect.
                # Brushing is still available from the modebar's box-select and
                # lasso tools; the selection handlers below serve both.
                plot_view = ui.plotly(state.figure()).classes("w-full h-[55vh]")
                error_banner = ui.label("").classes("text-red-400 text-sm")
                refresh_inspector = build_inspector(state, state.tolerances)

                refresh_table = build_table(
                    state,
                    on_select=lambda key: select_record(state, key, refresh_inspector),
                    on_filter_change=lambda: refresh(),
                )

                def on_point_click(event) -> None:
                    points = (event.args or {}).get("points") or []
                    if not points:
                        return
                    key = key_from_customdata(points[0].get("customdata"))
                    select_record(state, key, refresh_inspector, refresh_table)

                plot_view.on("plotly_click", on_point_click)

                def on_brush(event) -> None:
                    apply_brush(state, event.args, refresh)

                plot_view.on("plotly_selected", on_brush)
                plot_view.on("plotly_deselect", lambda _: apply_brush(state, None, refresh))

        def refresh() -> None:
            plot_view.update_figure(state.figure())
            error_banner.text = state.last_error or ""
            status.text = "unsaved changes" if session.is_dirty(state.config) else "saved"
            refresh_inspector()
            refresh_table()

        def reload_everything() -> None:
            """After a dataset swap the whole view is stale, selection included."""
            refresh()

        def save(path: Path | None, force: bool = False) -> None:
            try:
                written = session.save(state.config, path, force=force)
            except StaleFileError as exc:
                confirm_overwrite(str(exc))
                return
            except (ValueError, OSError) as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.notify(f"Saved {written}", type="positive")
            refresh()

        def confirm_overwrite(message: str) -> None:
            with ui.dialog() as dialog, ui.card():
                ui.label(message)
                with ui.row():
                    ui.button("Cancel", on_click=dialog.close)
                    ui.button(
                        "Overwrite",
                        on_click=lambda: (dialog.close(), save(None, force=True)),
                    ).props("color=negative")
            dialog.open()

        def ask_where_to_save() -> None:
            with ui.dialog() as dialog, ui.card():
                ui.label("Save configuration as")
                target = ui.input("Path", value=str(session.config_path or "parity.toml"))
                with ui.row():
                    ui.button("Cancel", on_click=dialog.close)
                    ui.button(
                        "Save",
                        on_click=lambda: (dialog.close(), save(Path(target.value))),
                    )
            dialog.open()

        refresh()

    return state