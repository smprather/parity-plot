"""Designer controls for polynomial reference lines."""

from __future__ import annotations

from typing import Callable

from ...polynomial_lines import LINE_STYLES, PolynomialLine, PolynomialLineError
from ...themes import COLOR_TOKENS
from ..state import DesignerState
from .section import section


def build_polynomial_lines_panel(
    state: DesignerState, on_change: Callable[[], None]
) -> None:
    """Render repeatable add/edit/delete controls for polynomial lines."""
    from nicegui import ui

    with section("Reference lines"):
        container = ui.column().classes("w-full gap-1")

        def current() -> tuple[PolynomialLine, ...]:
            return state.config.plot.polynomial_lines

        def commit(lines: tuple[PolynomialLine, ...]) -> None:
            state.update("plot", polynomial_lines=lines)
            render()
            on_change()

        def render() -> None:
            container.clear()
            with container:
                for index, polynomial in enumerate(current()):
                    _row(index, polynomial)
                ui.button(
                    "Add reference line",
                    icon="add",
                    on_click=lambda: _open_editor(None, None),
                ).props("flat dense")

        def _row(index: int, polynomial: PolynomialLine) -> None:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                _swatch(polynomial)
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(polynomial.equation).classes(
                        "text-sm font-medium leading-tight break-all"
                    )
                    ui.label(f"{polynomial.color} | {polynomial.style}").classes(
                        "text-xs opacity-60 leading-tight"
                    )
                ui.button(
                    icon="edit",
                    on_click=lambda _, i=index, p=polynomial: _open_editor(i, p),
                ).props("flat dense round size=sm").tooltip("Edit reference line")
                ui.button(
                    icon="delete",
                    on_click=lambda _, i=index: commit(
                        current()[:i] + current()[i + 1 :]
                    ),
                ).props("flat dense round size=sm color=negative").tooltip(
                    "Delete reference line"
                )

        def _swatch(polynomial: PolynomialLine) -> None:
            from ...themes import get as get_theme

            colour = get_theme(state.config.plot.theme).resolve_color(polynomial.color)
            border_style = {
                "solid": "solid",
                "dashed": "dashed",
                "dotted": "dotted",
            }[polynomial.style]
            ui.element("div").style(
                f"width:22px;height:0;border-top:2px {border_style} {colour}"
            )

        def _open_editor(index: int | None, polynomial: PolynomialLine | None) -> None:
            initial = polynomial or PolynomialLine((1.0, 0.0))
            color_options = list(COLOR_TOKENS)
            if initial.color.startswith("#"):
                color_options.append(initial.color)
            with ui.dialog() as dialog, ui.card().classes("w-96 gap-2"):
                ui.label(
                    "Edit reference line" if polynomial else "Add reference line"
                ).classes("text-base font-medium")
                coefficients_in = ui.input(
                    "Coefficients",
                    value=initial.coefficients_csv,
                ).classes("w-full")
                with ui.row().classes("w-full gap-2 no-wrap"):
                    color_sel = ui.select(
                        color_options, value=initial.color, label="Color"
                    ).classes("grow")
                    style_sel = ui.select(
                        list(LINE_STYLES), value=initial.style, label="Line style"
                    ).classes("grow")
                error = ui.label("").classes("text-red-400 text-xs")

                def save() -> None:
                    try:
                        edited = PolynomialLine.from_csv(
                            coefficients_in.value or "",
                            color=color_sel.value or "",
                            style=style_sel.value or "",
                        )
                    except PolynomialLineError as exc:
                        error.text = str(exc)
                        return
                    lines = current()
                    updated = (
                        (*lines, edited)
                        if index is None
                        else (
                            *lines[:index],
                            edited,
                            *lines[index + 1 :],
                        )
                    )
                    dialog.close()
                    commit(updated)

                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancel", on_click=dialog.close).props("flat")
                    ui.button("Save", on_click=save)
            dialog.open()

        render()
