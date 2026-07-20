"""The tolerance list panel: add, edit, delete, enable.

Thin over `tolerance_ops`. Every edit rebuilds the whole list and pushes it
through `state.update("plot", tolerances=...)`, so the config on screen and the
config that saves cannot disagree -- the same discipline as the rest of the
designer.

The parity entry is special: it leads the list, cannot be deleted, and its
name, kind and bounds are locked in the editor. Everything else about it --
colour, style, whether it is drawn, whether it is in the legend -- is editable,
because those are presentation.
"""

from __future__ import annotations

from typing import Callable

from ...tolerances import (
    KINDS,
    PARITY_NAME,
    STYLES,
    NamedTolerance,
)
from ...themes import COLOR_TOKENS
from .. import tolerance_ops as ops
from ..state import DesignerState


def build_tolerances_panel(state: DesignerState, on_change: Callable[[], None]) -> None:
    """Render the tolerance list and the controls that edit it."""
    from nicegui import ui

    with ui.expansion("Tolerances", value=True).classes("w-full"):
        container = ui.column().classes("w-full gap-1")

        def current() -> tuple[NamedTolerance, ...]:
            return state.config.plot.tolerances

        def commit(tolerances) -> None:
            """Push a new list into state and redraw the whole panel."""
            if not state.update("plot", tolerances=ops.normalise(tolerances)):
                ui.notify(state.last_error, type="negative")
            render()
            on_change()

        def render() -> None:
            container.clear()
            with container:
                for tol in current():
                    _row(tol)
                ui.button("Add tolerance", icon="add",
                          on_click=lambda: commit(ops.add(current()))).props("flat dense")

        def _row(tol: NamedTolerance) -> None:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.checkbox(
                    value=tol.enabled,
                    on_change=lambda e, n=tol.name: commit(ops.set_enabled(current(), n, e.value)),
                ).props("dense").tooltip("Draw this tolerance")

                _swatch(tol)

                with ui.column().classes("gap-0 grow"):
                    ui.label(tol.name).classes("text-sm font-medium leading-tight")
                    ui.label(f"{tol.display_label} · {tol.kind}").classes(
                        "text-xs opacity-60 leading-tight"
                    )

                ui.button(icon="edit", on_click=lambda _, t=tol: _open_editor(t)).props(
                    "flat dense round size=sm"
                )
                if tol.name != PARITY_NAME:
                    ui.button(
                        icon="delete",
                        on_click=lambda _, n=tol.name: commit(ops.delete(current(), n)),
                    ).props("flat dense round size=sm color=negative")

        def _swatch(tol: NamedTolerance) -> None:
            from ...themes import get as get_theme

            colour = get_theme(state.config.plot.theme).resolve_color(tol.color_token)
            style = f"width:14px;height:14px;border-radius:3px;background:{colour}"
            if not tol.enabled:
                style += ";opacity:0.3"
            ui.element("div").style(style)

        def _open_editor(tol: NamedTolerance) -> None:
            locked = tol.name == PARITY_NAME
            with ui.dialog() as dialog, ui.card().classes("w-96 gap-2"):
                ui.label(f"Edit {tol.name}").classes("text-base font-medium")

                name_in = ui.input("Name", value=tol.name).classes("w-full")
                if locked:
                    name_in.props("readonly")

                auto = tol.label in (None, "auto")
                label_mode = ui.toggle(
                    {"auto": "Auto label", "manual": "Manual label"},
                    value="auto" if auto else "manual",
                ).props("dense")
                # In auto mode the derived legend text is shown read-only, so the
                # user sees what "auto" will produce; in manual mode they type it.
                auto_preview = ui.label("").classes("text-sm opacity-70 italic")
                auto_preview.bind_visibility_from(label_mode, "value", value="auto")
                label_in = ui.input(
                    "Legend label",
                    value="" if auto else tol.label,
                ).classes("w-full")
                label_in.bind_visibility_from(label_mode, "value", value="manual")

                with ui.row().classes("w-full gap-2 no-wrap items-center"):
                    abstol_in = ui.number("abstol", value=tol.abstol, format="%.4g").classes("grow")
                    # Left to right: the reltol value, then the % checkbox, then a
                    # "%" label. Checked (default) the field is a percentage;
                    # unchecked it is a bare ratio. Toggling converts in place so
                    # the underlying value never changes just from flipping it.
                    reltol_in = ui.number(
                        "reltol", value=_reltol_display(tol, percent=True), format="%.4g"
                    ).classes("grow")
                    pct_in = ui.checkbox(value=True).props("dense").tooltip(
                        "Enter reltol as a percentage"
                    )
                    ui.label("%").classes("text-sm")

                    def _convert(e) -> None:
                        if reltol_in.value is None:
                            return
                        reltol_in.value = (
                            reltol_in.value * 100 if e.value else reltol_in.value / 100
                        )
                    pct_in.on_value_change(_convert)
                if locked:
                    abstol_in.props("readonly").tooltip("The parity line is a zero tolerance")
                    reltol_in.props("readonly")
                    pct_in.props("disable")

                kind_sel = ui.select(
                    {"pass": "pass-fail", "info": "info"}, value=tol.kind, label="Kind",
                ).classes("w-full")
                if locked:
                    kind_sel.props("readonly").tooltip("The parity line is informational")

                def _refresh_auto_preview() -> None:
                    """Show what an auto label would read, from the fields as they
                    stand -- so editing a bound updates the preview live."""
                    reltol = _reltol_from_field(reltol_in.value, pct_in.value)
                    abstol = float(abstol_in.value) if abstol_in.value not in (None, "") else None
                    auto_preview.text = _auto_label_preview(abstol, reltol)

                for widget in (abstol_in, reltol_in, pct_in):
                    widget.on_value_change(lambda _: _refresh_auto_preview())
                _refresh_auto_preview()

                with ui.row().classes("w-full gap-2 no-wrap"):
                    color_sel = ui.select(
                        list(COLOR_TOKENS), value=_color_value(tol), label="Colour",
                    ).classes("grow")
                    style_sel = ui.select(list(STYLES), value=tol.style, label="Draw as").classes("grow")
                if locked:
                    # Parity is a single zero-width line; lines-vs-shaded has
                    # nothing to fill between, so the choice is meaningless.
                    style_sel.props("readonly").tooltip("The parity line is always a line")

                legend_sw = ui.switch("Show in legend", value=tol.show_in_legend)

                error = ui.label("").classes("text-red-400 text-xs")

                def save() -> None:
                    reltol = _reltol_from_field(reltol_in.value, pct_in.value)
                    edited = _from_editor(
                        tol, locked, name_in.value, label_mode.value, label_in.value,
                        abstol_in.value, reltol, kind_sel.value,
                        color_sel.value, style_sel.value, legend_sw.value,
                    )
                    if isinstance(edited, str):  # an error message
                        error.text = edited
                        return
                    if not ops.rename_is_free(current(), tol.name, edited.name):
                        error.text = f"a tolerance named {edited.name!r} already exists"
                        return
                    dialog.close()
                    commit(ops.update(current(), tol.name, edited))

                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")
                    ui.button("Save", on_click=save)
            dialog.open()

        render()


def _auto_label_preview(abstol: float | None, reltol: float | None) -> str:
    """The legend text an auto label would produce for these bounds.

    Mirrors what the plot will draw, by asking the real Tolerance for its label;
    falls back to a hint when neither bound is set yet.
    """
    from ...tolerance import Tolerance

    if abstol is None and reltol is None:
        return "(set a bound to see the auto label)"
    return Tolerance(abstol=abstol, reltol=reltol).label()


def _reltol_display(tol: NamedTolerance, percent: bool) -> float | None:
    """The number to seed the reltol field with, in the field's current units."""
    if tol.reltol is None:
        return None
    return tol.reltol * 100 if percent else tol.reltol


def _reltol_from_field(value: float | None, percent: bool) -> float | None:
    """The stored ratio from what the field holds, given the % checkbox state."""
    if value in (None, ""):
        return None
    return float(value) / 100 if percent else float(value)


def _color_value(tol: NamedTolerance) -> str:
    token = tol.color_token
    return token if not token.startswith("#") else token


def _from_editor(
    original, locked, name, label_mode, label, abstol, reltol, kind, color, style, in_legend,
):
    """Assemble an edited NamedTolerance, or return an error string.

    ``reltol`` here is already a ratio or None -- the % conversion happened at
    the widget. Kept separate from the widgets so the assembly rules are one
    place; a locked entry keeps its name, bounds and kind no matter what the
    (read-only) fields hold, so a stray value cannot corrupt the parity line.
    """
    from dataclasses import replace

    from ...tolerances import ToleranceError

    if locked:
        # Name, bounds, kind and style are fixed for the parity line; only
        # colour, legend visibility and the label are the user's to change.
        return replace(
            original,
            color=color or None,
            show_in_legend=bool(in_legend),
            label=None if label_mode == "auto" else (label.strip() or None),
        )

    name = (name or "").strip()
    try:
        return NamedTolerance(
            name=name,
            abstol=float(abstol) if abstol not in (None, "") else None,
            reltol=reltol,
            kind=kind,
            color=color or None,
            style=style,
            show_in_legend=bool(in_legend),
            label=None if label_mode == "auto" else (label.strip() or None),
            enabled=original.enabled,
        )
    except ToleranceError as exc:
        return str(exc)
