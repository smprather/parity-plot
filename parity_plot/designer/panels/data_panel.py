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

_NONE = "— none —"


def column_options(files: tuple[Path, ...]) -> dict[str, list[str]]:
    """Dropdown options per role.

    ``ref``/``test`` are numeric ``file:column`` (they are the plotted axes);
    ``group`` is any ``file:column``; ``join`` is a bare column name present in
    every open file, since the key has to exist on both sides to join. An
    unreadable file yields empty options rather than raising -- the panel must
    still render so a different file can be chosen.
    """
    empty = {"ref": [], "test": [], "group": [], "join": []}
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
    return {
        "ref": numeric,
        "test": list(numeric),
        "group": src.columns(),
        "join": common,
    }


def build_data_panel(state: DesignerState, on_change: Callable[[], None]) -> None:
    """The open-file list, an Open-file browser, and the ref/test/join/group maps."""
    from nicegui import ui

    with ui.expansion("Data", value=True).classes("w-full"):
        files = list(state.config.data.files)
        options = column_options(tuple(files))

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
                            icon="close",
                            on_click=lambda _, p=f: _remove(p),
                        ).props("flat dense round size=sm")

        ref_sel = ui.select(options["ref"], value=state.config.data.ref, label="Reference").classes("w-full")
        test_sel = ui.select(options["test"], value=state.config.data.test, label="Test").classes("w-full")
        join_sel = ui.select(
            [_NONE, *options["join"]],
            value=state.config.data.join or _NONE,
            label="Join column (blank = pair by order)",
        ).classes("w-full")
        group_sel = ui.select(
            [_NONE, *options["group"]],
            value=state.config.data.group or _NONE,
            label="Group by",
        ).classes("w-full")

        def refresh_options() -> None:
            opts = column_options(tuple(files))
            ref_sel.options, test_sel.options = opts["ref"], opts["test"]
            join_sel.options = [_NONE, *opts["join"]]
            group_sel.options = [_NONE, *opts["group"]]
            # Guess ref/test if unset and two numeric columns are available.
            if not ref_sel.value and len(opts["ref"]) >= 1:
                ref_sel.value = opts["ref"][0]
            if not test_sel.value and len(opts["test"]) >= 2:
                test_sel.value = opts["test"][1]
            for s in (ref_sel, test_sel, join_sel, group_sel):
                s.update()

        def apply() -> None:
            ok = state.set_data_source(
                files=tuple(files),
                ref=ref_sel.value or None,
                test=test_sel.value or None,
                join=None if join_sel.value == _NONE else join_sel.value,
                group=None if group_sel.value == _NONE else group_sel.value,
            )
            if not ok and state.last_error:
                ui.notify(state.last_error, type="negative")
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
        with ui.row().classes("w-full gap-2"):
            ui.button("Open file…", icon="folder_open",
                      on_click=lambda: _browse(_add)).props("flat")
            ui.button("Apply", on_click=apply)


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
                    ui.button("⬆ up", on_click=lambda: go(result.parent)).props("flat dense align=left").classes("w-full")
                for entry in result.entries:
                    if entry.is_dir:
                        ui.button(f"📁 {entry.name}", on_click=lambda _, p=entry.path: go(p)).props("flat dense align=left").classes("w-full")
                    else:
                        ui.button(f"📄 {entry.name}", on_click=lambda _, p=entry.path: pick(p)).props("flat dense align=left").classes("w-full")

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
