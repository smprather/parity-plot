from __future__ import annotations

from dataclasses import replace

import pytest

from parity_plot.designer import tolerance_ops as ops
from parity_plot.tolerances import PARITY_NAME, NamedTolerance, parity


def names(tols):
    return [t.name for t in tols]


@pytest.fixture
def tols():
    return (
        parity(),
        NamedTolerance(name="spec", reltol=0.10),
        NamedTolerance(name="tight", abstol=2.0),
    )


def test_add_appends_a_named_valid_entry(tols):
    result = ops.add(tols)
    assert names(result) == [PARITY_NAME, "spec", "tight", "tolerance1"]
    assert result[-1].reltol == pytest.approx(0.10)  # a visible starting band


def test_add_counts_around_existing_auto_names():
    result = ops.add((parity(), NamedTolerance(name="tolerance1", abstol=1.0)))
    assert result[-1].name == "tolerance2"


def test_delete_removes_by_name(tols):
    assert names(ops.delete(tols, "spec")) == [PARITY_NAME, "tight"]


def test_delete_refuses_the_parity_line(tols):
    with pytest.raises(ValueError, match="parity"):
        ops.delete(tols, PARITY_NAME)


def test_update_replaces_in_place(tols):
    edited = NamedTolerance(name="spec", reltol=0.25, color="purple")
    result = ops.update(tols, "spec", edited)
    assert names(result) == [PARITY_NAME, "spec", "tight"]  # position kept
    assert result[1].reltol == pytest.approx(0.25)


def test_update_survives_a_rename(tols):
    """Editing by the old name means a rename still lands in the right slot."""
    edited = NamedTolerance(name="renamed", reltol=0.10)
    result = ops.update(tols, "spec", edited)
    assert names(result) == [PARITY_NAME, "renamed", "tight"]


def test_set_enabled_toggles_one_entry(tols):
    result = ops.set_enabled(tols, "spec", False)
    assert result[1].enabled is False
    assert result[2].enabled is True


def test_parity_can_be_disabled(tols):
    """Disabling parity is how the reference line is hidden."""
    result = ops.set_enabled(tols, PARITY_NAME, False)
    assert result[0].enabled is False


def test_rename_is_free_for_an_unused_name(tols):
    assert ops.rename_is_free(tols, "spec", "brandnew")
    assert not ops.rename_is_free(tols, "spec", "tight")


def test_rename_to_its_own_name_is_allowed(tols):
    assert ops.rename_is_free(tols, "spec", "spec")


def test_normalise_restores_parity_to_the_front():
    stray = (NamedTolerance(name="spec", reltol=0.1),)
    assert names(ops.normalise(stray)) == [PARITY_NAME, "spec"]


def test_normalise_keeps_a_customised_parity(tols):
    disabled = replace(parity(), enabled=False)
    result = ops.normalise((NamedTolerance(name="spec", reltol=0.1), disabled))
    assert result[0].name == PARITY_NAME
    assert result[0].enabled is False
