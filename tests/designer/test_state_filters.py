# tests/designer/test_state_filters.py
from __future__ import annotations

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import from_sequences
from parity_plot.designer.filters import FilterSet
from parity_plot.designer.state import DesignerState


@pytest.fixture
def state():
    data = from_sequences(
        x=[10.0, 100.0, 50.0, 70.0, None],
        y=[11.0, 101.0, 55.0, None, 33.0],
        keys=["a", "b", "c", "d", "e"],
    )
    return DesignerState(config=ParityConfig(), data=data)


def test_by_default_everything_is_visible(state):
    assert not state.filters.is_active
    assert state.visible_data().keys == state.data.keys
    assert state.counts() == (5, 5)


def test_tolerance_comes_from_the_config(state):
    assert state.tolerance().reltol is None

    state.update("plot", reltol=0.05)
    assert state.tolerance().reltol == pytest.approx(0.05)

    state.update("plot", abstol=2.0)
    assert state.tolerance().abstol == pytest.approx(2.0)


def test_filtering_narrows_the_visible_data(state):
    state.update("plot", reltol=0.05)
    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)

    assert state.visible_data().keys == ["a", "c"]
    assert state.counts() == (2, 5)


def test_the_figure_shows_the_filtered_view(state):
    """A filtered table beside an unfiltered plot would be two answers to one
    question."""
    before = state.figure().to_dict()
    state.filters = FilterSet(show_unpaired=False)
    after = state.figure().to_dict()

    assert before != after


def test_the_statistics_follow_the_filter(state):
    state.update("plot", reltol=0.05)
    unfiltered = state.figure()

    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)
    filtered = state.figure()

    assert "3 paired" in unfiltered.layout.title.subtitle.text
    assert "2 paired" in filtered.layout.title.subtitle.text


def test_visible_records_are_judged_against_the_current_tolerance(state):
    state.update("plot", reltol=0.05)
    verdicts = {v.key: v.within for v in state.visible_records()}

    assert verdicts["a"] is False
    assert verdicts["b"] is True
    assert verdicts["d"] is None  # unpaired, never judged


def test_filters_do_not_touch_the_config(state):
    """A saved config must never encode a temporary view."""
    before = state.config
    state.filters = FilterSet(outside_tolerance_only=True, show_paired=False)
    assert state.config == before


def test_the_underlying_dataset_is_never_modified(state):
    original = list(state.data.keys)
    state.filters = FilterSet(show_paired=False)
    state.visible_data()
    assert state.data.keys == original


def test_selected_record_still_reads_the_full_dataset(state):
    """Filtering out the selected record must not make it unreadable -- the
    inspector should still describe what you clicked."""
    state.selection = "a"
    state.filters = FilterSet(show_paired=False)
    assert state.selected_record() is not None