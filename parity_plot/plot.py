"""Figure construction.

The defining property of a parity plot is that ``y = x`` runs at a true 45
degrees. That requires two things together: a single range shared by both axes,
and ``scaleanchor`` locking their pixel scales. Either one alone lets the
identity line drift off the diagonal, so both are asserted in the tests.

The identity line is the built-in ``parity`` tolerance -- a zero-width entry
whose envelope collapses onto ``y = x`` -- so it renders through the same path
as every other tolerance.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

import plotly.graph_objects as go

from . import stats as stats_mod
from . import themes
from .config import OutputConfig, PlotConfig, StatsConfig
from .data import ParityData, Unpaired
from .encoding import DEFAULT_SYMBOLS, Encoding, partition
from .tolerances import (
    NamedTolerance,
    draw_order,
    failures,
    verdict_text,
)

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
        dict(l=80, r=160, t=100, b=80),
    ),
    "bottom": (
        dict(orientation="h", x=0.5, xanchor="center", y=-0.09, yanchor="top"),
        dict(l=80, r=50, t=100, b=120),
    ),
    "none": (None, dict(l=80, r=50, t=100, b=80)),
}

_PARITY_DOMAIN_WITH_DELTA_HISTOGRAM = [0.34, 1.0]
_DELTA_HISTOGRAM_DOMAIN = [0.0, 0.20]


def build_figure(
    data: ParityData,
    plot: PlotConfig | None = None,
    stats_cfg: StatsConfig | None = None,
) -> go.Figure:
    plot = plot or PlotConfig()
    stats_cfg = stats_cfg or StatsConfig()
    theme = themes.get(plot.theme)

    is_scale = plot.encoding.color_by == "colorscale"
    if is_scale and data.color_values is None:
        raise ValueError(
            "color_by=colorscale needs a numeric colour column; set [data].color_column"
        )

    if plot.log:
        data = _drop_non_positive(data)

    summary = stats_mod.compute(data, plot.tolerances)
    lo, hi = _axis_range(data, log=plot.log)

    fig = go.Figure()
    _add_tolerances(fig, plot.tolerances, lo, hi, plot.log, theme)
    _add_paired(fig, data, plot.tolerances, plot.encoding, theme)
    if plot.nulls == "rug":
        _add_rugs(fig, data, lo, hi, plot.log, theme)
    if plot.delta_histogram:
        _add_delta_histogram(fig, data, plot, theme)

    _apply_layout(fig, data, plot, theme, summary, lo, hi, has_colorbar=is_scale)
    if stats_cfg.show:
        _add_stats_box(fig, summary, stats_cfg.metrics, theme, lo, hi)
    return fig


def _drop_non_positive(data: ParityData) -> ParityData:
    """Remove values a log axis cannot show, reporting how many were lost."""
    # Re-slice every per-paired-point list by kept indices so hover text and
    # colour stay aligned to x/y. group is deliberately left alone: re-slicing
    # it is a pre-existing gap tracked separately, not this feature's to close.
    kept = [i for i in range(data.n_paired) if data.x[i] > 0 and data.y[i] > 0]
    hovers = (
        [data.hover_values[i] for i in kept] if data.hover_values is not None else None
    )
    missing_y = _filter_unpaired(data.missing_y)
    missing_x = _filter_unpaired(data.missing_x)

    removed = (
        (data.n_paired - len(kept))
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
        keys=[data.keys[i] for i in kept],
        x=[data.x[i] for i in kept],
        y=[data.y[i] for i in kept],
        color_values=(
            [data.color_values[i] for i in kept]
            if data.color_values is not None
            else None
        ),
        hover_values=hovers,
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


def _add_tolerances(
    fig: go.Figure,
    tolerances: Sequence[NamedTolerance],
    lo: float,
    hi: float,
    log: bool,
    theme: themes.Theme,
) -> None:
    """Draw every enabled tolerance, parity last so nothing buries it."""
    for tol in draw_order(tolerances):
        _add_one_tolerance(fig, tol, lo, hi, log, theme)


def _add_one_tolerance(
    fig: go.Figure,
    tol: NamedTolerance,
    lo: float,
    hi: float,
    log: bool,
    theme: themes.Theme,
) -> None:
    """Draw one tolerance envelope, or a single line when it is zero-width.

    Straight segments in linear space curve on a log axis, so the log case is
    sampled densely rather than drawn vertex to vertex. The parity entry is a
    zero-width tolerance whose envelope collapses onto ``y = x``; drawing both
    edges would stack two identical traces and double its legend entry, so that
    case renders a single line instead.
    """
    geometry = tol.tolerance
    if log:
        xs, upper, lower = geometry.log_envelope(lo, hi)
    else:
        xs, upper, lower = geometry.envelope(lo, hi)
    if not xs:
        return

    colour = theme.resolve_color(tol.color_token)
    shaded = tol.style == "shaded"
    line = dict(color=colour, width=2 if tol.builtin else 1.6)

    # A zero-width tolerance (the parity line) has upper == lower, so drawing
    # both would stack two identical traces and double the legend entry.
    if upper == lower:
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=upper,
                mode="lines",
                name=tol.display_label,
                line=line,
                showlegend=tol.show_in_legend,
                hoverinfo="skip",
            )
        )
        return

    # The lower limit is drawn first so the shaded variant can fill up to it.
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=lower,
            mode="lines",
            name=tol.display_label,
            legendgroup=tol.name,
            line=dict(width=0) if shaded else line,
            showlegend=tol.show_in_legend and not shaded,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=upper,
            mode="lines",
            name=tol.display_label,
            legendgroup=tol.name,
            line=dict(width=0) if shaded else line,
            fill="tonexty" if shaded else None,
            fillcolor=theme.band_fill_for(tol.color_token) if shaded else None,
            showlegend=tol.show_in_legend and shaded,
            hoverinfo="skip",
        )
    )


def _paired_hovertemplate(data: ParityData) -> str:
    """The hover layout for a paired point.

    customdata is (key, difference, verdict, *hover cells), so the configured
    columns start at index 3. The verdict stays last: it reads as the
    conclusion, and the metadata belongs with the record's identity above it.
    """
    rows = [
        "<b>%{customdata[0]}</b>",
        f"{data.x_label}: %{{x:.4g}}",
        f"{data.y_label}: %{{y:.4g}}",
        "difference: %{customdata[1]:+.4g}",
    ]
    for i, label in enumerate(data.hover_labels):
        rows.append(f"{label}: %{{customdata[{3 + i}]}}")
    rows.append("%{customdata[2]}<extra></extra>")
    return "<br>".join(rows)


def _add_paired(
    fig: go.Figure,
    data: ParityData,
    tolerances: Sequence[NamedTolerance],
    encoding: Encoding,
    theme: themes.Theme,
) -> None:
    """Draw the paired points, one trace per (colour, symbol) the encoding yields.

    Under ``color_by = "colorscale"`` colour is per-point, so the colour key is
    constant and does not split traces: every symbol group shares one continuous
    colour mapping, drawn once as a colorbar. Otherwise each trace's colour key
    is resolved to a real colour through the theme.
    """
    scatter = go.Scattergl if data.n_paired > _WEBGL_THRESHOLD else go.Scatter
    diffs = [yi - xi for xi, yi in zip(data.x, data.y)]
    verdicts = [
        verdict_text(failures(tolerances, xi, yi)) for xi, yi in zip(data.x, data.y)
    ]
    passes = [failures(tolerances, xi, yi) == () for xi, yi in zip(data.x, data.y)]

    specs = partition(data.n_paired, passes, data.group, encoding)
    symbols = _resolve_symbols(specs, encoding)

    is_scale = encoding.color_by == "colorscale"
    colours = None if is_scale else _resolve_colours(specs, encoding, theme)
    cmin = cmax = None
    color_values: list[float | None] = []
    if is_scale:
        # build_figure guarantees color_values is present under colorscale.
        assert data.color_values is not None
        color_values = data.color_values
        finite = [c for c in color_values if c is not None]
        cmin, cmax = (min(finite), max(finite)) if finite else (0.0, 1.0)

    template = _paired_hovertemplate(data)
    for i, spec in enumerate(specs):
        idx = spec.indices
        name = spec.name if len(specs) > 1 else f"paired (n={data.n_paired:,})"
        if is_scale:
            marker: dict[str, Any] = dict(
                color=[color_values[j] for j in idx],
                colorscale=encoding.colorscale,
                cmin=cmin,
                cmax=cmax,
                showscale=(i == 0),
                symbol=symbols[spec.symbol_key],
                opacity=theme.marker_opacity,
                size=7,
                line=dict(color=theme.marker_line, width=0.5),
            )
            if i == 0:
                marker["colorbar"] = dict(
                    title=dict(text=data.color_label),
                    x=1.02,
                    xanchor="left",
                    thickness=14,
                    len=0.6,
                    y=0.5,
                    yanchor="middle",
                )
        else:
            assert colours is not None
            marker = dict(
                color=colours[spec.color_key],
                symbol=symbols[spec.symbol_key],
                opacity=theme.marker_opacity,
                size=7,
                line=dict(color=theme.marker_line, width=0.5),
            )
        fig.add_trace(
            scatter(
                x=[data.x[j] for j in idx],
                y=[data.y[j] for j in idx],
                mode="markers",
                name=name,
                customdata=[
                    (
                        data.keys[j],
                        diffs[j],
                        verdicts[j],
                        *(data.hover_values[j] if data.hover_values else ()),
                    )
                    for j in idx
                ],
                marker=marker,
                hovertemplate=template,
            )
        )


def _resolve_colours(
    specs: Sequence, encoding: Encoding, theme: themes.Theme
) -> dict[str, str]:
    """Map each trace's colour key to a real colour, per channel.

    Symbol keys are already Plotly names, but colour is theme-dependent, so it
    stays a key until here: a token for `single`, pass/fail for the verdict, or
    a group value cycled through the theme palette in first-seen order.
    """
    if encoding.color_by == "pass-fail":
        return {"pass": theme.pass_color, "fail": theme.fail_color}
    if encoding.color_by == "group":
        distinct: list[str] = []
        for spec in specs:
            if spec.color_key not in distinct:
                distinct.append(spec.color_key)
        palette = themes.GROUP_PALETTE
        return {
            key: theme.resolve_color(palette[i % len(palette)])
            for i, key in enumerate(distinct)
        }
    # single: the colour key is a token (or hex) the theme resolves directly.
    return {spec.color_key: theme.resolve_color(spec.color_key) for spec in specs}


def _resolve_symbols(specs: Sequence, encoding: Encoding) -> dict[str, str]:
    """Map each trace's symbol key to a real Plotly symbol name.

    Symmetric with :func:`_resolve_colours`, minus the theme: a symbol does not
    depend on light/dark. For ``symbol_by = "group"`` the symbol keys are group
    *values*, assigned symbols from ``encoding.symbol_sequence`` (or the built-in
    :data:`DEFAULT_SYMBOLS`) in first-seen order, wrapping when groups outnumber
    symbols. For every other channel the key is already a symbol name.
    """
    if encoding.symbol_by == "group":
        distinct: list[str] = []
        for spec in specs:
            if spec.symbol_key not in distinct:
                distinct.append(spec.symbol_key)
        sequence = encoding.symbol_sequence or DEFAULT_SYMBOLS
        return {key: sequence[i % len(sequence)] for i, key in enumerate(distinct)}
    return {spec.symbol_key: spec.symbol_key for spec in specs}


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


def _add_delta_histogram(
    fig: go.Figure,
    data: ParityData,
    plot: PlotConfig,
    theme: themes.Theme,
) -> None:
    """Draw the signed paired deltas in a compact lower panel."""
    deltas = [yi - xi for xi, yi in zip(data.x, data.y)]
    if not deltas:
        return
    centers, counts, width = _histogram(deltas, delta_histogram_bin_count(deltas, plot))

    fig.add_trace(
        go.Bar(
            x=centers,
            y=counts,
            width=[width] * len(centers),
            xaxis="x2",
            yaxis="y2",
            name="delta histogram",
            showlegend=False,
            marker=dict(
                color=theme.marker,
                opacity=0.75,
                line=dict(color=theme.marker_line, width=0.5),
            ),
            hovertemplate="delta: %{x:.4g}<br>count: %{y}<extra></extra>",
        )
    )
    _add_delta_reference_line(fig, 0.0, theme.identity, width=1.5)
    if plot.delta_histogram_sigma_lines:
        sigma = _stddev(deltas)
        if sigma > 0:
            for x in (-sigma, sigma):
                _add_delta_reference_line(
                    fig, x, theme.font_muted, width=1.25, dash="dash"
                )
    y_label = plot.y_label or data.y_label
    x_label = plot.x_label or data.x_label
    fig.add_annotation(
        xref="paper",
        yref="paper",
        x=0,
        y=_DELTA_HISTOGRAM_DOMAIN[1],
        xanchor="left",
        yanchor="bottom",
        text=f"Delta distribution ({y_label} - {x_label})",
        showarrow=False,
        font=dict(color=theme.font_muted, size=12),
    )


def delta_histogram_bin_count(deltas: Sequence[float], plot: PlotConfig) -> int:
    """The effective delta-histogram bucket count for this data and config."""
    if not plot.delta_histogram_bins_auto and plot.delta_histogram_bins is not None:
        return _odd_bucket_count(int(plot.delta_histogram_bins))
    return _odd_bucket_count(math.ceil(math.sqrt(len(deltas))))


def _odd_bucket_count(count: int) -> int:
    count = max(1, count)
    return count if count % 2 == 1 else count + 1


def _histogram(
    deltas: Sequence[float], bins: int
) -> tuple[list[float], list[int], float]:
    bins = _odd_bucket_count(bins)
    half = bins // 2
    max_abs = max(abs(delta) for delta in deltas)
    width = max_abs / (half + 0.5) if max_abs else 1.0
    counts = [0] * bins
    for delta in deltas:
        index = math.floor(delta / width + half + 0.5)
        counts[min(max(index, 0), bins - 1)] += 1
    centers = [(i - half) * width for i in range(bins)]
    return centers, counts, width


def _stddev(values: Sequence[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _add_delta_reference_line(
    fig: go.Figure,
    x: float,
    color: str,
    *,
    width: float,
    dash: str | None = None,
) -> None:
    line: dict[str, Any] = dict(color=color, width=width)
    if dash is not None:
        line["dash"] = dash
    fig.add_shape(
        type="line",
        xref="x2",
        yref="y2 domain",
        x0=x,
        x1=x,
        y0=0,
        y1=1,
        line=line,
    )


def _apply_layout(
    fig: go.Figure,
    data: ParityData,
    plot: PlotConfig,
    theme: themes.Theme,
    summary: stats_mod.Stats,
    lo: float,
    hi: float,
    has_colorbar: bool = False,
) -> None:
    axis_type = "log" if plot.log else "linear"
    x_axis: dict[str, Any] = dict(
        title=plot.x_label or data.x_label, range=[lo, hi], type=axis_type
    )
    y_axis: dict[str, Any] = dict(
        title=plot.y_label or data.y_label, range=[lo, hi], type=axis_type
    )
    if plot.equal_axes:
        # `constrain="domain"` is what makes both axes actually *start and end*
        # at the same value. Under the default ("range"), Plotly satisfies the
        # 1:1 pixel ratio by widening whichever axis has more room, so a
        # non-square drawing area silently pulls the ranges apart no matter
        # what we set here. Shrinking the domain instead keeps them honest.
        y_axis |= dict(scaleanchor="x", scaleratio=1, constrain="domain")
        x_axis |= dict(constrain="domain")

    hist_x_axis: dict[str, Any] | None = None
    hist_y_axis: dict[str, Any] | None = None
    if plot.delta_histogram:
        tick_labels = None
        if plot.delta_histogram_bucket_labels:
            deltas = [yi - xi for xi, yi in zip(data.x, data.y)]
            if deltas:
                centers, _, _ = _histogram(
                    deltas, delta_histogram_bin_count(deltas, plot)
                )
                tick_labels = centers
        y_axis["domain"] = _PARITY_DOMAIN_WITH_DELTA_HISTOGRAM
        hist_x_axis = dict(
            title=f"{plot.y_label or data.y_label} - {plot.x_label or data.x_label}",
            anchor="y2",
            domain=[0.0, 1.0],
            zeroline=True,
            zerolinecolor=theme.identity,
            zerolinewidth=1.5,
        )
        hist_y_axis = dict(
            title="count",
            anchor="x2",
            domain=_DELTA_HISTOGRAM_DOMAIN,
            rangemode="tozero",
            type="log" if plot.delta_histogram_log_y else "linear",
        )
        if tick_labels is not None:
            hist_x_axis |= dict(
                tickmode="array",
                tickvals=tick_labels,
                ticktext=[f"{value:.4g}" for value in tick_labels],
                tickangle=90,
            )

    try:
        placement, margin = _LEGEND_LAYOUTS[plot.legend]
    except KeyError:
        raise ValueError(
            f"unknown legend position {plot.legend!r}; "
            f"available positions are {sorted(_LEGEND_LAYOUTS)}"
        ) from None

    if has_colorbar:
        if plot.legend == "right" and placement is not None:
            placement = {**placement, "x": 1.16}
            margin = {**margin, "r": 300}
        else:
            margin = {**margin, "r": max(margin["r"], 110)}
    if plot.delta_histogram:
        margin = {**margin, "b": max(margin["b"], 140)}

    layout: dict[str, Any] = dict(
        template=theme.template_name,
        title=dict(
            text=plot.title,
            # Centre on the plotting area (paper), not the whole figure: the
            # asymmetric margins (a wide right margin for the legend) push the
            # axes left, and Plotly's default container-centred title then floats
            # right of the plot.
            x=0.5,
            xanchor="center",
            xref="paper",
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
    if hist_x_axis is not None and hist_y_axis is not None:
        layout["xaxis2"] = hist_x_axis
        layout["yaxis2"] = hist_y_axis
    fig.update_layout(**layout)
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


# How `[output].plotlyjs` maps onto plotly's own `include_plotlyjs` argument.
# True inlines the library, False emits none, the rest are plotly's spellings.
_PLOTLYJS_ARG: dict[str, bool | str] = {
    "inline": True,
    "cdn": "cdn",
    "directory": "directory",
    "none": False,
}


def to_fragment(
    fig: go.Figure, div_id: str | None = None, plotlyjs: str = "none"
) -> str:
    """The figure as an HTML fragment, for embedding in a page you own.

    A ``<div>`` and its ``<script>`` with no ``<html>``/``<head>`` wrapper, so any
    number of plots can share the one copy of plotly.js the page loads itself. A
    fragment carries only the data, so it costs a few KB for a small plot and tens
    of KB for a large one -- against the flat ~4.9 MB of library that a standalone
    inlined document repeats per file.

    Pass an explicit ``div_id`` when the output is cached or diffed: plotly
    invents a random UUID otherwise, so identical data produces a different
    fragment on every run.

    The fragment carries **no width or height** -- the container sizes it. That
    matters more here than it looks: the 45 degree parity line survives only
    while both axes share a range *and* their pixel scales are locked *and*
    ``constrain="domain"`` is set. Baking in pixels the container does not have
    makes Plotly lay the axes out for the wrong box, and the diagonal quietly
    stops being diagonal. Call ``Plotly.Plots.resize(div)`` when the container
    changes size.
    """
    if plotlyjs not in _PLOTLYJS_ARG:
        raise ValueError(
            f"unknown plotlyjs mode {plotlyjs!r}; valid modes are "
            f"{sorted(_PLOTLYJS_ARG)}"
        )
    return fig.to_html(
        full_html=False,
        include_plotlyjs=_PLOTLYJS_ARG[plotlyjs],
        div_id=div_id,
    )


def save(fig: go.Figure, output: OutputConfig) -> Path:
    """Write the figure to disk in the configured format."""
    path = Path(output.path)
    if path.parent != Path(""):
        path.parent.mkdir(parents=True, exist_ok=True)

    fmt = output.resolved_format
    if fmt == "html" and output.embed:
        # Deliberately before the width/height update: a fragment is sized by
        # the page it lands in, and forcing pixels here is what breaks the
        # 45 degree invariant in a responsive container (see to_fragment).
        path.write_text(
            to_fragment(fig, div_id=output.div_id, plotlyjs=output.resolved_plotlyjs),
            encoding="utf-8",
        )
        return path

    fig.update_layout(width=output.width, height=output.height)

    if fmt == "html":
        fig.write_html(
            str(path), include_plotlyjs=_PLOTLYJS_ARG[output.resolved_plotlyjs]
        )
        return path

    try:
        fig.write_image(str(path), format=fmt)
    except Exception as exc:
        raise ExportError(_export_hint(fmt, exc)) from exc
    return path


class ExportError(RuntimeError):
    """Raised when a static image could not be written."""


def _export_hint(fmt: str, exc: Exception) -> str:
    """Turn an export failure into the remedy that actually applies.

    Kaleido is a required dependency, so it is always present; what goes missing
    is the headless browser it renders into. Kaleido's own error reports itself
    in terms of the other, which would otherwise send people to reinstall
    something they already have.
    """
    detail = str(exc).lower()
    if isinstance(exc, ImportError) or "kaleido is not installed" in detail:
        return (
            f"writing {fmt} needs the kaleido engine, which should have been "
            f"installed with parity-plot. Try:  uv sync"
        )
    if "chrome" in detail:
        return (
            f"writing {fmt} needs a headless Chrome for kaleido to render "
            f"into, and none was found. Install one with:  "
            f"uv run plotly_get_chrome\n"
            f"(HTML output needs none of this -- use -o plot.html instead.)"
        )
    return f"could not write {fmt} image: {exc}"
