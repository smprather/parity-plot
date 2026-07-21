from __future__ import annotations

import pytest

from parity_plot import parity_plot
from parity_plot.config import OutputConfig, PlotConfig, StatsConfig
from parity_plot.data import ParityData, Unpaired, from_sequences
from parity_plot.plot import build_figure, save
from parity_plot.tolerances import NamedTolerance, parity, with_parity


def _tol(**kwargs):
    """Shorthand for a tolerance list with the parity entry plus one spec.

    Real configs always carry the built-in ``y = x`` reference, so the
    rendering tests do too -- ``with_parity`` prepends it. The spec entry is
    named ``t1``.
    """
    return with_parity((NamedTolerance(name="t1", **kwargs),))


# Phase 2 taught plot.py to render the tolerance list. These tests now assert
# the list shape directly; the xfail marker is retired.


@pytest.fixture
def data():
    return from_sequences(
        x=[1.0, 2.0, 3.0, 4.0, None, 9.0],
        y=[1.1, 2.2, 2.9, None, 7.0, None],
        keys=["a", "b", "c", "d", "e", "f"],
    )


def trace_named(fig, fragment):
    return next((t for t in fig.data if t.name and fragment in t.name), None)


def test_axes_are_locked_to_45_degrees(data):
    """Equal ranges and scaleanchor together are what make it a parity plot;
    either alone lets y = x drift off the diagonal."""
    fig = build_figure(data, PlotConfig())

    assert list(fig.layout.xaxis.range) == list(fig.layout.yaxis.range)
    assert fig.layout.yaxis.scaleanchor == "x"
    assert fig.layout.yaxis.scaleratio == 1


def test_axes_keep_their_range_when_the_drawing_area_is_not_square(data):
    """Without constrain="domain", Plotly honours scaleanchor by *widening*
    whichever axis has more room, so the two axes stop starting at the same
    value on any non-square figure."""
    fig = build_figure(data, PlotConfig())

    assert fig.layout.xaxis.constrain == "domain"
    assert fig.layout.yaxis.constrain == "domain"


def test_constrain_is_dropped_with_equal_axes_off(data):
    fig = build_figure(data, PlotConfig(equal_axes=False))
    assert fig.layout.yaxis.constrain is None


def test_equal_axes_can_be_switched_off(data):
    fig = build_figure(data, PlotConfig(equal_axes=False))
    assert fig.layout.yaxis.scaleanchor is None


def test_axis_range_covers_unpaired_values():
    """A rug mark outside the range would silently vanish."""
    data = from_sequences(x=[1.0, 2.0, 500.0], y=[1.0, 2.0, None])
    fig = build_figure(data, PlotConfig())
    lo, hi = fig.layout.xaxis.range
    assert lo <= 1.0 and hi >= 500.0


def test_rug_traces_carry_every_unpaired_record(data):
    fig = build_figure(data, PlotConfig(nulls="rug"))

    missing_y = trace_named(fig, "missing y")
    missing_x = trace_named(fig, "missing x")

    assert len(missing_y.x) == len(data.missing_y) == 2  # d and f
    assert len(missing_x.y) == len(data.missing_x) == 1  # e
    # Each sits on one baseline rather than getting a fabricated value.
    assert len(set(missing_y.y)) == 1
    assert len(set(missing_x.x)) == 1


def test_rug_ticks_sit_on_zero_when_zero_is_in_range():
    """They should read as marks on the axis, not as data at some height."""
    data = from_sequences(x=[0.0, 10.0, 20.0, 30.0], y=[0.5, 11.0, None, None])
    fig = build_figure(data, PlotConfig(nulls="rug"))

    lo, hi = fig.layout.xaxis.range
    assert lo <= 0 <= hi
    assert set(trace_named(fig, "missing y").y) == {0.0}


def test_rug_ticks_fall_back_to_the_floor_when_zero_is_off_plot():
    """Data far from the origin would put a zero baseline outside the axes."""
    data = from_sequences(x=[100.0, 200.0, 300.0], y=[101.0, None, None])
    fig = build_figure(data, PlotConfig(nulls="rug"))

    lo, _ = fig.layout.xaxis.range
    assert lo > 0
    assert set(trace_named(fig, "missing y").y) == {lo}


def test_rug_ticks_avoid_zero_on_a_log_axis():
    """A log axis cannot render zero at all."""
    data = from_sequences(x=[1.0, 10.0, 100.0], y=[1.1, None, None])
    fig = build_figure(data, PlotConfig(nulls="rug", log=True))

    baseline = set(trace_named(fig, "missing y").y)
    assert baseline == {10 ** fig.layout.yaxis.range[0]}
    assert 0.0 not in baseline


def test_drop_mode_omits_the_rugs_but_still_counts_them(data):
    fig = build_figure(data, PlotConfig(nulls="drop"))

    assert trace_named(fig, "missing y") is None
    assert trace_named(fig, "missing x") is None
    assert "2 missing y" in fig.layout.title.subtitle.text
    assert "1 missing x" in fig.layout.title.subtitle.text


def test_parity_line_spans_the_full_range(data):
    """The parity entry is a zero-width tolerance, so its envelope is y = x."""
    fig = build_figure(data, PlotConfig())
    line = trace_named(fig, "0% error")
    lo, hi = fig.layout.xaxis.range
    assert list(line.x) == pytest.approx(list(line.y))
    assert line.x[0] == pytest.approx(lo)
    assert line.x[-1] == pytest.approx(hi)


def test_parity_line_can_be_switched_off(data):
    """Disabling the parity entry replaces the old identity_line = false."""
    from dataclasses import replace
    from parity_plot.tolerances import parity
    fig = build_figure(data, PlotConfig(tolerances=(replace(parity(), enabled=False),)))
    assert trace_named(fig, "0% error") is None


def test_relative_tolerance_draws_a_wedge_through_the_origin(data):
    fig = build_figure(data, PlotConfig(tolerances=_tol(reltol=0.10)))
    limits = [t for t in fig.data if t.name == "±10%"]
    assert len(limits) == 2  # an upper and a lower limit line

    lower, upper = limits
    assert list(upper.y) == pytest.approx([x + 0.1 * abs(x) for x in upper.x])
    assert list(lower.y) == pytest.approx([x - 0.1 * abs(x) for x in lower.x])


def test_absolute_tolerance_draws_lines_parallel_to_the_identity(data):
    """abstol is a fixed offset in data units, so the gap never changes."""
    fig = build_figure(data, PlotConfig(tolerances=_tol(abstol=2.0)))
    lower, upper = [t for t in fig.data if t.name == "±2"]

    assert list(upper.y) == pytest.approx([x + 2.0 for x in upper.x])
    assert list(lower.y) == pytest.approx([x - 2.0 for x in lower.x])
    # Parallel: the offset is constant, not proportional.
    assert len(set(round(y - x, 9) for x, y in zip(upper.x, upper.y))) == 1


def test_funnel_takes_whichever_tolerance_is_looser(data):
    fig = build_figure(data, PlotConfig(tolerances=_tol(abstol=2.0, reltol=0.10)))
    lower, upper = [t for t in fig.data if t.name == "±max(2, 10%)"]

    for x, y in zip(upper.x, upper.y):
        assert y == pytest.approx(x + max(2.0, 0.1 * abs(x)))
    for x, y in zip(lower.x, lower.y):
        assert y == pytest.approx(x - max(2.0, 0.1 * abs(x)))


def test_funnel_puts_a_vertex_exactly_at_the_crossover():
    """The kink is real geometry; a coarse sample would round it off."""
    data = from_sequences(x=[0.0, 100.0], y=[0.0, 100.0])
    fig = build_figure(data, PlotConfig(tolerances=_tol(abstol=2.0, reltol=0.10)))
    upper = [t for t in fig.data if t.name == "±max(2, 10%)"][1]

    assert 20.0 in [pytest.approx(v) for v in upper.x]  # crossover at 2 / 0.10


def test_tolerance_limits_are_lines_not_shading_by_default(data):
    fig = build_figure(data, PlotConfig(tolerances=_tol(reltol=0.10)))
    lower, upper = [t for t in fig.data if t.name == "±10%"]
    assert upper.fill is None
    assert lower.line.width > 0


def test_shaded_band_style_fills_between_the_limits(data):
    fig = build_figure(data, PlotConfig(tolerances=_tol(reltol=0.10, style="shaded")))
    lower, upper = [t for t in fig.data if t.name == "±10%"]
    assert upper.fill == "tonexty"
    assert upper.fillcolor is not None


def test_unknown_band_style_is_rejected(data):
    """A bad style is rejected when the tolerance is built, not at draw time."""
    with pytest.raises(ValueError, match="is not one of"):
        build_figure(data, PlotConfig(tolerances=_tol(reltol=0.10, style="dotted")))


def test_no_tolerance_draws_no_limits(data):
    fig = build_figure(data, PlotConfig())
    assert not [t for t in fig.data if t.name and t.name.startswith("±")]


def test_identity_line_is_solid(data):
    """Solid green marks exact agreement; the dashed red lines are the limits."""
    line = trace_named(build_figure(data, PlotConfig()), "0% error")
    assert line.line.dash is None


def test_legend_sits_on_the_right_by_default(data):
    fig = build_figure(data, PlotConfig())
    assert fig.layout.showlegend
    assert fig.layout.legend.orientation == "v"
    assert fig.layout.legend.x > 1.0  # outside the plotting area


def test_legend_can_move_to_the_bottom(data):
    fig = build_figure(data, PlotConfig(legend="bottom"))
    assert fig.layout.showlegend
    assert fig.layout.legend.orientation == "h"
    assert fig.layout.legend.y < 0


def test_legend_can_be_hidden(data):
    fig = build_figure(data, PlotConfig(legend="none"))
    assert fig.layout.showlegend is False


@pytest.mark.parametrize("position", ["right", "bottom", "none"])
def test_each_legend_position_reserves_its_own_margin(data, position):
    """A right-hand legend needs width where a bottom one needs height; sharing
    one margin set either clips the legend or strands the plot in whitespace."""
    fig = build_figure(data, PlotConfig(legend=position))
    margin = fig.layout.margin
    if position == "right":
        assert margin.r > margin.b
    elif position == "bottom":
        assert margin.b > margin.r


def test_unknown_legend_position_is_rejected(data):
    with pytest.raises(ValueError, match="unknown legend position"):
        build_figure(data, PlotConfig(legend="sideways"))


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_both_themes_build_and_apply_their_template(data, theme):
    fig = build_figure(data, PlotConfig(theme=theme))
    assert fig.layout.template.layout.paper_bgcolor is not None


def test_unknown_theme_is_rejected(data):
    with pytest.raises(ValueError, match="unknown theme"):
        build_figure(data, PlotConfig(theme="neon"))


def test_log_mode_drops_non_positive_values_and_warns():
    data = from_sequences(x=[1.0, 10.0, -5.0, 0.0], y=[1.0, 11.0, -4.0, 1.0])
    with pytest.warns(UserWarning, match="zero or negative"):
        fig = build_figure(data, PlotConfig(log=True))

    assert fig.layout.xaxis.type == "log"
    assert fig.layout.yaxis.type == "log"
    paired = trace_named(fig, "paired")
    assert list(paired.x) == [1.0, 10.0]


def test_log_mode_places_the_identity_line_in_data_space():
    """The axis range is in exponents on a log axis; the trace is not."""
    data = from_sequences(x=[1.0, 100.0], y=[1.0, 100.0])
    fig = build_figure(data, PlotConfig(log=True))
    line = trace_named(fig, "0% error")
    lo, hi = fig.layout.xaxis.range
    assert line.x[0] == pytest.approx(10**lo)
    assert line.x[-1] == pytest.approx(10**hi)


def test_stats_box_is_optional(data):
    assert len(build_figure(data, PlotConfig(), StatsConfig(show=True)).layout.annotations) == 1
    assert build_figure(data, PlotConfig(), StatsConfig(show=False)).layout.annotations == ()


def test_subtitle_reports_every_null_category():
    data = ParityData(
        keys=["a"], x=[1.0], y=[1.0],
        missing_y=Unpaired(["b"], [2.0]),
        missing_x=Unpaired(["c"], [3.0]),
        n_dropped=4,
        x_label="ref", y_label="meas",
    )
    subtitle = build_figure(data, PlotConfig()).layout.title.subtitle.text
    assert "1 paired" in subtitle
    assert "1 missing meas" in subtitle
    assert "1 missing ref" in subtitle
    assert "4 with neither" in subtitle


def test_empty_data_still_builds():
    fig = build_figure(from_sequences(x=[], y=[]), PlotConfig())
    assert fig.layout.xaxis.range is not None


def test_save_writes_html_and_creates_parent_dirs(data, tmp_path):
    out = tmp_path / "nested" / "dir" / "p.html"
    written = save(build_figure(data, PlotConfig()), OutputConfig(path=out))
    assert written.exists()
    assert "plotly" in written.read_text(encoding="utf-8").lower()


def test_public_api_accepts_sequences_and_paths(wide_csv):
    from_arrays = parity_plot(ref=[1.0, 2.0], test=[1.1, None], theme="light")
    assert from_arrays.layout.template.layout.paper_bgcolor == "#ffffff"

    from_path = parity_plot(wide_csv, ref="wide.csv:reference",
                           test="wide.csv:test", join="id")
    assert trace_named(from_path, "paired").x == (10.0, 30.0)


def test_public_api_rejects_mixed_and_unknown_arguments(wide_csv):
    with pytest.raises(TypeError, match="both be file:column strings"):
        parity_plot(wide_csv, ref="wide.csv:reference", test=[1.0, 2.0])
    with pytest.raises(TypeError, match="unexpected keyword"):
        parity_plot(ref=[1.0], test=[1.0], colour="blue")
    with pytest.raises(TypeError, match="not both"):
        parity_plot(wide_csv, ref=[1.0], test=[1.0])
