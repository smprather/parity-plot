"""The encoding panel: what drives marker colour and symbol.

Two independent channels. Each is `single | pass-fail | group`; when a channel
is `single`, a contextual picker chooses the fixed colour token / symbol name.
The pass-fail and group choices need no extra input -- their values come from the
verdict and the group column.
"""

from __future__ import annotations

from typing import Callable

from ...encoding import CHANNELS, SYMBOL_CATALOG, Encoding
from ...themes import COLOR_TOKENS
from ..state import DesignerState

_CHANNEL_LABELS = {"single": "one value", "pass-fail": "pass / fail", "group": "group"}


def build_encoding_panel(state: DesignerState, on_change: Callable[[], None]) -> None:
    """Colour and symbol channel selects, each with a contextual picker."""
    from nicegui import ui

    enc = state.config.plot.encoding

    with ui.expansion("Encoding", value=False).classes("w-full"):

        def commit() -> None:
            new = Encoding(
                color_by=color_by.value,
                symbol_by=symbol_by.value,
                color=color_pick.value or "blue",
                symbol=symbol_pick.value or "circle",
                symbol_sequence=tuple(seq_pick.value or ()),
            )
            # A rejected update leaves state.last_error; the status bar shows it.
            state.update("plot", encoding=new)
            on_change()

        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.label("Colour by").classes("w-24 text-sm")
            color_by = ui.select(
                {c: _CHANNEL_LABELS[c] for c in CHANNELS}, value=enc.color_by,
                on_change=lambda: commit(),
            ).classes("grow")
            color_pick = ui.select(
                list(COLOR_TOKENS), value=enc.color, on_change=lambda: commit(),
            ).classes("w-28")
            # The fixed colour only matters when the channel is "single".
            color_pick.bind_visibility_from(color_by, "value", value="single")

        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.label("Symbol by").classes("w-24 text-sm")
            symbol_by = ui.select(
                {c: _CHANNEL_LABELS[c] for c in CHANNELS}, value=enc.symbol_by,
                on_change=lambda: commit(),
            ).classes("grow")
            symbol_pick = ui.select(
                list(SYMBOL_CATALOG), value=enc.symbol, on_change=lambda: commit(),
            ).classes("w-28")
            symbol_pick.bind_visibility_from(symbol_by, "value", value="single")

        # The per-group symbol cycle. Only meaningful when symbol_by = "group";
        # an empty selection falls back to the built-in default cycle.
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.label("Symbols").classes("w-24 text-sm")
            seq_pick = ui.select(
                list(SYMBOL_CATALOG),
                value=list(enc.symbol_sequence),
                multiple=True,
                label="cycle for groups (blank = default)",
                on_change=lambda: commit(),
            ).classes("grow").props("use-chips")
            seq_pick.bind_visibility_from(symbol_by, "value", value="group")

        ui.label(
            "pass/fail colours a point by its verdict; group uses the group column."
        ).classes("text-xs opacity-60")
