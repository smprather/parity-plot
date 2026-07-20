# tests/designer/test_inspector.py
from __future__ import annotations

import pytest

from parity_plot.designer.inspector_helpers import describe  # see note below
from parity_plot.designer.records import RecordView


def labelled(view):
    return dict(describe(view))


def test_nothing_selected_says_so():
    assert describe(None) == [("", "Click a point to inspect it")]


def test_a_paired_record_shows_both_values_and_the_error():
    view = RecordView("A1", 10.0, 11.0, 1.0, 0.1, "paired", None)
    fields = labelled(view)
    assert fields["Record"] == "A1"
    assert fields["Reference"] == "10"
    assert fields["Measured"] == "11"
    assert fields["Error"] == "+1"
    assert fields["Relative error"] == "+10%"


def test_an_unpaired_record_says_what_is_missing():
    view = RecordView("A2", 20.0, None, None, None, "missing y", None)
    fields = labelled(view)
    assert fields["Measured"] == "missing"
    assert fields["Error"] == "n/a"
    assert "missing y" in fields["Status"]


def test_tolerance_verdict_appears_only_when_judged():
    inside = RecordView("A1", 10.0, 10.2, 0.2, 0.02, "paired", True)
    outside = RecordView("A1", 10.0, 15.0, 5.0, 0.5, "paired", False)
    unjudged = RecordView("A1", 10.0, 10.2, 0.2, 0.02, "paired", None)

    assert labelled(inside)["Tolerance"] == "within"
    assert labelled(outside)["Tolerance"] == "OUT"
    assert "Tolerance" not in labelled(unjudged)


def test_relative_error_is_omitted_when_undefined():
    view = RecordView("Z", 0.0, 1.0, 1.0, None, "paired", None)
    assert "Relative error" not in labelled(view)