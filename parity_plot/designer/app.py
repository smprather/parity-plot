# parity_plot/designer/app.py
"""NiceGUI assembly.

This module owns layout and event wiring only. Anything worth a test belongs in
`state.py`, `session.py`, `serialize.py`, or `validation.py`, which need no
browser.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from plotly.graph_objects import Figure

from ..config import ConfigError, ParityConfig
from ..data import DataError, ParityData
from .panels.controls import build_controls
from .panels.data_panel import build_data_panel
from .panels.encoding import build_encoding_panel
from .panels.histogram import build_histogram_panel
from .panels.inspector import build_inspector
from .panels.polynomial_lines import build_polynomial_lines_panel
from .panels.table import build_table
from .panels.tolerances import build_tolerances_panel
from .records import key_from_customdata
from .selection import range_from_selection
from .session import Session, config_choice_names
from .state import DesignerState
from .validation import problems as config_problems

# The dropdown entry standing in for a working config not yet bound to a file
# (a New Design, or a data-only launch). Save As binds it to a name.
UNSAVED = "‹unsaved›"

PAGE_CONTENT_CLASSES = "absolute inset-0 overflow-hidden"
WORKSPACE_CLASSES = (
    "designer-workspace w-full h-full min-h-0 no-wrap gap-4 "
    "items-stretch overflow-hidden"
)
SETTINGS_COLUMN_CLASSES = (
    "designer-settings w-80 shrink-0 h-full min-h-0 overflow-y-auto "
    "overscroll-contain pr-2 pb-6"
)
RESULTS_COLUMN_CLASSES = (
    "designer-results grow h-full min-h-0 overflow-y-auto overscroll-contain pb-6"
)
PLOT_CLASSES = "designer-plot aspect-square h-[70vh] mx-auto"
RESPONSIVE_LAYOUT_CSS = """
.designer-plot {
  width: min(70vh, 100%) !important;
  height: min(70vh, 100%) !important;
  flex: none;
}
@media (max-width: 767px) {
  .designer-workspace {
    flex-direction: column;
  }
  .designer-settings,
  .designer-results {
    width: 100%;
    min-width: 0;
  }
  .designer-settings {
    order: 2;
    height: calc(33.3333% - 0.5rem);
    flex: 0 0 calc(33.3333% - 0.5rem);
  }
  .designer-results {
    order: 1;
    height: calc(66.6667% - 0.5rem);
    flex: 0 0 calc(66.6667% - 0.5rem);
  }
  .designer-plot {
    width: auto !important;
    max-width: 100%;
    height: 100% !important;
    flex: none;
  }
}
"""
RESPONSIVE_PLOT_SCRIPT = """
<script>
(() => {
  const baseCompactMargin = {l: 55, r: 20, t: 75, b: 115};
  const clone = value => JSON.parse(JSON.stringify(value || {}));
  const statsIndex = plot =>
    (plot.layout.annotations || []).findIndex(annotation =>
      annotation.font && annotation.font.family === 'monospace'
    );
  const compactMarginFor = plot => ({
    ...baseCompactMargin,
    t: statsIndex(plot) >= 0 ? plot.layout.margin.t : baseCompactMargin.t,
  });
  const isCompact = (plot, compactMargin) => {
    const margin = plot.layout && plot.layout.margin;
    return margin && Object.entries(compactMargin)
      .every(([key, value]) => margin[key] === value);
  };
  const sync = plot => {
    if (!window.Plotly || !plot.layout) return;
    const narrow = window.matchMedia('(max-width: 767px)').matches;
    const annotationIndex = statsIndex(plot);
    const compactMargin = compactMarginFor(plot);
    if (narrow && !isCompact(plot, compactMargin)) {
      plot.__designerDesktopLayout = {
        margin: clone(plot.layout.margin),
        legend: clone(plot.layout.legend),
        titleX: plot.layout.title && plot.layout.title.x,
        statsXshift: annotationIndex >= 0
          ? plot.layout.annotations[annotationIndex].xshift
          : undefined,
        modebarOrientation:
          plot.layout.modebar && plot.layout.modebar.orientation,
      };
      const legend = {
        ...clone(plot.layout.legend),
        orientation: 'h',
        x: 0.5,
        xanchor: 'center',
        y: annotationIndex >= 0 ? -0.55 : -0.28,
        yanchor: 'top',
        font: {...clone(plot.layout.legend && plot.layout.legend.font), size: 10},
      };
      const update = {
        margin: compactMargin,
        legend,
        'modebar.orientation': 'v',
      };
      if (annotationIndex >= 0) update['title.x'] = 0.75;
      if (annotationIndex >= 0) {
        update[`annotations[${annotationIndex}].xshift`] = -55;
      }
      window.Plotly.relayout(plot, update);
    } else if (!narrow && isCompact(plot, compactMargin) && plot.__designerDesktopLayout) {
      const desktop = plot.__designerDesktopLayout;
      delete plot.__designerDesktopLayout;
      const update = {margin: desktop.margin, legend: desktop.legend};
      if (desktop.titleX !== undefined) update['title.x'] = desktop.titleX;
      if (desktop.statsXshift !== undefined && annotationIndex >= 0) {
        update[`annotations[${annotationIndex}].xshift`] = desktop.statsXshift;
      }
      update['modebar.orientation'] = desktop.modebarOrientation || 'h';
      window.Plotly.relayout(plot, update);
    }
  };
  const scan = () => document.querySelectorAll('.designer-plot').forEach(plot => {
    if (!plot.__designerResponsiveBound && typeof plot.on === 'function') {
      plot.__designerResponsiveBound = true;
      plot.on('plotly_afterplot', () => requestAnimationFrame(() => sync(plot)));
    }
    sync(plot);
  });
  new MutationObserver(scan).observe(document.body, {childList: true, subtree: true});
  window.addEventListener('resize', scan);
  scan();
})();
</script>
"""


def axis_range_relayout(figure: Figure) -> dict[str, list[float]]:
    """Exact requested ranges to reapply after NiceGUI calls Plotly.react."""
    return {
        "xaxis.range": list(figure.layout.xaxis.range),
        "yaxis.range": list(figure.layout.yaxis.range),
    }


def axis_range_relayout_script(plot_id: int, figure: Figure) -> str:
    """Build a bounded client retry for plots not mounted during early events."""
    ranges = json.dumps(axis_range_relayout(figure), allow_nan=False)
    return f"""
(() => {{
  const apply = attempt => {{
    const plot = document.getElementById('c{plot_id}');
    if (window.Plotly && plot && plot.layout) {{
      window.Plotly.relayout(plot, {ranges});
    }} else if (attempt < 40) {{
      window.setTimeout(() => apply(attempt + 1), 25);
    }}
  }};
  apply(0);
}})();
"""


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


def build_app(
    session: Session, config: ParityConfig, data: ParityData | None
) -> DesignerState:
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
        ui.add_css(RESPONSIVE_LAYOUT_CSS)
        ui.add_body_html(RESPONSIVE_PLOT_SCRIPT)
        ui.query(".nicegui-content").classes(PAGE_CONTENT_CLASSES)

        def current_choice() -> str:
            s = sess["session"]
            return s.config_path.name if s.config_path is not None else UNSAVED

        def choice_options() -> list[str]:
            s = sess["session"]
            names = config_choice_names(launch_dir, s.config_path)
            # The unbound sentinel is offered only while unbound.
            return ([UNSAVED] if s.config_path is None else []) + names

        # The data panel returns a hook that marks its join field; held here so
        # refresh() can call it after each change. Rebuilt with the column.
        marks: dict[str, Callable[[list], None]] = {"join": lambda problems: None}

        # settings_column is defined before the layout that calls it; its panels'
        # on_change callbacks reference refresh/reload_everything, which are
        # defined further down and only fire on later user interaction.
        @ui.refreshable
        def settings_column() -> None:
            marks["join"] = build_data_panel(state, lambda: reload_everything())
            build_tolerances_panel(state, lambda: refresh())
            build_polynomial_lines_panel(state, lambda: refresh())
            build_histogram_panel(state, lambda: refresh())
            build_encoding_panel(state, lambda: refresh())
            build_controls(state, lambda: refresh())

        with ui.header().classes("items-center justify-between"):
            ui.label("parity-plot designer").classes("text-lg font-medium")
            with ui.row().classes("items-center gap-2"):
                config_pick = ui.select(
                    choice_options(),
                    value=current_choice(),
                    label="Config",
                    on_change=lambda e: open_named(e.value),
                ).classes("w-56")
                save_as_btn = ui.button(
                    "Save As…", on_click=lambda: ask_where_to_save()
                )
                ui.button("New Design", on_click=lambda: new_design())

        with ui.row().classes(WORKSPACE_CLASSES):
            with ui.column().classes(SETTINGS_COLUMN_CLASSES):
                settings_column()

            with ui.column().classes(RESULTS_COLUMN_CLASSES):
                # A parity plot is square; render the preview square and centred
                # rather than stretched across a wide column, so the legend hugs
                # the plot and the (paper-centred) title lines up with it.
                plot_view = ui.plotly(state.figure()).classes(PLOT_CLASSES)
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
                plot_view.on(
                    "plotly_deselect", lambda _: apply_brush(state, None, refresh)
                )

        def set_status(message: str, kind: str = "info") -> None:
            """Write the persistent status bar. kind: error | warn | ok | info."""
            colour = {
                "error": "bg-red-900 text-red-100",
                "warn": "bg-amber-900 text-amber-100",
                "ok": "bg-green-900 text-green-100",
                "info": "opacity-70",
            }[kind]
            status_bar.classes(replace="w-full text-sm px-2 py-1 rounded " + colour)
            status_bar.text = message

        def refresh() -> None:
            figure = state.figure()
            plot_view.update_figure(figure)
            # Plotly.react can retain the previous constrained ranges even
            # though the new figure contains explicit ones. Reapply them after
            # react so viewport-origin edits take effect immediately.
            ui.run_javascript(axis_range_relayout_script(plot_view.id, figure))

            probs = config_problems(state.config)
            errors = [p for p in probs if p.severity == "error"]
            warnings = [p for p in probs if p.severity == "warning"]
            # Only an error (or a load/build failure) blocks; a warning is
            # advisory -- shown amber, but it neither disables Save As nor
            # withholds the auto-save.
            blocking = state.last_error or (errors[0].message if errors else None)

            if blocking:
                set_status(f"⛔  {blocking}", "error")
            elif warnings:
                set_status(f"⚠️  {warnings[0].message}", "warn")
            else:
                set_status("Ready", "info")

            marks["join"](errors)  # only errors redden a field
            save_as_btn.set_enabled(not blocking)

            # Auto-save: only a clean (no error), bound config is written; autosave
            # no-ops when unbound. The bound file thus always holds the last valid
            # config -- a broken edit is withheld until it is fixed. A warning does
            # not withhold the write.
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
                        on_click=lambda: (
                            dialog.close(),
                            on_cancel() if on_cancel else None,
                        ),
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
                target = ui.input(
                    "Path", value=str(sess["session"].config_path or "parity.toml")
                )
                with ui.row():
                    ui.button("Cancel", on_click=dialog.close)
                    ui.button(
                        "Save",
                        on_click=lambda: (dialog.close(), save_as(Path(target.value))),
                    )
            dialog.open()

        refresh()

    return state
