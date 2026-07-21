# parity_plot/designer/panels/data_panel.py
"""Choosing the dataset and saying which column is which."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ...data import DataError
from ..datasets import peek, suggest_mapping
from ..state import DesignerState


def mapping_options(paths: tuple[Path, ...]) -> dict[str, list[str]]:
    """Column choices for each role, given the currently selected files.

    With two files the key must be present in both, or the join cannot run, so
    only their common columns are offered. An unreadable file yields no options
    rather than an exception -- the panel still has to render so the user can
    pick a different one.
    """
    empty = {"key": [], "x": [], "y": []}
    if not paths:
        return empty

    try:
        peeks = [peek(p) for p in paths]
    except DataError:
        return empty

    if len(peeks) == 1:
        columns = list(peeks[0].columns)
        return {"key": columns, "x": list(columns), "y": list(columns)}

    common = [c for c in peeks[0].columns if all(c in p.columns for p in peeks[1:])]
    return {
        "key": common,
        "x": list(peeks[0].columns),
        "y": list(peeks[1].columns),
    }


def _ref_col(data, fallback: str | None) -> str | None:
    """The ref column name from the `file:column` ref, or `fallback`."""
    if data.ref:
        return data.ref.rpartition(":")[2]
    return fallback


def _test_col(data, fallback: str | None) -> str | None:
    if data.test:
        return data.test.rpartition(":")[2]
    return fallback


def _qualified(files: tuple[Path, ...], column: str | None, which: int) -> str | None:
    """Build a `file:column` ref from a bare column name, or None."""
    if column is None or not files:
        return None
    f = files[min(which, len(files) - 1)]
    return f"{f.name}:{column}"


def build_data_panel(state: DesignerState, on_change: Callable[[], None]) -> None:
    """File paths plus the column mapping, applied together."""
    from nicegui import ui

    with ui.expansion("Data", value=False).classes("w-full"):
        paths_input = ui.input(
            "Paths",
            value=", ".join(str(p) for p in state.config.data.files),
        ).classes("w-full").tooltip(
            "One path for a wide file, or two to outer-join on the key column."
        )

        options = mapping_options(state.config.data.files)
        # The config stores `file:column` refs; the selects show bare column names.
        key_select = ui.select(
            options["key"], value=state.config.data.join, label="Key column"
        ).classes("w-full")
        x_select = ui.select(
            options["x"], value=_ref_col(state.config.data, None), label="Reference column"
        ).classes("w-full")
        y_select = ui.select(
            options["y"], value=_test_col(state.config.data, None), label="Measured column"
        ).classes("w-full")

        def parse_paths() -> tuple[Path, ...]:
            return tuple(
                Path(part.strip()) for part in paths_input.value.split(",") if part.strip()
            )

        def refresh_options() -> None:
            """Re-read the headers so the selects match the chosen files.

            Guessing a mapping means the plot appears immediately instead of
            waiting behind an empty form the user must fill in first.
            """
            paths = parse_paths()
            opts = mapping_options(paths)
            key_select.options, x_select.options, y_select.options = (
                opts["key"], opts["x"], opts["y"],
            )
            if paths:
                try:
                    guess = suggest_mapping(peek(paths[0]))
                except DataError:
                    guess = {}
                key_select.value = guess.get("key") or key_select.value
                x_select.value = guess.get("x") or x_select.value
                y_select.value = guess.get("y") or y_select.value
            for select in (key_select, x_select, y_select):
                select.update()

        def apply() -> None:
            files = parse_paths()
            ok = state.set_data_source(
                files=files,
                ref=_qualified(files, x_select.value, 0),
                test=_qualified(files, y_select.value, min(1, len(files) - 1)),
                join=key_select.value,
            )
            if not ok:
                ui.notify(state.last_error, type="negative")
            on_change()

        with ui.row():
            ui.button("Re-read columns", on_click=refresh_options).props("flat")
            ui.button("Load", on_click=apply)