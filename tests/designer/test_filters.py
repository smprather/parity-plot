# tests/designer/test_filters.py
from __future__ import annotations

import pytest

from parity_plot.data import from_sequences
from parity_plot.designer.filters import FilterSet
from parity_plot.tolerance import Tolerance


@pytest.fixture
def data():
    # a,b,c paired (a and c are 10% off, b is 1% off); d missing y; e missing x
    return from_sequences(
        x=[10.0, 100.0, 50.0, 70.0, None],
        y=[11.0, 101.0, 55.0, None, 33.0],
        keys=["a", "b", "c", "d", "e"],
    )


def test_the_default_filter_changes_nothing(data):
    """The golden tests compare an unfiltered designer against the CLI; if the
    default filter altered anything they would fail, and rightly so."""
    result = FilterSet().apply(data)

    assert result.keys == data.keys
    assert result.x == data.x
    assert result.y == data.y
    assert result.missing_y.keys == data.missing_y.keys
    assert result.missing_x.keys == data.missing_x.keys
    assert result.n_dropped == data.n_dropped


def test_the_default_filter_is_not_active():
    assert not FilterSet().is_active
    assert FilterSet(show_paired=False).is_active
    assert FilterSet(outside_tolerance_only=True).is_active
    assert FilterSet(x_range=(0.0, 1.0)).is_active


def test_hiding_paired_records_leaves_only_the_unpaired(data):
    result = FilterSet(show_paired=False).apply(data)

    assert result.keys == []
    assert result.missing_y.keys == ["d"]
    assert result.missing_x.keys == ["e"]


def test_hiding_unpaired_records_leaves_only_the_paired(data):
    result = FilterSet(show_unpaired=False).apply(data)

    assert result.keys == ["a", "b", "c"]
    assert len(result.missing_y) == 0
    assert len(result.missing_x) == 0


def test_outside_tolerance_keeps_only_the_failures(data):
    result = FilterSet(outside_tolerance_only=True).apply(data, Tolerance(reltol=0.05))

    assert result.keys == ["a", "c"]  # 10% off; b is 1% off and passes


def test_outside_tolerance_does_nothing_without_a_tolerance(data):
    """With no spec to fail, nothing can be outside it."""
    result = FilterSet(outside_tolerance_only=True).apply(data, None)
    assert result.keys == ["a", "b", "c"]


def test_outside_tolerance_leaves_unpaired_records_to_the_other_switch(data):
    """An unpaired record was never judged, so 'outside tolerance' has no
    opinion about it -- show_unpaired governs it instead."""
    result = FilterSet(outside_tolerance_only=True).apply(data, Tolerance(reltol=0.05))
    assert result.missing_y.keys == ["d"]
    assert result.missing_x.keys == ["e"]

    both = FilterSet(outside_tolerance_only=True, show_unpaired=False).apply(
        data, Tolerance(reltol=0.05)
    )
    assert len(both.missing_y) == 0


def test_x_range_keeps_records_inside_the_window(data):
    result = FilterSet(x_range=(40.0, 80.0)).apply(data)

    assert result.keys == ["c"]          # x = 50
    assert result.missing_y.keys == ["d"]  # x = 70, known
    assert result.missing_x.keys == []     # no x at all, so not in any window


def test_x_range_bounds_are_inclusive(data):
    assert FilterSet(x_range=(10.0, 10.0)).apply(data).keys == ["a"]


def test_filters_combine(data):
    result = FilterSet(outside_tolerance_only=True, show_unpaired=False).apply(
        data, Tolerance(reltol=0.05)
    )
    assert result.keys == ["a", "c"]
    assert len(result.missing_y) == 0
    assert len(result.missing_x) == 0


def test_labels_and_dropped_count_survive_filtering(data):
    result = FilterSet(show_paired=False).apply(data)
    assert result.x_label == data.x_label
    assert result.y_label == data.y_label
    assert result.n_dropped == data.n_dropped


def test_filtering_never_reclassifies_a_record(data):
    """Hiding a record is a filter; turning an unpaired one into a paired one
    would be a bug that silently invents a measurement."""
    result = FilterSet(x_range=(0.0, 1000.0)).apply(data)
    for key, x, y in zip(result.keys, result.x, result.y):
        assert x is not None and y is not None
    assert "d" not in result.keys
    assert "e" not in result.keys