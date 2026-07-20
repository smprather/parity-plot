# tests/designer/test_selection_parse.py
from __future__ import annotations

import pytest

from parity_plot.designer.selection import range_from_selection


def test_a_box_selection_uses_its_x_bounds():
    """Box select is the common case; Plotly reports the dragged rectangle."""
    args = {"range": {"x": [10.0, 90.0], "y": [0.0, 100.0]}}
    assert range_from_selection(args) == (10.0, 90.0)


def test_box_bounds_are_normalised_when_dragged_right_to_left():
    """Dragging leftwards gives a reversed pair; a range must be low-to-high."""
    args = {"range": {"x": [90.0, 10.0], "y": [0.0, 100.0]}}
    assert range_from_selection(args) == (10.0, 90.0)


def test_a_lasso_selection_uses_the_extent_of_its_outline():
    args = {"lassoPoints": {"x": [30.0, 55.0, 12.0], "y": [1.0, 2.0, 3.0]}}
    assert range_from_selection(args) == (12.0, 55.0)


def test_falls_back_to_the_selected_points():
    """Some selections report points but neither a range nor a lasso."""
    args = {"points": [{"x": 5.0}, {"x": 25.0}, {"x": 15.0}]}
    assert range_from_selection(args) == (5.0, 25.0)


def test_a_box_range_wins_over_the_points_it_contains():
    """The dragged window is what the user chose, not the points that landed
    in it -- an empty region still means that region."""
    args = {"range": {"x": [0.0, 100.0]}, "points": [{"x": 50.0}]}
    assert range_from_selection(args) == (0.0, 100.0)


@pytest.mark.parametrize("args", [None, {}, {"points": []}, {"range": {}}])
def test_an_empty_selection_is_no_range(args):
    """Clearing the selection must clear the filter, not freeze the last one."""
    assert range_from_selection(args) is None


def test_non_numeric_values_are_ignored():
    assert range_from_selection({"points": [{"x": "abc"}, {"x": 4.0}]}) == (4.0, 4.0)


def test_points_without_an_x_are_ignored():
    """Rug marks on the y axis have no x to contribute."""
    assert range_from_selection({"points": [{"y": 3.0}, {"x": 8.0}]}) == (8.0, 8.0)


def test_a_selection_with_nothing_usable_is_no_range():
    assert range_from_selection({"points": [{"y": 3.0}]}) is None