# parity_plot/designer/panels/controls.py
"""The settings panel.

`CONTROL_SPECS` is declarative data describing every control, so the set of
controls can be tested against the config dataclasses without a browser. A
setting with no control here is a setting the designer cannot reach, which
would make the saved config differ from what was on screen -- hence the test
that walks the dataclass fields.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable

from ...config import (
    LEGEND_POSITIONS,
    NULL_MODES,
    OUTPUT_FORMATS,
    PLOTLYJS_MODES,
    THEMES,
    OutputConfig,
    PlotConfig,
    StatsConfig,
)
from ...data import ParityData
from ..state import DesignerState
from .section import section


@dataclass(frozen=True)
class ControlSpec:
    section: str
    key: str
    label: str
    kind: str  # "text" | "number" | "switch" | "choice"
    help: str
    choices: tuple[str, ...] = ()
    group: str = "Appearance"


CONTROL_SPECS: tuple[ControlSpec, ...] = (
    # --- Appearance -------------------------------------------------------
    ControlSpec("plot", "title", "Title", "text", "Plot title."),
    ControlSpec("plot", "x_label", "X label", "text", "Defaults to the column name."),
    ControlSpec("plot", "y_label", "Y label", "text", "Defaults to the column name."),
    ControlSpec("plot", "theme", "Theme", "choice", "Colour theme.", THEMES),
    ControlSpec(
        "plot", "legend", "Legend", "choice", "Where the legend sits.", LEGEND_POSITIONS
    ),
    ControlSpec(
        "plot",
        "nulls",
        "Unpaired records",
        "choice",
        "Rug ticks, or hidden.",
        NULL_MODES,
    ),
    ControlSpec("plot", "log", "Log axes", "switch", "Logarithmic x and y."),
    ControlSpec(
        "plot",
        "equal_axes",
        "Lock 45°",
        "switch",
        "Share one range and a 1:1 pixel scale.",
    ),
    ControlSpec(
        "plot",
        "delta_histogram",
        "Delta histogram",
        "switch",
        "Add a lower histogram of paired differences.",
    ),
    # --- Statistics -------------------------------------------------------
    ControlSpec(
        "stats",
        "show",
        "Show statistics",
        "switch",
        "Display the metrics box.",
        group="Statistics",
    ),
    ControlSpec(
        "stats",
        "metrics",
        "Metrics",
        "text",
        "Comma-separated: n, r2, rmse, mae, bias.",
        group="Statistics",
    ),
    # --- Output -----------------------------------------------------------
    ControlSpec(
        "output",
        "path",
        "Output file",
        "text",
        "Where `plot` writes to.",
        group="Output",
    ),
    ControlSpec(
        "output",
        "format",
        "Format",
        "choice",
        "html needs nothing; the rest need kaleido.",
        OUTPUT_FORMATS,
        group="Output",
    ),
    ControlSpec(
        "output",
        "plotlyjs",
        "plotly.js in HTML",
        "choice",
        "inline is self-contained and works offline; cdn is small but needs "
        "a network; directory shares one file per folder.",
        PLOTLYJS_MODES,
        group="Output",
    ),
    ControlSpec(
        "output",
        "embed",
        "Embed fragment",
        "switch",
        "Write a bare div + script instead of a whole page, for embedding "
        "several plots in one app. Ignores width/height -- the container sizes it.",
        group="Output",
    ),
    ControlSpec(
        "output",
        "div_id",
        "Fragment div id",
        "text",
        "Container id for an embedded fragment; pin it so cached output does "
        "not churn on a random UUID.",
        group="Output",
    ),
    ControlSpec(
        "output", "width", "Width", "number", "Figure width in pixels.", group="Output"
    ),
    ControlSpec(
        "output",
        "height",
        "Height",
        "number",
        "Figure height in pixels.",
        group="Output",
    ),
)

GROUPS = ("Appearance", "Statistics", "Output")

_SECTION_CLASS = {"plot": PlotConfig, "stats": StatsConfig, "output": OutputConfig}


def _placeholder(spec: ControlSpec, data: ParityData | None) -> str:
    """The dimmed default shown in an empty text control.

    x_label / y_label resolve to the actual column name (from the loaded data),
    so an emptied label visibly falls back to it. Other fields show their
    dataclass default when it is a meaningful non-empty value (title ->
    "Parity Plot"); an all-None default shows nothing.
    """
    if spec.key in ("x_label", "y_label"):
        if data is None:
            return "column name"
        return data.x_label if spec.key == "x_label" else data.y_label
    cls = _SECTION_CLASS.get(spec.section)
    if cls is not None:
        for f in dataclasses.fields(cls):
            if f.name == spec.key and f.default is not dataclasses.MISSING:
                if f.default not in (None, ""):
                    return str(f.default)
    return ""


def build_controls(state: DesignerState, on_change: Callable[[], None]) -> None:
    """Render every control, grouped, wired straight into ``state``."""
    for group in GROUPS:
        specs = [s for s in CONTROL_SPECS if s.group == group]
        if not specs:
            continue
        with section(group):
            for spec in specs:
                _build_one(state, spec, on_change)


def _build_one(
    state: DesignerState, spec: ControlSpec, on_change: Callable[[], None]
) -> None:
    from nicegui import ui

    current = getattr(getattr(state.config, spec.section), spec.key)

    def apply(value: Any) -> None:
        cleaned = _clean(spec, value)
        if cleaned is None:
            # Blank means "revert to default" -- merge drops None, so route
            # through reset_fields, which actually clears the field.
            state.reset_fields(spec.section, spec.key)
        else:
            state.update(spec.section, **{spec.key: cleaned})
        on_change()

    if spec.kind == "switch":
        ui.switch(
            spec.label, value=bool(current), on_change=lambda e: apply(e.value)
        ).tooltip(spec.help)
    elif spec.kind == "choice":
        ui.select(
            list(spec.choices),
            value=current,
            label=spec.label,
            on_change=lambda e: apply(e.value),
        ).classes("w-full").tooltip(spec.help)
    elif spec.kind == "number":
        ui.number(
            spec.label, value=current, on_change=lambda e: apply(e.value)
        ).classes("w-full").tooltip(spec.help)
    else:
        ui.input(
            spec.label,
            value=_as_text(current),
            placeholder=_placeholder(spec, state.data),
            on_change=lambda e: apply(e.value),
        ).classes("w-full").tooltip(spec.help)


def _clean(spec: ControlSpec, value: Any) -> Any:
    """Turn a widget value into something ParityConfig.merge accepts.

    Blank text means "unset", which merge reads as None and therefore skips --
    so an emptied field falls back to the config default rather than erroring.
    """
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if spec.key == "metrics":
            return tuple(part.strip() for part in value.split(",") if part.strip())
    return value


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (tuple, list)):
        return ", ".join(str(v) for v in value)
    return str(value)
