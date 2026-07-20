# tests/designer/test_state_filters.py
from __future__ import annotations

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import from_sequences
from parity_plot.designer.filters import FilterSet
from parity_plot.designer.state import DesignerState
from parity_plot.tolerances import NamedTolerance

SPEC_5PCT = [NamedTolerance(name="spec", reltol=0.05)]


def with_spec(state: DesignerState, reltol: float) -> DesignerState:
    """Replace the config's pass/fail tolerance list with one +/-reltol spec.

    Goes through ``merge`` so the built-in parity entry is preserved (merge
    re-adds it via ``with_parity``); ``replace`` would drop it."""
    if reltol:
        state.config = state.config.merge(
            plot={"tolerances": [NamedTolerance(name="spec", reltol=reltol)]}
        )
    else:
        state.config = state.config.merge(plot={"tolerances": []})
    return state


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


def test_tolerances_come_from_the_config(state):
    # The default config carries only the built-in parity entry (informational).
    assert [t.name for t in state.tolerances()] == ["parity"]

    with_spec(state, reltol=0.05)
    # merge re-adds the parity entry first via with_parity.
    assert [t.name for t in state.tolerances()] == ["parity", "spec"]
    assert state.tolerances()[-1].reltol == pytest.approx(0.05)


def test_filtering_narrows_the_visible_data(state):
    with_spec(state, reltol=0.05)
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
    with_spec(state, reltol=0.05)
    unfiltered = state.figure()

    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)
    filtered = state.figure()

    assert "3 paired" in unfiltered.layout.title.subtitle.text
    assert "2 paired" in filtered.layout.title.subtitle.text


def test_visible_records_are_judged_against_the_current_tolerances(state):
    with_spec(state, reltol=0.05)
    verdicts = {v.key: v.failed for v in state.visible_records()}

    assert verdicts["a"] == ("spec",)   # 10% off
    assert verdicts["b"] == ()          # 1% off, judged and passed
    assert verdicts["d"] is None        # unpaired, never judged


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