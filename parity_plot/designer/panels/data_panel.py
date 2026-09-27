"""Choosing the dataset: the open files, and which column is ref/test/join/group.

The designer can hold an arbitrary set of files; ref and test are picked as
`file:column` across all of them. ref/test are offered only from numeric columns
(they are the axes); join is a bare column name common to the files; group is any
`file:column`. Files are opened through a server-side browser dialog, so the
designer can start empty.

Every handler here is async and every file read is offloaded to NiceGUI's
thread pool (:func:`parity_plot.designer.io.offload`). Re-deriving the options
re-reads all open files, and on a laggy filesystem that takes seconds -- a
synchronous handler would block the event loop past the websocket heartbeat
deadline and every browser tab would show the reconnect overlay.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from ...data import DataError, hover_candidates
from ...sources import open_sources
from ..io import debug_log, offload
from ..state import DesignerState
from ..widgets import as_int
from .section import section

_NONE = "— none —"


def _discard_when_hidden(dialog) -> None:
    """Delete a dialog's elements once hidden. See ``app._discard_when_hidden``.

    Duplicated rather than imported: this module is imported by the panels, and
    ``app`` imports the panels, so a shared helper belongs in a module neither
    depends on the other for.
    """
    dialog.on("hide", dialog.delete)


@dataclass(frozen=True)
class _Configured:
    """The config values ``column_options`` must keep offering.

    Only the fields a select can hold, so the fallback path can be built from
    the same arguments the caller already has rather than requiring a whole
    ``DataConfig``.
    """

    ref: str | None = None
    test: str | None = None
    join: str | None = None
    group: tuple[str, ...] = ()
    color_column: str | None = None
    hover_columns: tuple[str, ...] = ()


def _background_spawn(awaitable: Coroutine[Any, Any, None]) -> None:
    """Default spawn: a NiceGUI background task, named for the transcript."""
    from nicegui import background_tasks

    background_tasks.create(awaitable, name="data panel commit")


class CommitGate:
    """At most one commit in flight, and never one raised by our own events.

    Two separate problems, one owner.

    **The guard must be checked at emission time.** NiceGUI calls an event
    handler synchronously and only schedules it afterwards if it returns an
    awaitable, so a suspension flag checked *inside* the async handler is
    already down by the time the body runs. That is how one Add File turned into
    roughly six full reads of every open CSV: the panel assigned
    ``ref_sel.value`` to guess an axis, each assignment emitted a change, each
    change re-entered the commit with the guard released. :meth:`submit` is
    called from a *sync* wrapper, while the emitting frame is still on the
    stack, so a suspended emission is dropped before it can spawn anything.

    **A burst is one commit, not N.** Edits arrive faster than a slow
    filesystem can answer, and each concurrent commit would read every open
    file. While one runs, further requests collapse into a single catch-up that
    re-reads the widgets -- so the newest choice is what lands, and the reads
    are serialised rather than piled onto the thread pool.
    """

    def __init__(
        self, spawn: Callable[[Coroutine[Any, Any, None]], None] | None = None
    ) -> None:
        self._spawn = _background_spawn if spawn is None else spawn
        self._depth = 0
        self._running = False
        self._queued = False
        self._in_flight = 0

    @property
    def is_suspended(self) -> bool:
        return self._depth > 0

    @property
    def in_flight(self) -> int:
        """Spawned drains that have not finished; 1 means a commit is running."""
        return self._in_flight

    @contextmanager
    def suspend(self) -> Iterator[None]:
        """Suppress commits for the duration. Nesting is counted, not boolean.

        A leak would wedge the panel permanently -- nothing would ever commit
        again -- so the flag is restored in a ``finally`` rather than being
        lowered at the end of the body.
        """
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1

    def submit(self, work: Callable[[], Awaitable[None]]) -> None:
        """Run ``work``, unless suspended or a commit is already running.

        Synchronous by design: the guard is only meaningful while the emitting
        frame is still on the stack.
        """
        if self.is_suspended:
            return
        if self._running:
            self._queued = True
            return
        self._running = True
        self._in_flight += 1
        self._spawn(self._drain(work))

    async def _drain(self, work: Callable[[], Awaitable[None]]) -> None:
        try:
            while True:
                self._queued = False
                await work()
                if not self._queued:
                    break
        finally:
            # Release on failure too: an unreadable file must not leave the
            # panel permanently refusing commits.
            self._running = False
            self._in_flight -= 1


def _column_of(ref: str | None) -> str | None:
    """The bare column name of a ``file:column`` ref, or None."""
    if not ref or ":" not in ref:
        return None
    return ref.split(":", 1)[1]


def current_only_options(data: Any) -> dict[str, list[str]]:
    """Option lists holding nothing but the config's current values.

    Lets the panel build its selects with *no* file read at all, so opening a
    page or swapping a config cannot block the event loop on a slow
    filesystem. ``refresh_options`` fills the real lists in afterwards.

    Nothing is filtered out here: a value in the config that the derived lists
    could not produce is exactly what makes ``ui.select(options, value=...)``
    raise and 500 the whole page.
    """
    return {
        "ref": [data.ref] if data.ref else [],
        "test": [data.test] if data.test else [],
        "join": [data.join] if data.join else [],
        "group": list(data.group),
        "color_column": [data.color_column] if data.color_column else [],
        "hover_columns": list(data.hover_columns or ()),
    }


def _offer(derived: list[str], *current: str | None) -> list[str]:
    """``derived`` plus any current value it does not already contain.

    The derived lists are the honest view of the files; a configured value is
    appended when the derivation could not produce it, so the select can hold
    what the config actually says. Offering a value the files no longer have is
    a visible, fixable oddity; omitting it makes the page fail to load.
    """
    out = list(derived)
    for value in current:
        if value and value not in out:
            out.append(value)
    return out


def column_options(
    files: tuple[Path, ...],
    ref: str | None = None,
    test: str | None = None,
    join: str | None = None,
    *,
    group: Sequence[str] = (),
    color_column: str | None = None,
    hover_columns: Sequence[str] | None = (),
) -> dict[str, list[str]]:
    """Dropdown options per role. See :func:`read_column_options`."""
    options, _ = read_column_options(
        files,
        ref,
        test,
        join,
        group=group,
        color_column=color_column,
        hover_columns=hover_columns,
    )
    return options


def read_column_options(
    files: tuple[Path, ...],
    ref: str | None = None,
    test: str | None = None,
    join: str | None = None,
    *,
    group: Sequence[str] = (),
    color_column: str | None = None,
    hover_columns: Sequence[str] | None = (),
) -> tuple[dict[str, list[str]], bool]:
    """Dropdown options per role, and whether the open files could be read.

    The flag is for the panel's hover pruning: pins are dropped when the files
    were read and no longer offer them, never because a read failed (NFS, a
    file mid-rewrite) -- the fallback lists carry nothing derived, so pruning
    against them would empty the selection, and the next edit would save that.

    ``ref``/``test`` are numeric ``file:column`` (they are the plotted axes);
    ``group`` is any ``file:column``; ``join`` is a bare column name present in
    every open file, since the key has to exist on both sides to join. An
    unreadable file yields only the current values rather than raising -- the
    panel must still render so a different file can be chosen.

    ``hover_columns`` lists the auto hover set from the ref/test files. It
    needs a resolvable ref *and* test; when either is missing, or resolving
    raises (a ref left over from a just-removed file), it falls back to the
    configured set (or ``[]``) so the panel still renders.

    Every list is passed through :func:`_offer`, so a select can never be
    handed a value it does not contain.
    """
    fallback = current_only_options(
        _Configured(
            ref=ref,
            test=test,
            join=join,
            group=tuple(group),
            color_column=color_column,
            hover_columns=tuple(hover_columns or ()),
        )
    )
    if not files:
        return fallback, True
    try:
        src = open_sources(files)
    except DataError:
        return fallback, False

    # numeric_refs, not numeric_columns: a file whose basename repeats among the
    # open set must be named by its full path, because that is the only form
    # Sources.resolve accepts.
    numeric = src.numeric_refs()
    common = [
        col
        for col in src.tables[src.order[0]]
        if all(col in src.tables[f] for f in src.order)
    ]
    # group and join are file-independent (bare column names): a group labels
    # the joined entity, and a join key must match across files. group offers
    # every distinct column name; join offers those present in every file.
    distinct: list[str] = []
    for f in src.order:
        for col in src.tables[f]:
            if col not in distinct:
                distinct.append(col)
    # Group is almost never the plotted axis: grouping by a continuous ref/test
    # value gives ~one group per point. Drop the ref/test column names (bare, to
    # match group's file-independence) from the group list.
    axis_columns = {c for c in (_column_of(ref), _column_of(test)) if c is not None}
    group_options = [c for c in distinct if c not in axis_columns]
    # hover_candidates needs both axes resolvable; a stale ref left pointing at
    # a removed file resolves to a DataError, which we swallow so the panel
    # keeps rendering (same reason the whole function swallows DataError).
    try:
        derived_hover = hover_candidates(src, ref, test, join) if ref and test else []
    except DataError:
        derived_hover = []
    return {
        "ref": _offer(numeric, ref),
        "test": _offer(numeric, test),
        "group": _offer(group_options, *group),
        "join": _offer(common, join),
        "color_column": _offer(numeric, color_column),
        "hover_columns": _offer(derived_hover, *(hover_columns or ())),
    }, True


def build_data_panel(
    state: DesignerState, on_change: Callable[[], Any]
) -> Callable[[list], None]:
    """The open-file list, an Add-file browser, and the ref/test/join/group maps.

    ``on_change`` may be sync or async; it is awaited when the commit succeeds,
    so the status bar and auto-save run after the data is actually loaded.

    Returns a ``mark_problems(problems)`` hook so ``app.refresh`` can redden the
    exact widget a validation problem names -- today just the ``join`` select.
    """
    from nicegui import ui

    with section("Data"):
        files = list(state.config.data.files)
        # The config this panel was built for. Opening another config rebuilds
        # the panel, but this one's handlers may still be awaiting a read; once
        # the epoch moves they must not commit (see ``apply``).
        epoch = state.config_epoch
        # The selects are built with their current values as the only options,
        # and the real lists are derived in the background. Deriving them here
        # would read every open CSV on the event loop -- on every page load and
        # every config swap, which is the NFS stall the scan reported.
        options = current_only_options(state.config.data)

        # One commit at a time, and never one triggered by our own option
        # updates. See CommitGate for why the guard is checked synchronously.
        gate = CommitGate()

        # Add File sits at the top of the section: choosing the data comes first.
        ui.button("Add File", icon="add", on_click=lambda: _browse(_pick_file)).props(
            "flat"
        )

        file_list = ui.column().classes("w-full gap-0")

        def render_files() -> None:
            file_list.clear()
            with file_list:
                if not files:
                    ui.label("No files open").classes("text-sm opacity-60 italic")
                for f in files:
                    with ui.row().classes("w-full items-center gap-1 no-wrap"):
                        ui.label(f.name).classes("text-sm grow")
                        ui.button(
                            "👀",
                            on_click=lambda _, p=f: _preview_dialog(p),
                        ).props("flat dense round size=sm").tooltip(
                            "Peek at the first rows"
                        )
                        # Gated like Add File: an ungated remove ran alongside a
                        # gated commit, and the older of two option refreshes
                        # could land last and re-offer the removed file's columns.
                        ui.button(
                            icon="close",
                            on_click=lambda _, p=f: gate.submit(partial(_remove, p)),
                        ).props("flat dense round size=sm")

        def _pick_file(path: Path) -> None:
            """Sync wrapper: the browser's pick handler, gated like any other commit."""
            gate.submit(partial(_add, path))

        async def _reapply() -> None:
            """Re-derive dependent options, then commit -- one gated run.

            The old code returned a tuple ``(refresh_dependent(), apply())``
            from a sync lambda; with both halves async the pair would be two
            never-awaited coroutines. Sequencing them here keeps the
            commit-after-rederive order.
            """
            await refresh_dependent()
            await apply()

        # Every handler is a *sync* wrapper around a gate submit. That is load
        # bearing: the guard is only effective while the emitting frame is still
        # on the stack, and NiceGUI calls sync handlers inline.
        ref_sel = ui.select(
            options["ref"],
            value=state.config.data.ref,
            label="Reference",
            on_change=lambda: gate.submit(_reapply),
        ).classes("w-full")
        test_sel = ui.select(
            options["test"],
            value=state.config.data.test,
            label="Test",
            on_change=lambda: gate.submit(_reapply),
        ).classes("w-full")
        join_sel = ui.select(
            [_NONE, *options["join"]],
            value=state.config.data.join or _NONE,
            label="Join column (blank = pair by order)",
            # The join is not a hover candidate (it is already the key line), so
            # changing it changes the hover set -- re-derive before applying.
            on_change=lambda: gate.submit(_reapply),
        ).classes("w-full")
        group_sel = (
            ui.select(
                options["group"],
                value=list(state.config.data.group),
                multiple=True,
                label="Group by (one or more columns)",
                on_change=lambda: gate.submit(apply),
            )
            .classes("w-full")
            .props("use-chips")
        )
        color_sel = ui.select(
            [_NONE, *options["color_column"]],
            value=state.config.data.color_column or _NONE,
            label="Colour column (numeric, for colorscale)",
            on_change=lambda: gate.submit(apply),
        ).classes("w-full")

        # The switch is declared first so it sits above the select it governs;
        # its handler resolves at click time, by when the select exists.
        hover_auto = ui.switch(
            "Auto (all columns from the ref/test files)",
            value=state.config.data.hover_columns is None,
            on_change=lambda: gate.submit(_on_hover_auto),
        )
        hover_sel = (
            ui.select(
                options["hover_columns"],
                value=list(state.config.data.hover_columns or ()),
                multiple=True,
                label="Hover columns",
                on_change=lambda: gate.submit(apply),
            )
            .classes("w-full")
            .props("use-chips")
        )
        hover_sel.set_enabled(not hover_auto.value)

        async def _on_hover_auto() -> None:
            hover_sel.set_enabled(not hover_auto.value)
            await apply()

        async def refresh_options(*, guess: bool) -> None:
            """Re-derive every option list; with ``guess``, fill an unset ref/test.

            Every value assignment and every ``update()`` below is wrapped in the
            gate's suspension. That includes the ``update()`` calls: a select
            whose current value is no longer among its options resets to None,
            which is itself an emission -- and one that used to fire a fresh
            full read of every open file.

            ``guess`` only where a commit follows (adding or removing a file):
            the guessed values are set under suspension, so without that commit
            the selects would show an axis pair the state never received -- a
            chosen-looking ref and test over an empty plot.
            """
            opts, readable = await _options()
            ref_sel.options, test_sel.options = opts["ref"], opts["test"]
            join_sel.options = [_NONE, *opts["join"]]
            group_sel.options = opts["group"]
            color_sel.options = [_NONE, *opts["color_column"]]
            _refresh_hover(opts["hover_columns"], prune=readable)
            with gate.suspend():
                # Guess ref/test if unset and enough numeric columns are offered.
                if guess and not ref_sel.value and len(opts["ref"]) >= 1:
                    ref_sel.value = opts["ref"][0]
                if guess and not test_sel.value and len(opts["test"]) >= 2:
                    test_sel.value = opts["test"][1]
                for s in (ref_sel, test_sel, join_sel, group_sel, color_sel):
                    s.update()

        async def refresh_dependent() -> None:
            """Re-derive the options that depend on the ref/test/join choice."""
            opts, readable = await _options()
            group_sel.options = opts["group"]
            with gate.suspend():
                group_sel.update()
            _refresh_hover(opts["hover_columns"], prune=readable)

        async def _options() -> tuple[dict[str, list[str]], bool]:
            """read_column_options over the open files, off the event loop.

            Timing goes to the transcript in --debug so a slow-filesystem
            read is visible in the terminal instead of only as UI lag.
            """
            files_tuple = tuple(files)
            started = time.monotonic()
            # Every current value goes in, so every list keeps offering it. The
            # colour select is single-valued: left out, a configured colour the
            # derivation cannot produce (a path-form ref, a briefly unreadable
            # file) was reset to None on every page load. Hover is the
            # exception -- _refresh_hover decides which pins survive.
            opts, readable = await offload(
                read_column_options,
                files_tuple,
                ref_sel.value,
                test_sel.value,
                _join_value(),
                group=tuple(group_sel.value or ()),
                color_column=_color_value(),
            )
            debug_log(
                "column_options(%d file%s) %.0fms",
                len(files_tuple),
                "s" if len(files_tuple) != 1 else "",
                (time.monotonic() - started) * 1000,
            )
            return opts, readable

        def _join_value() -> str | None:
            return None if join_sel.value == _NONE else join_sel.value

        def _color_value() -> str | None:
            # `or None`: a select whose value fell out of its options holds None.
            return None if color_sel.value == _NONE else (color_sel.value or None)

        def _refresh_hover(candidates: list[str], *, prune: bool) -> None:
            """Re-derive hover options and drop pinned refs no longer offered.

            A pinned ref left pointing at a removed file -- or at a file that no
            longer backs ref or test, which ``load`` also refuses -- would make
            every later ``apply()`` raise a ``DataError`` the user could not see
            the cause of, so stale selections are pruned here rather than left
            to fail.

            Only when ``prune``: that is, when the files were actually read. A
            failed read offers no candidates at all, and pruning against that
            emptied the selection -- which the next data edit then saved.
            """
            current = list(hover_sel.value or ())
            kept = [v for v in current if v in candidates] if prune else current
            hover_sel.options = _offer(candidates, *kept)
            if kept != current:
                # Suspending is re-entrant, so this nests safely inside
                # refresh_options' own suspension rather than clobbering it.
                with gate.suspend():
                    hover_sel.value = kept
            hover_sel.update()

        def _structural_clears() -> tuple[str, ...]:
            """Fields whose unset state is a *value*, so they must be cleared.

            ``merge`` drops a ``None`` override by design, which is right for a
            CLI and wrong here: "no ref selected" and "no colour column" are real
            states the user reaches by clearing the select. Passed through
            ``clear`` they reset to the dataclass default, so clearing the colour
            column actually clears it instead of keeping the stale one.
            """
            names = []
            if not ref_sel.value:
                names.append("ref")
            if not test_sel.value:
                names.append("test")
            if _color_value() is None:
                names.append("color_column")
            if hover_auto.value:
                # Auto is hover_columns=None, and merge drops None overrides.
                names.append("hover_columns")
            return tuple(names)

        async def apply() -> None:
            if gate.is_suspended:
                return
            if state.config_epoch != epoch:
                # Another config was opened while this panel's handler awaited
                # a read (the option refresh before a commit). The generation
                # below cannot catch it: claimed now, after the swap, it would
                # be current, and this panel's [data] would overwrite the newly
                # opened config's -- then be auto-saved into its file.
                debug_log("data panel of a replaced config: commit dropped")
                return
            # Annotated because it is splatted into a signature with a typed
            # keyword-only `clear`: without it the checker cannot tell that
            # `source` never carries that key.
            source: dict[str, Any] = dict(
                files=tuple(files),
                ref=ref_sel.value or None,
                test=test_sel.value or None,
                join=_join_value(),
                group=tuple(group_sel.value or ()),
                color_column=_color_value(),
            )
            if not hover_auto.value:
                # An empty selection is a real value meaning "no extra rows",
                # not "unset", so () must reach the config.
                source["hover_columns"] = tuple(hover_sel.value or ())

            # Claim the generation on the loop *before* the slow read, so a
            # newer choice (or a config swap) can invalidate this one while it
            # is in flight.
            generation = state.begin_data_source()
            started = time.monotonic()
            # The prepare reads every open file (data.load) in a worker thread.
            # Off the event loop for the same reason as column_options above.
            prepared = await offload(
                state.prepare_data_source,
                clear=_structural_clears(),
                **source,
            )
            # Back on the loop: merge only the [data] section into the config as
            # it stands now, so an edit made during the load is not reverted.
            applied = state.commit_data_source(prepared, generation)
            debug_log(
                "set_data_source(%s%s) %.0fms%s",
                ",".join(p.name for p in files) or "no files",
                ", auto-hover" if hover_auto.value else "",
                (time.monotonic() - started) * 1000,
                "" if applied else f" -- {prepared.error or 'superseded'}",
            )
            if not applied and prepared.error is None:
                # Superseded by a newer choice or a config swap: say nothing,
                # because the newer change is about to repaint on its own.
                return
            # On failure last_error is set; the status bar (painted by
            # on_change -> refresh) shows it persistently -- no toast.
            # Awaited only if it is awaitable: a sync on_change is legal.
            result = on_change()
            if inspect.isawaitable(result):
                await result

        async def _remove(path: Path) -> None:
            if path in files:
                files.remove(path)
            render_files()
            await refresh_options(guess=True)
            await apply()

        async def _add(path: Path) -> None:
            debug_log("add file %s", path)
            if path not in files:
                files.append(path)
            render_files()
            await refresh_options(guess=True)
            await apply()

        render_files()

        # The real option lists, derived off the event loop now that the panel
        # is on screen. Building the selects with only the current values is
        # what keeps a page load -- and every config swap -- from reading every
        # open CSV synchronously. Gated like any other commit, so the value
        # assignments it makes cannot re-enter and re-read.
        #
        # create_or_defer, not create: the panel is also built without a running
        # loop (tests, script mode), where create would raise.
        from nicegui import background_tasks

        background_tasks.create_or_defer(
            refresh_options(guess=False), name="data panel options"
        )

        def mark_problems(problems) -> None:
            """Redden the join select while a `data.join` problem stands."""
            has_join_problem = any(
                getattr(p, "field", None) == "data.join" for p in problems
            )
            join_sel.props(remove="error")
            if has_join_problem:
                join_sel.props("error")

        return mark_problems


def _preview_dialog(path: Path) -> None:
    """Zoom-open the first rows of a CSV in an AG-Grid table.

    AG-Grid gives a sticky header, sortable/resizable columns, and a dark theme
    (it follows the designer's dark mode) out of the box. The row count is
    adjustable; the read is bounded (``datasets.preview``), so it is instant even
    on a huge file.
    """
    from nicegui import background_tasks, ui

    from ...data import DataError
    from ..datasets import preview

    # A dialog-scoped generation counter, so a slow read that lands after a
    # newer request cannot render over it.
    counter = {"v": 0}

    def _next_generation() -> int:
        counter["v"] += 1
        return counter["v"]

    _generation = counter

    with ui.dialog() as dialog, ui.card().classes("w-[85vw] max-w-none"):
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            ui.label(path.name).classes("text-base font-medium")
            with ui.row().classes("items-center gap-2 no-wrap"):
                rows_input = (
                    ui.number(
                        "Rows",
                        value=100,
                        min=1,
                        max=10000,
                        format="%d",
                        on_change=lambda: body.refresh(),
                    )
                    .props("debounce=500")
                    .classes("w-24")
                )
                ui.button(icon="close", on_click=dialog.close).props("flat dense round")

        @ui.refreshable
        async def body() -> None:
            limit = _row_limit(rows_input.value)
            # A slow read can outlast the field's 500ms debounce, so two
            # `body.refresh()` runs can both be in flight. Only the newest
            # renders; an older one would append a second grid on top of the
            # first, leaving a duplicated table in the dialog.
            generation = _next_generation()
            try:
                started = time.monotonic()
                data = await offload(preview, path, limit)
                debug_log(
                    "preview(%s, %d rows) %.0fms",
                    path.name,
                    limit,
                    (time.monotonic() - started) * 1000,
                )
            except DataError as exc:
                if generation != _generation["v"]:
                    return
                ui.label(str(exc)).classes("text-red-400 text-sm")
                return
            if generation != _generation["v"]:
                debug_log("discarded superseded preview of %s", path.name)
                return

            ui.label(
                f"first {len(data.rows)} row(s) · {len(data.columns)} column(s)"
            ).classes("text-xs opacity-60")
            # Map each column to a safe internal field id (c0, c1, ...) so a
            # header containing a dot is not read by AG-Grid as a nested path.
            # Numeric columns get a numeric schema so they sort by magnitude, not
            # lexically ("9" before "100"), and their cells carry real numbers.
            field_of = {c: f"c{i}" for i, c in enumerate(data.columns)}
            column_defs = []
            for c in data.columns:
                col = {"headerName": c, "field": field_of[c]}
                if c in data.numeric:
                    col["type"] = "numericColumn"
                    col["filter"] = "agNumberColumnFilter"
                column_defs.append(col)

            def _cell(value: str, numeric: bool) -> str | float | None:
                if not numeric:
                    return value
                text = (value or "").strip()
                # `numeric` already proved every non-empty cell in the previewed
                # rows parses, so this cannot fail; the guard keeps a surprise
                # from killing the whole grid inside a background task, where
                # the user would just see an empty dialog and no message.
                try:
                    return float(text) if text else None
                except ValueError:
                    return None

            row_data = [
                {
                    field_of[c]: _cell(row.get(c, ""), c in data.numeric)
                    for c in data.columns
                }
                for row in data.rows
            ]
            ui.aggrid(
                {
                    "columnDefs": column_defs,
                    "rowData": row_data,
                    # Tight rows -- NiceGUI/AG-Grid default to a lot of vertical
                    # air; a data peek wants to show as many rows as it can.
                    "rowHeight": 24,
                    "headerHeight": 36,
                    "defaultColDef": {
                        "sortable": True,
                        "resizable": True,
                        "filter": True,
                        "minWidth": 100,
                    },
                },
                theme="balham",
            ).classes("peek-grid w-full").style("height: 65vh")

        # An async refreshable returns a coroutine when called; unawaited it
        # would never run the read. Schedule it -- refreshable targets are
        # per-task, and this call site already sits in the page's task.
        result = body()
        if inspect.isawaitable(result):
            background_tasks.create(result, name="preview body")

    _discard_when_hidden(dialog)
    dialog.open()


def _row_limit(value: Any) -> int:
    """How many rows the preview should read, from the number field's value.

    A ``ui.number`` can hold anything the user half-typed, and an ``int()`` that
    raises here would abort the read inside a background task -- the dialog
    would stay blank with no message anywhere. Fall back to the default.

    ``as_int`` rather than ``int(value or 100)``: a field legitimately holding
    ``0`` must clamp to 1, not silently become 100. The fallback is an explicit
    ``is None`` test for the same reason -- ``x or 100`` cannot tell a 0 from a
    missing value.
    """
    parsed = as_int(value)
    return max(1, min(parsed if parsed is not None else 100, 10_000))


def _browse(on_pick: Callable[[Path], Any]) -> None:
    """A directory-navigating dialog; picking a CSV calls ``on_pick``."""
    from nicegui import background_tasks, ui

    cwd = {"path": Path.cwd()}
    with ui.dialog() as dialog, ui.card().classes("w-[32rem]"):
        header = ui.label("").classes("text-sm font-mono opacity-70")
        listing = ui.column().classes("w-full gap-0 max-h-96 overflow-auto")

        async def show() -> None:
            from ..filebrowser import list_dir as _ld

            # scandir issues one getattr per entry -- on NFS that is one
            # round-trip per file, so the scan belongs off the event loop.
            started = time.monotonic()
            try:
                result = await offload(_ld, cwd["path"])
            except NotADirectoryError:
                # The cwd was removed or replaced by a file: fall back to the
                # launch directory rather than leaving a stale listing.
                result = await offload(_ld, Path.cwd())
                cwd["path"] = Path.cwd()
            except OSError as exc:
                # A PermissionError, an NFS ESTALE, a vanished mount: none of
                # these should kill the task. Say so inline and keep showing the
                # previous listing, so the dialog reads as "that directory is
                # unavailable" rather than frozen.
                debug_log("list_dir(%s) failed: %s", cwd["path"], exc)
                header.text = f"{cwd['path']} — {exc}"
                return
            debug_log(
                "list_dir(%s) %d entr%s %.0fms",
                result.cwd,
                len(result.entries),
                "y" if len(result.entries) == 1 else "ies",
                (time.monotonic() - started) * 1000,
            )
            header.text = str(result.cwd)
            listing.clear()
            with listing:
                if result.parent is not None:
                    ui.button("⬆ up", on_click=lambda: go(result.parent)).props(  # ty: ignore[invalid-argument-type]
                        "flat dense align=left"
                    ).classes("w-full")
                for entry in result.entries:
                    if entry.is_dir:
                        ui.button(
                            f"📁 {entry.name}", on_click=lambda _, p=entry.path: go(p)
                        ).props("flat dense align=left").classes("w-full")
                    else:
                        ui.button(
                            f"📄 {entry.name}", on_click=lambda _, p=entry.path: pick(p)
                        ).props("flat dense align=left").classes("w-full")

        async def go(path: Path) -> None:
            cwd["path"] = path
            await show()

        async def pick(path: Path) -> None:
            dialog.close()
            picked = on_pick(path)
            if inspect.isawaitable(picked):
                await picked

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
        # Fire the initial listing through the same await-aware shim as the
        # preview body: `show` is async, the dialog builder is not.
        result = show()
        if inspect.isawaitable(result):
            background_tasks.create(result, name="file browser listing")
    _discard_when_hidden(dialog)
    dialog.open()
