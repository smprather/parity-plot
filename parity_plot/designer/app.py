# parity_plot/designer/app.py
"""NiceGUI assembly.

This module owns layout and event wiring only. Anything worth a test belongs in
`state.py`, `session.py`, `serialize.py`, or `validation.py`, which need no
browser.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Coroutine
from dataclasses import replace
from pathlib import Path
from typing import Any

from plotly.graph_objects import Figure

from ..config import ConfigError, ParityConfig
from ..data import DataError, ParityData
from .io import debug_log, offload, sync_refresher
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
from .session import Debouncer, Session, config_choice_names
from .state import DesignerState, Generation
from .validation import problems as config_problems
from .widgets import as_float

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
PEEK_GRID_CSS = ".peek-grid .ag-header-cell-text { font-size: 15px; font-weight: 700; }"
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
    """Exact requested ranges to reapply after NiceGUI calls Plotly.react.

    Only axes that actually state a range: a figure built without explicit
    bounds leaves ``range`` as None, and indexing it would raise inside the
    refresh -- aborting the repaint with nothing shown.
    """
    ranges: dict[str, list[float]] = {}
    for axis in ("xaxis", "yaxis"):
        bound = getattr(getattr(figure.layout, axis, None), "range", None)
        if not bound:
            continue
        # as_float, not float(): a bound that is None or a non-number is
        # skipped rather than raising inside the refresh.
        low, high = as_float(bound[0]), as_float(bound[1])
        if low is None or high is None:
            continue
        ranges[f"{axis}.range"] = [low, high]
    return ranges


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


def _discard_when_hidden(dialog) -> None:
    """Delete a dialog's elements once it is hidden.

    ``close()`` only hides a dialog; without this its card, inputs and buttons
    stay in the document, so a long session -- peeking at files, cancelling
    Save As -- grew the DOM without bound. Every designer dialog is
    single-use, so deleting on hide costs nothing.
    """
    dialog.on("hide", dialog.delete)


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
    from nicegui import background_tasks, ui

    state = DesignerState(config=config, data=data)
    # The session is swapped when the toolbar opens a config or starts a New
    # Design, so it lives in a one-element dict the handlers can rebind.
    sess = {"session": session}
    # The directory the config picker scans -- where `parity-plot design` ran.
    launch_dir = Path.cwd()

    # One in-flight refresh at a time, for the whole app rather than per client:
    # a refresh rebuilds the figure and the table off a dataset that an earlier
    # refresh may still be reading, and two browser tabs share one
    # DesignerState, so a per-tab lock would let them interleave half-applied
    # states. Held across awaits, so commits serialise without blocking the
    # loop for anyone.
    _refresh_lock = asyncio.Lock()

    @ui.page("/")
    def page() -> None:
        ui.dark_mode(True)
        ui.add_css(RESPONSIVE_LAYOUT_CSS)
        # Added once per page, not once per dialog open: ui.add_css appends to
        # the document head, so doing it per preview left a duplicate <style>
        # behind on every peek in a long session.
        ui.add_css(PEEK_GRID_CSS)
        ui.add_body_html(RESPONSIVE_PLOT_SCRIPT)
        ui.query(".nicegui-content").classes(PAGE_CONTENT_CLASSES)

        def current_choice() -> str:
            s = sess["session"]
            return s.config_path.name if s.config_path is not None else UNSAVED

        def picker_options(listed: list[str]) -> list[str]:
            """The dropdown's options: ``listed`` configs plus the current one.

            Built on the loop from the session as it stands *now*. The listing
            itself is slow and runs in a thread; a session swapped while it ran
            must still find its own name among the options, or setting the
            value resets the select to None -- which NiceGUI reports as a change.
            """
            s = sess["session"]
            names = [n for n in listed if n != UNSAVED]
            if s.config_path is not None and s.config_path.name not in names:
                names.insert(0, s.config_path.name)
            # The unbound sentinel is offered only while unbound.
            return ([UNSAVED] if s.config_path is None else []) + names

        def show_picker(listed: list[str]) -> None:
            """Options first, value second, in one call: never a value it lacks."""
            config_pick.set_options(picker_options(listed), value=current_choice())

        async def refresh_picker() -> None:
            """Re-list the configs in the launch directory, off the event loop.

            ``config_choices`` parses every ``*.toml`` in the directory to
            decide whether the designer can open it, and on a network filesystem
            that is a round trip per file -- on page load, and again after every
            open, Save As and failed open.
            """
            listed = await offload(config_choice_names, launch_dir, None)
            show_picker(listed)

        # Two quick config picks race, so each claims a generation before its
        # (slow) read. Only the newest is allowed to swap the session in.
        _open_generation = Generation()

        # The data panel returns a hook that marks its join field; held here so
        # refresh() can call it after each change. Rebuilt with the column.
        marks: dict[str, Callable[[list], None]] = {"join": lambda _problems: None}

        async def refresh() -> None:
            """Rebuild the figure and every dependent view after a change.

            Async because the data panel's commit (and so the dataset it
            commits) can be an off-the-loop file read; the figure is only
            rebuilt once the read has actually landed.

            Runs as a background task when spawned by the page builder or a
            sync refresher slot; a background task starts with an empty slot
            stack, so the client context is entered here rather than assumed
            -- ``ui.run_javascript`` and ``ui.notify`` need it.
            """
            client = plot_view.client
            async with _refresh_lock:
                with client:
                    started = time.monotonic()
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
                    blocking = state.last_error or (
                        errors[0].message if errors else None
                    )

                    if blocking:
                        set_status(f"⛔  {blocking}", "error")
                    elif warnings:
                        set_status(f"⚠️  {warnings[0].message}", "warn")
                    else:
                        set_status("Ready", "info")

                    marks["join"](errors)  # only errors redden a field
                    save_as_btn.set_enabled(not blocking)

                    # The views first, the write second. An auto-save failure on
                    # NFS used to escape `refresh()` *after* the status bar was
                    # painted "Ready", so the inspector and table never updated
                    # and the only evidence was a line in the server log.
                    refresh_inspector()
                    refresh_table()

                    # Auto-save: only a clean (no error), bound config is written;
                    # autosave no-ops when unbound and skips an unchanged config.
                    # The bound file thus always holds the last valid config -- a
                    # broken edit is withheld until it is fixed. A warning does
                    # not withhold the write.
                    #
                    # Debounced and off the refresh lock: this runs on every
                    # keystroke in a text control, and each write is several NFS
                    # round trips. Deferring it also keeps a slow write from
                    # queueing every subsequent refresh behind it.
                    #
                    # The session is bound now, not looked up when the timer
                    # fires: a pending save belongs to the design being edited,
                    # and must reach that design's file even if another config
                    # has been opened by then.
                    if not blocking:
                        autosave.schedule(sess["session"], state.config)

                    debug_log(
                        "refresh() %.0fms%s",
                        (time.monotonic() - started) * 1000,
                        f" -- {blocking}" if blocking else "",
                    )

        async def _autosave_now(session: Session, config) -> str | None:
            """Write the config, off the event loop. Returns a message on failure."""
            return await offload(session.autosave, config)

        # A debounced auto-save: a burst of edits is one write, carrying the
        # newest config. `on_error` exists because `autosave` reports rather
        # than raises -- this is the background path, and a raise here would
        # abort whatever the refresh was doing instead of being shown.
        autosave = Debouncer(_autosave_now, delay=0.4)
        autosave.on_error = lambda message: set_status(f"⛔  {message}", "error")

        async def reload_everything() -> None:
            """After a dataset swap the whole view is stale, selection included."""
            await refresh()

        # settings_column is defined before the layout that calls it; its panels'
        # on_change callbacks reference refresh/reload_everything, which are
        # defined further up and only fire on later user interaction. The
        # refreshable supports async funcs: a not-awaited refresh becomes a
        # background task; awaiting it waits for the rebuild.
        @ui.refreshable
        def settings_column() -> None:
            # The data panel awaits its on_change, so it gets the coroutine
            # function; every other panel commits *synchronously* and drops the
            # return value, so it gets the scheduling shim instead. Passing the
            # async `refresh` straight to a sync panel means the coroutine is
            # never awaited -- no redraw, no status bar, no auto-save.
            marks["join"] = build_data_panel(state, reload_everything)
            notify = sync_refresher(refresh)
            build_tolerances_panel(state, notify)
            build_polynomial_lines_panel(state, notify)
            build_histogram_panel(state, notify)
            build_encoding_panel(state, notify)
            build_controls(state, notify)

        with ui.header().classes("items-center justify-between"):
            ui.label("parity-plot designer").classes("text-lg font-medium")
            with ui.row().classes("items-center gap-2"):
                config_pick = ui.select(
                    # Seeded with just the current value: the real listing
                    # parses every *.toml in the launch directory, which is file
                    # I/O the page builder must not block on. `refresh_picker`
                    # fills it in once the page is up. A value missing from the
                    # options would raise at construction and 500 the page.
                    [current_choice()],
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
                    # The table's filter switches commit synchronously too.
                    on_filter_change=sync_refresher(
                        refresh, name="refresh after filter"
                    ),
                )

                def on_point_click(event) -> None:
                    points = (event.args or {}).get("points") or []
                    if not points:
                        return
                    key = key_from_customdata(points[0].get("customdata"))
                    select_record(state, key, refresh_inspector, refresh_table)

                plot_view.on("plotly_click", on_point_click)

                async def on_brush(event) -> None:
                    # The refresher passed here is the async refresh; the
                    # brush helpers call it and await the result.
                    apply_brush(
                        state, event.args, sync_refresher(refresh, name="brush")
                    )

                plot_view.on("plotly_selected", on_brush)
                plot_view.on(
                    "plotly_deselect",
                    lambda _: apply_brush(
                        state, None, sync_refresher(refresh, name="brush clear")
                    ),
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

        def _sync_picker() -> None:
            """Point the picker at the current choice, listing in the background.

            Only the value is set synchronously -- it must always be among the
            options or NiceGUI rejects the select and returns HTTP 500. The
            options themselves are re-derived off the loop.
            """
            show_picker(list(config_pick.options))
            _spawn(refresh_picker())

        def _has_unsaved_unbound_edits() -> bool:
            s = sess["session"]
            return s.config_path is None and s.is_dirty(state.config)

        async def _swap(
            new_session: Session, cfg: ParityConfig, new_data, generation: int
        ) -> None:
            # A pending auto-save holds the user's last edit to the config being
            # replaced, bound to that config's own session: write it to its own
            # file now. Dropping it lost the edit; deferring it would let the new
            # design's first edit replace it in the debouncer.
            await autosave.flush()
            # The flush awaited, so a newer open may have claimed a generation
            # meanwhile. Checked again here, with no await between this check
            # and the swap, or two quick picks could land in either order.
            if generation != _open_generation.value:
                debug_log("discarded an open superseded during the save")
                return
            sess["session"] = new_session
            state.load_session_config(cfg, new_data)
            settings_column.refresh()
            _sync_picker()
            await refresh()

        async def _open_named_now(name: str) -> None:
            # Two quick picks race: each reads its config and every data file it
            # names, and whichever *finishes* last used to win -- not the one the
            # user picked last. Claim a generation on the loop before the read,
            # the same way the data panel does.
            generation = _open_generation.bump()
            try:
                # Session.start reads the TOML and every data file it names --
                # off the event loop for the same NFS reason as the rest.
                new_session, cfg, new_data = await offload(
                    Session.start, (), launch_dir / name
                )
            except (ConfigError, DataError, ValueError, OSError) as exc:
                if generation != _open_generation.value:
                    return  # superseded; do not report a stale failure
                set_status(f"⛔  {exc}", "error")
                _sync_picker()  # revert the selection to the still-open config
                return
            if generation != _open_generation.value:
                debug_log("discarded superseded open of %s", name)
                return
            debug_log("opened config %s", name)
            await _swap(new_session, cfg, new_data, generation)

        def open_named(name: str | None) -> None:
            # None is what a select reports when its value falls out of its
            # options; it names no config.
            if not name or name == UNSAVED or name == current_choice():
                return

            if _has_unsaved_unbound_edits():
                confirm_discard(
                    lambda: _spawn(_open_named_now(name)), on_cancel=_sync_picker
                )
            else:
                _spawn(_open_named_now(name))

        def new_design() -> None:
            async def do_new() -> None:
                generation = _open_generation.bump()
                new_session, cfg, new_data = Session.start((), None)
                if generation != _open_generation.value:
                    return
                await _swap(new_session, cfg, new_data, generation)

            if _has_unsaved_unbound_edits():
                confirm_discard(lambda: _spawn(do_new()))
            else:
                _spawn(do_new())

        def _spawn(awaitable: Coroutine[Any, Any, Any]) -> None:
            """Start an async continuation as a background task.

            Takes the coroutine, not the function: every caller writes
            ``_spawn(work())``. (It once called its argument, so every one of
            those calls raised inside a click handler and Save As, New Design and
            opening a config all silently did nothing.)

            ``confirm_discard`` calls its ``proceed`` from a sync button
            handler, so the async half needs a task to run in. The task starts
            with an empty slot stack, so anything it does that needs a client
            (ui.notify, run_javascript) must enter its own context -- refresh
            already does; dialog-building code runs inside ``with client:``
            blocks at its call sites or inside slot-aware refreshables.
            """
            background_tasks.create(awaitable, name="designer continuation")

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
            _discard_when_hidden(dialog)
            dialog.open()

        async def save_as(path: Path) -> None:
            try:
                # The write is file I/O; off the loop like every other one.
                written = await offload(sess["session"].save, state.config, path)
            except (ValueError, OSError) as exc:
                set_status(f"⛔  {exc}", "error")
                return
            # The one place a toast survives: a save is a discrete action whose
            # confirmation is transient good news; the status bar reverts to the
            # live state on the next refresh. Runs inside a spawned task, so
            # ui.notify gets the client context entered for it.
            with plot_view.client:
                ui.notify(f"Saved {written}", type="positive")
            set_status(f"✅  Saved {written}", "ok")
            _sync_picker()
            await refresh()

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
                        on_click=lambda: (
                            dialog.close(),
                            _spawn(_save_from_input(target)),
                        ),
                    )
            _discard_when_hidden(dialog)
            dialog.open()

        async def _save_from_input(target) -> None:
            await save_as(Path(target.value))

        # The initial paint: async refresh as a background task so the page
        # builder stays synchronous (the page function itself is not awaited).
        _spawn(refresh())
        # The picker was built holding only the current config; list the rest
        # now, off the loop. Without this nothing else could ever be opened.
        _spawn(refresh_picker())

    return state
