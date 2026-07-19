from __future__ import annotations

import pytest

from parity_plot.tolerance import Tolerance, parse_reltol


@pytest.mark.parametrize(
    "given, expected",
    [
        (0.1, 0.1),
        ("0.1", 0.1),
        (".25", 0.25),
        ("10pct", 0.1),
        ("10 pct", 0.1),
        ("10PCT", 0.1),
        ("  10pct  ", 0.1),
        ("10%", 0.1),
        ("2.5pct", 0.025),
        ("100pct", 1.0),
    ],
)
def test_relative_tolerance_is_a_ratio_unless_marked_percent(given, expected):
    assert parse_reltol(given) == pytest.approx(expected)


def test_a_bare_number_is_never_assumed_to_be_percent():
    """Guessing the unit is the mistake a tolerance spec exists to prevent."""
    assert parse_reltol(10) == 10.0
    assert parse_reltol("10") == 10.0


@pytest.mark.parametrize("given", ["", "abc", "pct", "10 percent", "1e", True])
def test_unreadable_tolerances_are_rejected(given):
    with pytest.raises(ValueError):
        parse_reltol(given)


def test_error_message_shows_both_accepted_spellings():
    with pytest.raises(ValueError, match="0.1.*10pct"):
        parse_reltol("wat")


def test_half_width_absolute_does_not_scale():
    tol = Tolerance(abstol=2.0)
    assert tol.half_width(0.0) == 2.0
    assert tol.half_width(1000.0) == 2.0


def test_half_width_relative_scales_with_magnitude():
    tol = Tolerance(reltol=0.1)
    assert tol.half_width(0.0) == 0.0
    assert tol.half_width(50.0) == pytest.approx(5.0)
    assert tol.half_width(-50.0) == pytest.approx(5.0)  # symmetric about zero


def test_half_width_takes_the_looser_spec():
    tol = Tolerance(abstol=2.0, reltol=0.1)  # crossover at 20
    assert tol.half_width(5.0) == 2.0  # absolute floor governs
    assert tol.half_width(20.0) == pytest.approx(2.0)  # they meet
    assert tol.half_width(100.0) == pytest.approx(10.0)  # relative governs


def test_crossover_only_exists_when_both_specs_do():
    assert Tolerance(abstol=2.0, reltol=0.1).crossover == pytest.approx(20.0)
    assert Tolerance(abstol=2.0).crossover is None
    assert Tolerance(reltol=0.1).crossover is None
    assert Tolerance().crossover is None


def test_empty_tolerance_is_falsy_and_permits_nothing():
    tol = Tolerance()
    assert not tol
    assert tol.half_width(100.0) == 0.0
    assert tol.label() == ""


@pytest.mark.parametrize(
    "tol, expected",
    [
        (Tolerance(abstol=2.0), "±2"),
        (Tolerance(abstol=0.5), "±0.5"),
        (Tolerance(reltol=0.1), "±10%"),
        (Tolerance(reltol=0.025), "±2.5%"),
        (Tolerance(abstol=2.0, reltol=0.1), "±max(2, 10%)"),
    ],
)
def test_labels_quote_the_spec_in_its_own_units(tol, expected):
    assert tol.label() == expected


def test_vertices_include_the_origin_and_both_crossovers():
    tol = Tolerance(abstol=2.0, reltol=0.1)  # crossover at |x| = 20
    assert tol.vertices(-100.0, 100.0) == [-100.0, -20.0, 0.0, 20.0, 100.0]


def test_vertices_skip_crossovers_outside_the_range():
    tol = Tolerance(abstol=2.0, reltol=0.1)
    assert tol.vertices(50.0, 100.0) == [50.0, 100.0]


def test_envelope_brackets_the_identity_line():
    xs, upper, lower = Tolerance(abstol=2.0).envelope(0.0, 10.0)
    assert upper == pytest.approx([x + 2.0 for x in xs])
    assert lower == pytest.approx([x - 2.0 for x in xs])


def test_log_envelope_drops_points_a_log_axis_cannot_show():
    """A lower limit at or below zero has no place on a log axis."""
    xs, _, lower = Tolerance(abstol=100.0).log_envelope(0.0, 3.0, samples=50)
    assert all(v > 0 for v in lower)
    assert all(x > 0 for x in xs)


def test_contains_matches_half_width():
    tol = Tolerance(abstol=2.0, reltol=0.1)
    assert tol.contains(100.0, 109.0)
    assert not tol.contains(100.0, 111.0)
    assert tol.contains(1.0, 2.9)
    assert not tol.contains(1.0, 3.5)
