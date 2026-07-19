from __future__ import annotations

import math

import pytest

from parity_plot.data import ParityData, Unpaired
from parity_plot.tolerance import Tolerance
from parity_plot.stats import compute, format_lines, summarize_nulls


def make(x, y, **kwargs):
    return ParityData(keys=[str(i) for i in range(len(x))], x=list(x), y=list(y), **kwargs)


def test_perfect_agreement():
    stats = compute(make([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0]))
    assert stats.r2 == 1.0
    assert stats.rmse == 0.0
    assert stats.mae == 0.0
    assert stats.bias == 0.0
    assert stats.max_abs_err == 0.0


def test_metrics_against_hand_computed_values():
    # residuals: +1, -1, +2  ->  mean 2/3, mean|r| 4/3, sqrt(6/3) rmse
    stats = compute(make([10.0, 20.0, 30.0], [11.0, 19.0, 32.0]))
    assert stats.bias == pytest.approx(2 / 3)
    assert stats.mae == pytest.approx(4 / 3)
    assert stats.rmse == pytest.approx(math.sqrt(6 / 3))
    assert stats.max_abs_err == pytest.approx(2.0)


def test_identity_r2_is_stricter_than_a_best_fit():
    """Data on a tight line parallel to y=x agrees with nothing, and only the
    identity-line R² says so -- a least-squares fit would score it 1.0."""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [v + 10.0 for v in x]

    stats = compute(make(x, y))

    assert stats.pearson_r == pytest.approx(1.0)  # perfectly correlated
    assert stats.r2 < 0  # yet far worse than useless about y = x


def test_r2_is_none_when_y_has_no_variance():
    stats = compute(make([1.0, 2.0, 3.0], [5.0, 5.0, 5.0]))
    assert stats.r2 is None


def test_pearson_is_none_when_a_series_is_constant():
    stats = compute(make([2.0, 2.0, 2.0], [1.0, 2.0, 3.0]))
    assert stats.pearson_r is None


def test_fewer_than_two_points_yields_counts_only():
    stats = compute(make([1.0], [1.0]), Tolerance(reltol=0.10))
    assert stats.n_paired == 1
    assert stats.rmse is None and stats.r2 is None
    assert stats.within is None
    assert stats.tolerance_label == "±10%"


def test_relative_tolerance_fraction():
    # relative errors: 0%, 5%, 20%  ->  two of three inside +/-10%
    stats = compute(make([100.0] * 3, [100.0, 105.0, 120.0]), Tolerance(reltol=0.10))
    assert stats.within == pytest.approx(2 / 3)


def test_absolute_tolerance_fraction():
    """abstol is in the data's units, so it does not scale with magnitude."""
    stats = compute(make([1.0, 100.0], [2.5, 101.5]), Tolerance(abstol=2.0))
    assert stats.within == pytest.approx(1.0)  # errors of 1.5 both inside +/-2

    stats = compute(make([1.0, 100.0], [4.0, 101.0]), Tolerance(abstol=2.0))
    assert stats.within == pytest.approx(0.5)  # 3.0 is out, 1.0 is in


def test_funnel_scores_against_whichever_spec_is_looser():
    """Below the crossover the absolute floor governs; above it the relative."""
    tol = Tolerance(abstol=2.0, reltol=0.10)  # crossover at |x| = 20

    # x=1: relative allows 0.1, absolute allows 2.0 -> the looser (2.0) wins.
    assert compute(make([1.0, 1.0], [2.5, 2.5]), tol).within == pytest.approx(1.0)
    # x=100: absolute allows 2.0, relative allows 10.0 -> relative wins.
    assert compute(make([100.0, 100.0], [105.0, 105.0]), tol).within == pytest.approx(1.0)
    # x=100 with an error of 12 exceeds both.
    assert compute(make([100.0, 100.0], [112.0, 112.0]), tol).within == pytest.approx(0.0)


def test_counts_carry_the_unpaired_records():
    data = make(
        [1.0],
        [1.0],
        missing_y=Unpaired(["a", "b"], [5.0, 6.0]),
        missing_x=Unpaired(["c"], [7.0]),
        n_dropped=3,
    )
    stats = compute(data)
    assert (stats.n_paired, stats.n_missing_y, stats.n_missing_x, stats.n_dropped) == (
        1,
        2,
        1,
        3,
    )


def test_unpaired_records_do_not_affect_the_metrics():
    """An unpaired record has no difference to measure, so it must not move a
    statistic -- otherwise a data-quality problem would silently skew the fit."""
    paired = compute(make([10.0, 20.0], [11.0, 19.0]))
    with_holes = compute(
        make(
            [10.0, 20.0],
            [11.0, 19.0],
            missing_y=Unpaired(["z"], [1e6]),
            missing_x=Unpaired(["w"], [-1e6]),
            n_dropped=5,
        )
    )
    assert paired.rmse == with_holes.rmse
    assert paired.bias == with_holes.bias
    assert paired.r2 == with_holes.r2


def test_format_lines_skips_unknown_metrics_and_renders_tolerances():
    stats = compute(make([10.0, 20.0], [11.0, 19.0]), Tolerance(reltol=0.10))
    lines = format_lines(stats, ("n", "rmse", "not_a_metric"))
    assert lines[0] == "n: 2"
    assert any(line.startswith("RMSE:") for line in lines)
    assert not any("not_a_metric" in line for line in lines)
    assert any("within ±10%" in line for line in lines)


def test_no_tolerance_means_no_tolerance_line():
    lines = format_lines(compute(make([10.0, 20.0], [11.0, 19.0])), ("n",))
    assert not any("within" in line for line in lines)


def test_summarize_nulls_mentions_only_what_is_present():
    stats = compute(make([1.0], [1.0], missing_y=Unpaired(["a"], [2.0])))
    text = summarize_nulls(stats, "reference", "measured")
    assert "1 paired" in text
    assert "1 missing measured" in text
    assert "missing reference" not in text
    assert "neither" not in text
