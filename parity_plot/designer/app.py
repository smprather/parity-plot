# parity_plot/designer/app.py
"""NiceGUI assembly.

This module owns layout and event wiring only. Anything worth a test belongs in
`state.py`, `session.py`, or `serialize.py`, which need no browser.
"""

from __future__ import annotations

from pathlib import Path

from ..config import ParityConfig
from ..data import ParityData
from .panels.controls import build_controls
from .session import Session, StaleFileError
from .state import DesignerState


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
                ui.label("Settings").classes("text-base font-medium")
                build_controls(state, lambda: refresh())
                ui.separator()
                with ui.row():
                    ui.button("Save", on_click=lambda: save(None))
                    ui.button("Save As…", on_click=lambda: ask_where_to_save())

            with ui.column().classes("grow"):
                plot_view = ui.plotly(state.figure()).classes("w-full h-[80vh]")
                error_banner = ui.label("").classes("text-red-400 text-sm")

        def refresh() -> None:
            plot_view.update_figure(state.figure())
            error_banner.text = state.last_error or ""
            status.text = "unsaved changes" if session.is_dirty(state.config) else "saved"

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