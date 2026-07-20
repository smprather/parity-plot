# tests/designer/test_state_data.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.state import DesignerState
from parity_plot.tolerances import NamedTolerance

WIDE = "id,reference,measured\nA1,10.0,11.0\nA2,20.0,21.0\nA3,30.0,\n"
OTHER = "name,golden,dut\nB1,5.0,5.5\nB2,6.0,6.6\n"

WIDE_TOL = (NamedTolerance(name="spec", reltol=0.05),)


@pytest.fixture
def first(tmp_path: Path) -> Path:
    path = tmp_path / "first.csv"
    path.write_text(WIDE, encoding="utf-8")
    return path


@pytest.fixture
def second(tmp_path: Path) -> Path:
    path = tmp_path / "second.csv"
    path.write_text(OTHER, encoding="utf-8")
    return path


@pytest.fixture
def state(first) -> DesignerState:
    config = ParityConfig().merge(data={"paths": (first,)})
    return DesignerState(config=config, data=load(config.data))


def test_swapping_to_another_file_and_mapping(state, second):
    assert state.set_data_source(paths=(second,), key="name", x="golden", y="dut")

    assert state.data.n_paired == 2
    assert state.data.x_label == "golden"
    assert state.config.data.paths == (second,)
    assert state.last_error is None


def test_a_failed_load_keeps_the_dataset_that_was_working(state, tmp_path):
    """Losing the loaded data because of a typo in a column name would be a
    much worse outcome than the error message."""
    before = state.data

    assert not state.set_data_source(x="nope")

    assert state.data is before
    assert "nope" in state.last_error


def test_a_failed_load_also_leaves_the_config_alone(state):
    before = state.config
    state.set_data_source(x="nope")
    assert state.config == before


def test_a_missing_file_is_reported_not_raised(state, tmp_path):
    assert not state.set_data_source(paths=(tmp_path / "ghost.csv",))
    assert "not found" in state.last_error


def test_the_figure_follows_the_new_dataset(state, second):
    before = state.figure().to_dict()
    state.set_data_source(paths=(second,), key="name", x="golden", y="dut")
    assert state.figure().to_dict() != before


def test_selected_record_returns_the_pinned_record(state):
    state.selection = "A1"
    view = state.selected_record()
    assert view.key == "A1"
    assert view.x == 10.0 and view.y == 11.0


def test_selected_record_judges_against_the_given_tolerances(state):
    state.selection = "A1"  # 10% off
    assert state.selected_record(WIDE_TOL).failed == ("spec",)
    loose = (NamedTolerance(name="loose", reltol=0.20),)
    assert state.selected_record(loose).failed == ()


def test_selected_record_is_none_when_nothing_is_pinned(state):
    assert state.selection is None
    assert state.selected_record() is None


def test_selected_record_is_none_when_the_key_is_gone(state, second):
    """Loading a different file must not leave a dangling selection."""
    state.selection = "A1"
    state.set_data_source(paths=(second,), key="name", x="golden", y="dut")
    assert state.selected_record() is None