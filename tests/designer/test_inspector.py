# tests/designer/test_inspector.py
from __future__ import annotations

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
    assert fields["Test"] == "11"
    assert fields["Error"] == "+1"
    assert fields["Relative error"] == "+10%"


def test_an_unpaired_record_says_what_is_missing():
    view = RecordView("A2", 20.0, None, None, None, "missing y", None)
    fields = labelled(view)
    assert fields["Test"] == "missing"
    assert fields["Error"] == "n/a"
    assert "missing y" in fields["Status"]


def test_a_passed_record_says_pass():
    inside = RecordView("A1", 10.0, 10.2, 0.2, 0.02, "paired", ())
    assert labelled(inside)["Verdict"] == "pass"


def test_a_failed_record_lists_each_broken_criterion():
    outside = RecordView("A1", 10.0, 15.0, 5.0, 0.5, "paired", ("spec", "tight"))
    fields = labelled(outside)
    assert fields["spec"] == "fail"
    assert fields["tight"] == "fail"
    assert "Verdict" not in fields


def test_an_unjudged_record_shows_no_verdict():
    unjudged = RecordView("A1", 10.0, 10.2, 0.2, 0.02, "paired", None)
    assert "Verdict" not in labelled(unjudged)
    assert "Tolerance" not in labelled(unjudged)


def test_relative_error_is_omitted_when_undefined():
    view = RecordView("Z", 0.0, 1.0, 1.0, None, "paired", None)
    assert "Relative error" not in labelled(view)