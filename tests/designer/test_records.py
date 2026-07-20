# tests/designer/test_records.py
from __future__ import annotations

import pytest

from parity_plot.data import from_sequences
from parity_plot.designer.records import (
    RecordView,
    find_record,
    key_from_customdata,
    record_views,
)
from parity_plot.tolerance import Tolerance


@pytest.fixture
def data():
    return from_sequences(
        x=[10.0, 20.0, None, 40.0],
        y=[11.0, None, 33.0, 40.5],
        keys=["a", "b", "c", "d"],
    )


def test_one_view_per_record_including_unpaired(data):
    views = record_views(data)
    assert [v.key for v in views] == ["a", "d", "b", "c"]


def test_paired_records_carry_both_values_and_the_error(data):
    view = find_record(record_views(data), "a")
    assert (view.x, view.y) == (10.0, 11.0)
    assert view.error == pytest.approx(1.0)
    assert view.rel_error == pytest.approx(0.1)
    assert view.status == "paired"


def test_unpaired_records_have_no_error_to_report(data):
    missing_y = find_record(record_views(data), "b")
    assert missing_y.x == 20.0
    assert missing_y.y is None
    assert missing_y.error is None
    assert missing_y.rel_error is None
    assert missing_y.status == "missing y"
    assert missing_y.within is None

    missing_x = find_record(record_views(data), "c")
    assert missing_x.x is None
    assert missing_x.y == 33.0
    assert missing_x.status == "missing x"


def test_tolerance_marks_records_in_and_out(data):
    views = record_views(data, Tolerance(reltol=0.05))  # +/-5%

    assert find_record(views, "a").within is False  # 10% off
    assert find_record(views, "d").within is True  # 1.25% off


def test_without_a_tolerance_nothing_is_judged(data):
    for view in record_views(data):
        assert view.within is None


def test_relative_error_is_undefined_at_zero():
    """Dividing by a zero reference would be a division by zero, not a 0% error."""
    data = from_sequences(x=[0.0], y=[1.0], keys=["z"])
    view = record_views(data)[0]
    assert view.error == pytest.approx(1.0)
    assert view.rel_error is None


def test_find_record_returns_none_for_an_unknown_key(data):
    assert find_record(record_views(data), "nope") is None


@pytest.mark.parametrize(
    "customdata, expected",
    [
        (["a1", 0.5], "a1"),          # paired trace: (key, diff)
        (("a1", 0.5), "a1"),
        ("a1", "a1"),                  # rug trace: bare key
        ([], None),
        (None, None),
    ],
)
def test_key_from_customdata_handles_both_trace_shapes(customdata, expected):
    """The paired trace carries (key, diff); the rug traces carry a bare key."""
    assert key_from_customdata(customdata) == expected