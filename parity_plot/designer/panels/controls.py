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
        "Keep y = x at 45° with a 1:1 pixel scale.",
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
VIEWPORT_ORIGIN_FIELDS = frozenset({"x_origin", "y_origin"})
VIEWPORT_ORIGIN_METHODS = ("Auto", "0,0", "Custom")
VIEWPORT_ORIGIN_FORMAT = "%.12g"

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
                if group == "Appearance" and spec.key == "y_label":
                    _build_viewport_origin(state, on_change)


def viewport_origin_method(plot: PlotConfig) -> str:
    """Return the designer method represented by a stored plot config."""
    if plot.x_origin is None and plot.y_origin is None:
        return "Auto"
    if plot.x_origin == 0.0 and plot.y_origin == 0.0:
        return "0,0"
    return "Custom"


def current_viewport_origins(state: DesignerState) -> tuple[float, float]:
    """Return the lower axis bounds currently used by the rendered plot.

    Plotly stores logarithmic axis ranges as base-10 exponents. Designer inputs
    always use data units, matching the TOML config.
    """
    figure = state.figure()
    x = float(figure.layout.xaxis.range[0])
    y = float(figure.layout.yaxis.range[0])
    if state.config.plot.log:
        return 10**x, 10**y
    return x, y


def apply_viewport_origin_method(
    state: DesignerState,
    method: str,
    custom_x: float | None = None,
    custom_y: float | None = None,
) -> bool:
    """Apply one viewport-origin method to the persisted config fields."""
    if method == "Auto":
        state.reset_fields("plot", *VIEWPORT_ORIGIN_FIELDS)
        return True
    if method == "0,0":
        return state.update("plot", x_origin=0.0, y_origin=0.0)
    if method == "Custom":
        if custom_x is None or custom_y is None:
            state.last_error = "Custom viewport origin requires both X and Y values."
            return False
        return state.update("plot", x_origin=custom_x, y_origin=custom_y)
    raise ValueError(f"unknown viewport origin method {method!r}")


def _build_viewport_origin(state: DesignerState, on_change: Callable[[], None]) -> None:
    """Render method first, then one horizontal row of custom X/Y values."""
    from nicegui import ui

    initial_method = viewport_origin_method(state.config.plot)
    initial_x, initial_y = current_viewport_origins(state)

    ui.label("Viewport Origin").classes("text-base font-medium mt-2")
    ui.label("Method").classes("text-sm opacity-70")

    def sync_custom_fields() -> None:
        custom = method_control.value == "Custom"
        x_input.set_enabled(custom)
        y_input.set_enabled(custom)

    def choose_method(method: str) -> None:
        succeeded = apply_viewport_origin_method(
            state, method, x_input.value, y_input.value
        )
        if succeeded:
            if method == "Auto":
                x_input.value, y_input.value = current_viewport_origins(state)
            elif method == "0,0":
                x_input.value = y_input.value = 0.0
            x_input.update()
            y_input.update()
        else:
            method_control.value = viewport_origin_method(state.config.plot)
            method_control.update()
        sync_custom_fields()
        on_change()

    def apply_custom(axis: str, value: float | None) -> None:
        custom_x = value if axis == "x" else x_input.value
        custom_y = value if axis == "y" else y_input.value
        apply_viewport_origin_method(state, "Custom", custom_x, custom_y)
        on_change()

    method_control = (
        ui.radio(
            list(VIEWPORT_ORIGIN_METHODS),
            value=initial_method,
            on_change=lambda e: choose_method(e.value),
        )
        .props('inline aria-label="Method"')
        .classes("w-full viewport-origin-method")
    )
    with ui.row().classes("w-full no-wrap gap-2 items-start viewport-origin-custom"):
        x_input = (
            ui.number(
                "Custom X",
                value=initial_x,
                format=VIEWPORT_ORIGIN_FORMAT,
                on_change=lambda e: apply_custom("x", e.value),
            )
            .classes("grow basis-0 min-w-0")
            .tooltip("Left edge in data units.")
        )
        y_input = (
            ui.number(
                "Custom Y",
                value=initial_y,
                format=VIEWPORT_ORIGIN_FORMAT,
                on_change=lambda e: apply_custom("y", e.value),
            )
            .classes("grow basis-0 min-w-0")
            .tooltip("Bottom edge in data units.")
        )
    sync_custom_fields()


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
