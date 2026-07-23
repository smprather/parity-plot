# parity_plot/designer/app.py
"""NiceGUI assembly.

This module owns layout and event wiring only. Anything worth a test belongs in
`state.py`, `session.py`, `serialize.py`, or `validation.py`, which need no
browser.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..config import ConfigError, ParityConfig
from ..data import DataError, ParityData
from .panels.controls import build_controls
from .panels.data_panel import build_data_panel
from .panels.encoding import build_encoding_panel
from .panels.inspector import build_inspector
from .panels.table import build_table
from .panels.tolerances import build_tolerances_panel
from .records import key_from_customdata
from .selection import range_from_selection
from .session import Session, config_choices
from .state import DesignerState
from .validation import problems as config_problems

# The dropdown entry standing in for a working config not yet bound to a file
# (a New Design, or a data-only launch). Save As binds it to a name.
UNSAVED = "‹unsaved›"


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


def build_app(session: Session, config: ParityConfig, data: ParityData | None) -> DesignerState:
    """Register the designer page and return the state it drives."""
    from nicegui import ui

    state = DesignerState(config=config, data=data)
    # The session is swapped when the toolbar opens a config or starts a New
    # Design, so it lives in a one-element dict the handlers can rebind.
    sess = {"session": session}
    # The directory the config picker scans -- where `parity-plot design` ran.
    launch_dir = Path.cwd()

    @ui.page("/")
    def page() -> None:
        ui.dark_mode(True)

        def current_choice() -> str:
            s = sess["session"]
            return s.config_path.name if s.config_path is not None else UNSAVED

        def choice_options() -> list[str]:
            names = [p.name for p in config_choices(launch_dir)]
            # The unbound sentinel is offered only while unbound.
            return ([UNSAVED] if sess["session"].config_path is None else []) + names

        # The data panel returns a hook that marks its join field; held here so
        # refresh() can call it after each change. Rebuilt with the column.
        marks = {"join": lambda problems: None}

        # settings_column is defined before the layout that calls it; its panels'
        # on_change callbacks reference refresh/reload_everything, which are
        # defined further down and only fire on later user interaction.
        @ui.refreshable
        def settings_column() -> None:
            marks["join"] = build_data_panel(state, lambda: reload_everything())
            build_tolerances_panel(state, lambda: refresh())
            build_encoding_panel(state, lambda: refresh())
            build_controls(state, lambda: refresh())

        with ui.header().classes("items-center justify-between"):
            ui.label("parity-plot designer").classes("text-lg font-medium")
            with ui.row().classes("items-center gap-2"):
                config_pick = ui.select(
                    choice_options(), value=current_choice(), label="Config",
                    on_change=lambda e: open_named(e.value),
                ).classes("w-56")
                save_as_btn = ui.button("Save As…", on_click=lambda: ask_where_to_save())
                ui.button("New Design", on_click=lambda: new_design())

        with ui.row().classes("w-full no-wrap gap-4"):
            with ui.column().classes("w-80 shrink-0"):
                settings_column()

            with ui.column().classes("grow"):
                plot_view = ui.plotly(state.figure()).classes("w-full h-[55vh]")
                # A persistent, colour-coded status bar -- no toasts. Errors (a
                # validation problem, a bad column) stay here until the next
                # action clears them, rather than popping and vanishing.
                status_bar = ui.label("Ready").classes(
                    "w-full text-sm px-2 py-1 rounded opacity-70"
                )
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

        def set_status(message: str, kind: str = "info") -> None:
            """Write the persistent status bar. kind: error | ok | info."""
            colour = {
                "error": "bg-red-900 text-red-100",
                "ok": "bg-green-900 text-green-100",
                "info": "opacity-70",
            }[kind]
            status_bar.classes(replace="w-full text-sm px-2 py-1 rounded " + colour)
            status_bar.text = message

        def refresh() -> None:
            plot_view.update_figure(state.figure())

            probs = config_problems(state.config)
            blocking = state.last_error or (probs[0].message if probs else None)

            if blocking:
                set_status(f"⛔  {blocking}", "error")
            else:
                set_status("Ready", "info")

            marks["join"](probs)
            save_as_btn.set_enabled(not blocking)

            # Auto-save: only a clean, bound config is written; autosave no-ops
            # when unbound. The bound file thus always holds the last valid
            # config -- a broken edit is withheld until it is fixed.
            if not blocking:
                sess["session"].autosave(state.config)

            refresh_inspector()
            refresh_table()

        def reload_everything() -> None:
            """After a dataset swap the whole view is stale, selection included."""
            refresh()

        def _sync_picker() -> None:
            config_pick.options = choice_options()
            config_pick.value = current_choice()
            config_pick.update()

        def _has_unsaved_unbound_edits() -> bool:
            s = sess["session"]
            return s.config_path is None and s.is_dirty(state.config)

        def _swap(new_session: Session, cfg: ParityConfig, new_data) -> None:
            sess["session"] = new_session
            state.load_session_config(cfg, new_data)
            settings_column.refresh()
            _sync_picker()
            refresh()

        def open_named(name: str) -> None:
            if name == UNSAVED or name == current_choice():
                return

            def do_open() -> None:
                try:
                    new_session, cfg, new_data = Session.start((), launch_dir / name)
                except (ConfigError, DataError, ValueError, OSError) as exc:
                    set_status(f"⛔  {exc}", "error")
                    _sync_picker()  # revert the selection to the still-open config
                    return
                _swap(new_session, cfg, new_data)

            if _has_unsaved_unbound_edits():
                confirm_discard(do_open, on_cancel=_sync_picker)
            else:
                do_open()

        def new_design() -> None:
            def do_new() -> None:
                new_session, cfg, new_data = Session.start((), None)
                _swap(new_session, cfg, new_data)

            if _has_unsaved_unbound_edits():
                confirm_discard(do_new)
            else:
                do_new()

        def confirm_discard(proceed, on_cancel=None) -> None:
            with ui.dialog() as dialog, ui.card():
                ui.label("Discard unsaved changes?")
                with ui.row():
                    ui.button(
                        "Cancel",
                        on_click=lambda: (dialog.close(), on_cancel() if on_cancel else None),
                    )
                    ui.button(
                        "Discard",
                        on_click=lambda: (dialog.close(), proceed()),
                    ).props("color=negative")
            dialog.open()

        def save_as(path: Path) -> None:
            try:
                written = sess["session"].save(state.config, path)
            except (ValueError, OSError) as exc:
                set_status(f"⛔  {exc}", "error")
                return
            # The one place a toast survives: a save is a discrete action whose
            # confirmation is transient good news; the status bar reverts to the
            # live state on the next refresh.
            ui.notify(f"Saved {written}", type="positive")
            set_status(f"✅  Saved {written}", "ok")
            _sync_picker()
            refresh()

        def ask_where_to_save() -> None:
            with ui.dialog() as dialog, ui.card():
                ui.label("Save configuration as")
                target = ui.input("Path", value=str(sess["session"].config_path or "parity.toml"))
                with ui.row():
                    ui.button("Cancel", on_click=dialog.close)
                    ui.button(
                        "Save",
                        on_click=lambda: (dialog.close(), save_as(Path(target.value))),
                    )
            dialog.open()

        refresh()

    return state
