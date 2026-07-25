"""Choosing the dataset: the open files, and which column is ref/test/join/group.

The designer can hold an arbitrary set of files; ref and test are picked as
`file:column` across all of them. ref/test are offered only from numeric columns
(they are the axes); join is a bare column name common to the files; group is any
`file:column`. Files are opened through a server-side browser dialog, so the
designer can start empty.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ...data import DataError
from ...sources import open_sources
from ..state import DesignerState
from .section import section

_NONE = "— none —"


def _column_of(ref: str | None) -> str | None:
    """The bare column name of a ``file:column`` ref, or None."""
    if not ref or ":" not in ref:
        return None
    return ref.split(":", 1)[1]


def column_options(
    files: tuple[Path, ...], ref: str | None = None, test: str | None = None
) -> dict[str, list[str]]:
    """Dropdown options per role.

    ``ref``/``test`` are numeric ``file:column`` (they are the plotted axes);
    ``group`` is any ``file:column``; ``join`` is a bare column name present in
    every open file, since the key has to exist on both sides to join. An
    unreadable file yields empty options rather than raising -- the panel must
    still render so a different file can be chosen.
    """
    empty = {"ref": [], "test": [], "group": [], "join": [], "color_column": []}
    if not files:
        return empty
    try:
        src = open_sources(files)
    except DataError:
        return empty

    numeric = src.numeric_columns()
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
    group = [c for c in distinct if c not in axis_columns]
    return {
        "ref": numeric,
        "test": list(numeric),
        "group": group,
        "join": common,
        "color_column": list(numeric),
    }


def build_data_panel(
    state: DesignerState, on_change: Callable[[], None]
) -> Callable[[list], None]:
    """The open-file list, an Add-file browser, and the ref/test/join/group maps.

    Returns a ``mark_problems(problems)`` hook so ``app.refresh`` can redden the
    exact widget a validation problem names -- today just the ``join`` select.
    """
    from nicegui import ui

    with section("Data"):
        files = list(state.config.data.files)
        options = column_options(
            tuple(files), state.config.data.ref, state.config.data.test
        )

        # Add File sits at the top of the section: choosing the data comes first.
        ui.button("Add File", icon="add", on_click=lambda: _browse(_add)).props("flat")

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
                        ui.button(
                            icon="close",
                            on_click=lambda _, p=f: _remove(p),
                        ).props("flat dense round size=sm")

        ref_sel = ui.select(
            options["ref"],
            value=state.config.data.ref,
            label="Reference",
            on_change=lambda: (refresh_group(), apply()),
        ).classes("w-full")
        test_sel = ui.select(
            options["test"],
            value=state.config.data.test,
            label="Test",
            on_change=lambda: (refresh_group(), apply()),
        ).classes("w-full")
        join_sel = ui.select(
            [_NONE, *options["join"]],
            value=state.config.data.join or _NONE,
            label="Join column (blank = pair by order)",
            on_change=lambda: apply(),
        ).classes("w-full")
        group_sel = (
            ui.select(
                options["group"],
                value=list(state.config.data.group),
                multiple=True,
                label="Group by (one or more columns)",
                on_change=lambda: apply(),
            )
            .classes("w-full")
            .props("use-chips")
        )
        color_sel = ui.select(
            [_NONE, *options["color_column"]],
            value=state.config.data.color_column or _NONE,
            label="Colour column (numeric, for colorscale)",
            on_change=lambda: apply(),
        ).classes("w-full")

        # Guard so the programmatic ref/test guessing in refresh_options does not
        # re-enter apply() through the selects' on_change.
        _suspend = {"v": False}

        def refresh_options() -> None:
            opts = column_options(tuple(files), ref_sel.value, test_sel.value)
            ref_sel.options, test_sel.options = opts["ref"], opts["test"]
            join_sel.options = [_NONE, *opts["join"]]
            group_sel.options = opts["group"]
            color_sel.options = [_NONE, *opts["color_column"]]
            _suspend["v"] = True
            # Guess ref/test if unset and two numeric columns are available.
            if not ref_sel.value and len(opts["ref"]) >= 1:
                ref_sel.value = opts["ref"][0]
            if not test_sel.value and len(opts["test"]) >= 2:
                test_sel.value = opts["test"][1]
            _suspend["v"] = False
            for s in (ref_sel, test_sel, join_sel, group_sel, color_sel):
                s.update()

        def refresh_group() -> None:
            opts = column_options(tuple(files), ref_sel.value, test_sel.value)
            group_sel.options = opts["group"]
            group_sel.update()

        def apply() -> None:
            if _suspend["v"]:
                return
            state.set_data_source(
                files=tuple(files),
                ref=ref_sel.value or None,
                test=test_sel.value or None,
                join=None if join_sel.value == _NONE else join_sel.value,
                group=tuple(group_sel.value or ()),
                color_column=None if color_sel.value == _NONE else color_sel.value,
            )
            # On failure last_error is set; the status bar (painted by
            # on_change -> refresh) shows it persistently -- no toast.
            on_change()

        def _remove(path: Path) -> None:
            files.remove(path)
            render_files()
            refresh_options()
            apply()

        def _add(path: Path) -> None:
            if path not in files:
                files.append(path)
            render_files()
            refresh_options()
            apply()

        render_files()

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
    from nicegui import ui

    from ...data import DataError
    from ..datasets import preview

    # A larger, bolder header row. Scoped by .peek-grid; added to the page head
    # (ui.add_css applies where an inline <style> element does not).
    ui.add_css(".peek-grid .ag-header-cell-text { font-size: 15px; font-weight: 700; }")

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
        def body() -> None:
            limit = max(1, min(int(rows_input.value or 100), 10000))
            try:
                data = preview(path, limit=limit)
            except DataError as exc:
                ui.label(str(exc)).classes("text-red-400 text-sm")
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
                return float(text) if text else None

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

        body()

    dialog.open()


def _browse(on_pick: Callable[[Path], None]) -> None:
    """A directory-navigating dialog; picking a CSV calls ``on_pick``."""
    from nicegui import ui

    cwd = {"path": Path.cwd()}
    with ui.dialog() as dialog, ui.card().classes("w-[32rem]"):
        header = ui.label("").classes("text-sm font-mono opacity-70")
        listing = ui.column().classes("w-full gap-0 max-h-96 overflow-auto")

        def show() -> None:
            from ..filebrowser import list_dir as _ld

            try:
                result = _ld(cwd["path"])
            except NotADirectoryError:
                result = _ld(Path.cwd())
                cwd["path"] = Path.cwd()
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

        def go(path: Path) -> None:
            cwd["path"] = path
            show()

        def pick(path: Path) -> None:
            dialog.close()
            on_pick(path)

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
        show()
    dialog.open()
