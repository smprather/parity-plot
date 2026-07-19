"""Figure construction.

The defining property of a parity plot is that ``y = x`` runs at a true 45
degrees. That requires two things together: a single range shared by both axes,
and ``scaleanchor`` locking their pixel scales. Either one alone lets the
identity line drift off the diagonal, so both are asserted in the tests.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import replace
from pathlib import Path

import plotly.graph_objects as go

from . import stats as stats_mod
from . import themes
from .config import OutputConfig, PlotConfig, StatsConfig
from .data import ParityData, Unpaired
from .tolerance import Tolerance

# Above this many points, WebGL rendering keeps the figure interactive.
_WEBGL_THRESHOLD = 5_000

# Each legend position needs its own margins: a right-hand legend needs width,
# a bottom one needs height. Leaving a single margin set for both either clips
# the legend or strands the plot in whitespace.
_LEGEND_LAYOUTS = {
    # Vertically centred rather than top-aligned: `constrain="domain"` shrinks
    # the drawn axes inside the specified domain, so a legend pinned to the top
    # of that domain floats above the visible frame.
    "right": (
        dict(orientation="v", x=1.02, xanchor="left", y=0.5, yanchor="middle"),
        dict(l=80, r=210, t=100, b=80),
    ),
    "bottom": (
        dict(orientation="h", x=0.5, xanchor="center", y=-0.09, yanchor="top"),
        dict(l=80, r=50, t=100, b=120),
    ),
    "none": (None, dict(l=80, r=50, t=100, b=80)),
}


def build_figure(
    data: ParityData,
    plot: PlotConfig | None = None,
    stats_cfg: StatsConfig | None = None,
) -> go.Figure:
    plot = plot or PlotConfig()
    stats_cfg = stats_cfg or StatsConfig()
    theme = themes.get(plot.theme)

    if plot.log:
        data = _drop_non_positive(data)

    tol = Tolerance(abstol=plot.abstol, reltol=plot.reltol)
    summary = stats_mod.compute(data, tol)
    lo, hi = _axis_range(data, log=plot.log)

    fig = go.Figure()
    if tol:
        _add_tolerance(fig, tol, lo, hi, plot.log, plot.band_style, theme)
    if plot.identity_line:
        _add_identity(fig, lo, hi, plot.log, theme)
    _add_paired(fig, data, theme)
    if plot.nulls == "rug":
        _add_rugs(fig, data, lo, hi, plot.log, theme)

    _apply_layout(fig, data, plot, theme, summary, lo, hi)
    if stats_cfg.show:
        _add_stats_box(fig, summary, stats_cfg.metrics, theme, lo, hi)
    return fig


def _drop_non_positive(data: ParityData) -> ParityData:
    """Remove values a log axis cannot show, reporting how many were lost."""
    paired = [
        (k, xi, yi)
        for k, xi, yi in zip(data.keys, data.x, data.y)
        if xi > 0 and yi > 0
    ]
    missing_y = _filter_unpaired(data.missing_y)
    missing_x = _filter_unpaired(data.missing_x)

    removed = (
        (data.n_paired - len(paired))
        + (len(data.missing_y) - len(missing_y))
        + (len(data.missing_x) - len(missing_x))
    )
    if removed:
        warnings.warn(
            f"log scale: dropped {removed} value(s) that were zero or negative",
            stacklevel=3,
        )

    return replace(
        data,
        keys=[k for k, _, _ in paired],
        x=[xi for _, xi, _ in paired],
        y=[yi for _, _, yi in paired],
        missing_y=missing_y,
        missing_x=missing_x,
    )


def _filter_unpaired(unpaired: Unpaired) -> Unpaired:
    kept = [(k, v) for k, v in zip(unpaired.keys, unpaired.values) if v > 0]
    return Unpaired([k for k, _ in kept], [v for _, v in kept])


def _axis_range(data: ParityData, log: bool) -> tuple[float, float]:
    """Compute the range shared by both axes, padded by 5%.

    Unpaired values participate, otherwise a rug mark could sit outside the
    plotted area and vanish.
    """
    values = data.all_values()
    if not values:
        return (0.0, 1.0)

    lo, hi = min(values), max(values)
    if log:
        lo_l, hi_l = math.log10(lo), math.log10(hi)
        pad = (hi_l - lo_l) * 0.05 or 0.5
        return (lo_l - pad, hi_l + pad)

    pad = (hi - lo) * 0.05 or (abs(hi) * 0.05 or 0.5)
    return (lo - pad, hi + pad)


def _rug_baseline(lo: float, hi: float, log: bool) -> float:
    """Where the rug ticks sit: on zero when zero is visible.

    A log axis cannot show zero, and data that never approaches zero would put
    the ticks off-plot, so both fall back to the axis floor.
    """
    if not log and lo <= 0.0 <= hi:
        return 0.0
    return 10**lo if log else lo


def _line_endpoints(lo: float, hi: float, log: bool) -> list[float]:
    """Endpoints in data space; on a log axis the range is in exponents."""
    return [10**lo, 10**hi] if log else [lo, hi]


def _add_identity(
    fig: go.Figure, lo: float, hi: float, log: bool, theme: themes.Theme
) -> None:
    """The zero-error reference: solid, so it reads as exact agreement."""
    ends = _line_endpoints(lo, hi, log)
    fig.add_trace(
        go.Scatter(
            x=ends,
            y=ends,
            mode="lines",
            name="0% error (y = x)",
            line=dict(color=theme.identity, width=2),
            hoverinfo="skip",
        )
    )


def _add_tolerance(
    fig: go.Figure,
    tol: Tolerance,
    lo: float,
    hi: float,
    log: bool,
    band_style: str,
    theme: themes.Theme,
) -> None:
    """Draw the tolerance envelope as a pair of limit lines.

    Straight segments in linear space curve on a log axis, so the log case is
    sampled densely rather than drawn vertex to vertex.
    """
    if band_style not in ("lines", "shaded"):
        raise ValueError(
            f"unknown band style {band_style!r}; expected 'lines' or 'shaded'"
        )

    if log:
        xs, upper, lower = tol.log_envelope(lo, hi)
    else:
        xs, upper, lower = tol.envelope(lo, hi)
    if not xs:
        return

    label = tol.label()
    shaded = band_style == "shaded"
    line = dict(color=theme.tolerance, width=1.6)

    # The lower limit is drawn first so the shaded variant can fill up to it.
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=lower,
            mode="lines",
            name=label,
            legendgroup="tolerance",
            line=dict(width=0) if shaded else line,
            showlegend=not shaded,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=upper,
            mode="lines",
            name=label,
            legendgroup="tolerance",
            line=dict(width=0) if shaded else line,
            fill="tonexty" if shaded else None,
            fillcolor=theme.band_fill if shaded else None,
            showlegend=shaded,
            hoverinfo="skip",
        )
    )


def _add_paired(fig: go.Figure, data: ParityData, theme: themes.Theme) -> None:
    scatter = go.Scattergl if data.n_paired > _WEBGL_THRESHOLD else go.Scatter
    diffs = [yi - xi for xi, yi in zip(data.x, data.y)]
    fig.add_trace(
        scatter(
            x=data.x,
            y=data.y,
            mode="markers",
            name=f"paired (n={data.n_paired:,})",
            customdata=list(zip(data.keys, diffs)),
            marker=dict(
                color=theme.marker,
                opacity=theme.marker_opacity,
                size=7,
                line=dict(color=theme.marker_line, width=0.5),
            ),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                f"{data.x_label}: %{{x:.4g}}<br>"
                f"{data.y_label}: %{{y:.4g}}<br>"
                "difference: %{customdata[1]:+.4g}<extra></extra>"
            ),
        )
    )


def _add_rugs(
    fig: go.Figure,
    data: ParityData,
    lo: float,
    hi: float,
    log: bool,
    theme: themes.Theme,
) -> None:
    """Draw unpaired records as ticks on the axis whose value is known.

    The ticks straddle the zero line, so they read as marks *on the axis*
    rather than as data at some particular height. They are not given a
    fabricated second coordinate -- the missing value is unknown, not zero.
    """
    baseline = _rug_baseline(lo, hi, log)

    if len(data.missing_y):
        fig.add_trace(
            go.Scatter(
                x=data.missing_y.values,
                y=[baseline] * len(data.missing_y),
                mode="markers",
                name=f"missing {data.y_label} (n={len(data.missing_y):,})",
                customdata=data.missing_y.keys,
                marker=dict(
                    color=theme.rug, symbol="line-ns-open", size=12, line=dict(width=2)
                ),
                cliponaxis=False,
                hovertemplate=(
                    "<b>%{customdata}</b><br>"
                    f"{data.x_label}: %{{x:.4g}}<br>"
                    f"{data.y_label}: missing<extra></extra>"
                ),
            )
        )

    if len(data.missing_x):
        fig.add_trace(
            go.Scatter(
                x=[baseline] * len(data.missing_x),
                y=data.missing_x.values,
                mode="markers",
                name=f"missing {data.x_label} (n={len(data.missing_x):,})",
                customdata=data.missing_x.keys,
                marker=dict(
                    color=theme.rug, symbol="line-ew-open", size=12, line=dict(width=2)
                ),
                cliponaxis=False,
                hovertemplate=(
                    "<b>%{customdata}</b><br>"
                    f"{data.x_label}: missing<br>"
                    f"{data.y_label}: %{{y:.4g}}<extra></extra>"
                ),
            )
        )


def _apply_layout(
    fig: go.Figure,
    data: ParityData,
    plot: PlotConfig,
    theme: themes.Theme,
    summary: stats_mod.Stats,
    lo: float,
    hi: float,
) -> None:
    axis_type = "log" if plot.log else "linear"
    x_axis = dict(title=plot.x_label or data.x_label, range=[lo, hi], type=axis_type)
    y_axis = dict(title=plot.y_label or data.y_label, range=[lo, hi], type=axis_type)
    if plot.equal_axes:
        # `constrain="domain"` is what makes both axes actually *start and end*
        # at the same value. Under the default ("range"), Plotly satisfies the
        # 1:1 pixel ratio by widening whichever axis has more room, so a
        # non-square drawing area silently pulls the ranges apart no matter
        # what we set here. Shrinking the domain instead keeps them honest.
        y_axis |= dict(scaleanchor="x", scaleratio=1, constrain="domain")
        x_axis |= dict(constrain="domain")

    try:
        placement, margin = _LEGEND_LAYOUTS[plot.legend]
    except KeyError:
        raise ValueError(
            f"unknown legend position {plot.legend!r}; "
            f"available positions are {sorted(_LEGEND_LAYOUTS)}"
        ) from None

    fig.update_layout(
        template=theme.template_name,
        title=dict(
            text=plot.title,
            subtitle=dict(
                text=stats_mod.summarize_nulls(summary, data.x_label, data.y_label),
                font=dict(color=theme.font_muted, size=13),
            ),
        ),
        xaxis=x_axis,
        yaxis=y_axis,
        hovermode="closest",
        showlegend=placement is not None,
        margin=margin,
    )
    if placement is not None:
        fig.update_layout(legend=placement)


def _add_stats_box(
    fig: go.Figure,
    summary: stats_mod.Stats,
    metrics: tuple[str, ...],
    theme: themes.Theme,
    lo: float,
    hi: float,
) -> None:
    """Place the metrics inside the top-left of the plotting area.

    Positioned in data coordinates rather than paper coordinates: with
    `constrain="domain"`, Plotly shrinks the drawn axes inside the specified
    domain, and paper-anchored items keep referencing the *original* domain --
    which floats the box above the visible frame. Data coordinates track the
    frame wherever it ends up. (On a log axis Plotly reads these as exponents,
    which is exactly what `lo`/`hi` already are.)
    """
    lines = stats_mod.format_lines(summary, metrics)
    if not lines:
        return
    inset = (hi - lo) * 0.04
    fig.add_annotation(
        xref="x",
        yref="y",
        x=lo + inset,
        y=hi - inset,
        xanchor="left",
        yanchor="top",
        align="left",
        text="<br>".join(lines),
        showarrow=False,
        font=dict(color=theme.font, size=12, family="monospace"),
        bgcolor=theme.box_bg,
        bordercolor=theme.box_border,
        borderwidth=1,
        borderpad=8,
    )


def save(fig: go.Figure, output: OutputConfig) -> Path:
    """Write the figure to disk in the configured format."""
    path = Path(output.path)
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)

    fig.update_layout(width=output.width, height=output.height)

    if output.format == "html":
        fig.write_html(str(path), include_plotlyjs="cdn")
        return path

    try:
        fig.write_image(str(path), format=output.format)
    except Exception as exc:
        raise ExportError(_export_hint(output.format, exc)) from exc
    return path


class ExportError(RuntimeError):
    """Raised when a static image could not be written."""


def _export_hint(fmt: str, exc: Exception) -> str:
    """Turn an export failure into the remedy that actually applies.

    Kaleido and its headless browser are separate installs, and each failure
    reports itself in terms of the other, so the naive message sends people to
    reinstall something they already have.
    """
    detail = str(exc).lower()
    if isinstance(exc, ImportError) or "kaleido is not installed" in detail:
        return (
            f"writing {fmt} needs the kaleido engine, which is an optional "
            f"extra. Install it with:  uv sync --extra static"
        )
    if "chrome" in detail:
        return (
            f"writing {fmt} needs a headless Chrome for kaleido to render "
            f"into, and none was found. Install one with:  "
            f"uv run plotly_get_chrome\n"
            f"(HTML output needs none of this -- use -o plot.html instead.)"
        )
    return f"could not write {fmt} image: {exc}"
