# tests/test_tolerances.py
from __future__ import annotations

import pytest

from parity_plot.tolerance import Tolerance
from parity_plot.tolerances import (
    NamedTolerance,
    ToleranceError,
    default_name,
    failures,
    pass_fail,
    require_unique_names,
    verdict_text,
)


def test_geometry_is_delegated_not_reimplemented():
    """All the math already exists in Tolerance; this only names it."""
    named = NamedTolerance(name="t1", abstol=2.0, reltol=0.1)
    assert named.tolerance == Tolerance(abstol=2.0, reltol=0.1)
    assert named.contains(100.0, 105.0) is named.tolerance.contains(100.0, 105.0)


def test_at_least_one_bound_is_required():
    with pytest.raises(ToleranceError, match="abstol or reltol"):
        NamedTolerance(name="t1")


@pytest.mark.parametrize("kwargs", [{"abstol": 2.0}, {"reltol": 0.1}, {"abstol": 2.0, "reltol": 0.1}])
def test_either_bound_alone_is_enough(kwargs):
    assert NamedTolerance(name="t1", **kwargs)


@pytest.mark.parametrize("name", ["upper spec", "customer limit", "±3σ", "spec (2026)"])
def test_names_are_freeform(name):
    """A name is display-facing as much as an identifier, so spaces and
    punctuation are allowed -- only emptiness is rejected."""
    assert NamedTolerance(name=name, abstol=1.0).name == name


def test_names_may_not_be_empty():
    with pytest.raises(ToleranceError, match="name"):
        NamedTolerance(name="", abstol=1.0)
    with pytest.raises(ToleranceError, match="name"):
        NamedTolerance(name="   ", abstol=1.0)


@pytest.mark.parametrize("kwargs", [{"abstol": 0}, {"abstol": -1}, {"reltol": 0}, {"reltol": -0.5}])
def test_bounds_must_be_positive(kwargs):
    with pytest.raises(ToleranceError, match="positive"):
        NamedTolerance(name="t1", **kwargs)


def test_kind_and_style_are_checked():
    with pytest.raises(ToleranceError, match="kind"):
        NamedTolerance(name="t1", abstol=1.0, kind="maybe")
    with pytest.raises(ToleranceError, match="style"):
        NamedTolerance(name="t1", abstol=1.0, style="dotted")


def test_label_defaults_to_the_spec():
    assert NamedTolerance(name="t1", reltol=0.1).display_label == "±10%"
    assert NamedTolerance(name="t1", abstol=2.0, reltol=0.1).display_label == "±max(2, 10%)"


def test_the_literal_string_auto_also_means_derive_it():
    assert NamedTolerance(name="t1", reltol=0.1, label="auto").display_label == "±10%"


def test_a_manual_label_is_used_verbatim():
    named = NamedTolerance(name="t1", reltol=0.1, label="customer limit")
    assert named.display_label == "customer limit"


def test_a_manual_label_may_contain_spaces():
    """Unlike the name, a label is display text and is never parsed."""
    assert NamedTolerance(name="t1", abstol=1.0, label="upper spec limit").display_label


def test_editing_a_bound_does_not_change_the_name():
    """The table lists failed *names*; a name that drifted would silently
    re-point at a different threshold."""
    from dataclasses import replace

    original = NamedTolerance(name="tolerance1", reltol=0.1)
    edited = replace(original, reltol=0.25)
    assert edited.name == "tolerance1"
    assert edited.display_label == "±25%"  # the label follows, the name does not


def test_pass_is_the_default_kind():
    assert NamedTolerance(name="t1", abstol=1.0).is_pass_fail
    assert not NamedTolerance(name="t1", abstol=1.0, kind="info").is_pass_fail


def test_colour_defaults_by_kind():
    assert NamedTolerance(name="t1", abstol=1.0).color_token == "red"
    assert NamedTolerance(name="t1", abstol=1.0, kind="info").color_token == "yellow"
    assert NamedTolerance(name="t1", abstol=1.0, color="purple").color_token == "purple"


def test_default_name_counts_up_past_taken_ones():
    assert default_name([]) == "tolerance1"
    assert default_name(["tolerance1"]) == "tolerance2"
    assert default_name(["tolerance1", "tolerance3"]) == "tolerance2"
    assert default_name(["spec", "tight"]) == "tolerance1"


def test_duplicate_names_are_rejected():
    """Two tolerances called the same thing make the failure list meaningless."""
    tols = [NamedTolerance(name="t1", abstol=1.0), NamedTolerance(name="t1", reltol=0.1)]
    with pytest.raises(ToleranceError, match="duplicate"):
        require_unique_names(tols)


def test_unique_names_pass():
    require_unique_names([NamedTolerance(name="a", abstol=1.0), NamedTolerance(name="b", abstol=2.0)])


def test_pass_fail_selects_only_criteria():
    tols = [
        NamedTolerance(name="spec", reltol=0.1),
        NamedTolerance(name="ref", reltol=0.25, kind="info"),
        NamedTolerance(name="tight", abstol=1.0),
    ]
    assert [t.name for t in pass_fail(tols)] == ["spec", "tight"]


def test_failures_names_every_criterion_the_point_breaks():
    tols = [
        NamedTolerance(name="spec", reltol=0.10),
        NamedTolerance(name="tight", reltol=0.01),
        NamedTolerance(name="ref", reltol=0.001, kind="info"),
    ]
    # 5% off: passes spec, fails tight; ref is info and never judged.
    assert failures(tols, 100.0, 105.0) == ("tight",)
    # 50% off: fails both criteria.
    assert failures(tols, 100.0, 150.0) == ("spec", "tight")
    # exact: fails nothing.
    assert failures(tols, 100.0, 100.0) == ()


def test_failures_preserves_declaration_order():
    tols = [
        NamedTolerance(name="zebra", reltol=0.01),
        NamedTolerance(name="alpha", reltol=0.01),
    ]
    assert failures(tols, 100.0, 200.0) == ("zebra", "alpha")


def test_failures_with_no_criteria_is_empty():
    assert failures([NamedTolerance(name="ref", reltol=0.1, kind="info")], 1.0, 99.0) == ()
    assert failures([], 1.0, 99.0) == ()


def test_verdict_text_reads_as_the_table_column_does():
    assert verdict_text(()) == "pass"
    assert verdict_text(("spec",)) == "spec"
    assert verdict_text(("spec", "tight")) == "spec, tight"