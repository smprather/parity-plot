"""``compute_view`` is the refresh's work, moved off the event loop.

It must show exactly what the synchronous path shows -- ``DesignerState.figure``,
``visible_records`` and ``counts`` are what the golden tests hold to the CLI --
while doing it in one pass a worker thread can run. These pin that equivalence,
the failure path, and the table order it builds.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import from_sequences
from parity_plot.designer.filters import FilterSet
from parity_plot.designer.state import DesignerState
from parity_plot.designer.table_rows import sort_rows, to_rows
from parity_plot.designer.view import compute_view, placeholder_figure
from parity_plot.tolerances import NamedTolerance, with_parity


def as_json(figure) -> str:
    """What the browser receives: the view's tuples are JSON arrays too."""
    return json.dumps(figure, sort_keys=True)


@pytest.fixture
def state() -> DesignerState:
    data = from_sequences(
        x=[1.0, 2.0, 3.0, 4.0, None, 6.0],
        y=[1.1, 2.6, None, 4.1, 5.0, 5.0],
        keys=["a", "b", "c", "d", "e", "f"],
    )
    spec = NamedTolerance(name="spec", reltol=0.1)
    config = ParityConfig()
    config = replace(config, plot=replace(config.plot, tolerances=with_parity((spec,))))
    return DesignerState(config=config, data=data)


@pytest.mark.parametrize(
    "filters",
    [
        FilterSet(),
        FilterSet(outside_tolerance_only=True),
        FilterSet(show_unpaired=False),
        FilterSet(x_range=(1.5, 4.5)),
    ],
    ids=["unfiltered", "failures-only", "paired-only", "brushed"],
)
def test_the_view_is_what_the_synchronous_path_shows(state, filters):
    state.filters = filters
    view = compute_view(state.view_inputs())

    assert view.error is None
    assert as_json(view.figure) == as_json(state.figure().to_plotly_json())
    assert view.rows == to_rows(state.visible_records())
    assert (view.showing, view.total) == state.counts()


def test_rows_arrive_in_the_requested_order(state):
    view = compute_view(state.view_inputs(("error", True)))
    assert view.rows == sort_rows(to_rows(state.visible_records()), "error", True)
    assert view.rows_by_key == {row["key"]: row for row in view.rows}


def test_a_figure_that_fails_to_build_reports_why_and_keeps_the_rows(state):
    """The app keeps the last figure on screen; the view only says what failed."""
    state.config = replace(
        state.config, plot=replace(state.config.plot, legend="nonsense")
    )
    view = compute_view(state.view_inputs())

    assert view.figure is None
    assert view.error
    assert view.rows == to_rows(state.visible_records())


def test_no_data_is_an_empty_view_not_an_error():
    view = compute_view(DesignerState(config=ParityConfig()).view_inputs())
    assert view.error is None
    assert view.figure is not None
    assert (view.rows, view.showing, view.total) == ([], 0, 0)


def test_the_placeholder_is_a_fresh_dict_each_time():
    """The plot widget keeps the dict it is given; sharing one would leak edits."""
    first = placeholder_figure()
    first["layout"]["title"] = "mutated"
    assert "title" not in placeholder_figure()["layout"]


def test_the_figure_holds_no_lists(state):
    """Every list would be wrapped in an observable, on the loop, per paint."""
    view = compute_view(state.view_inputs())
    stack = [view.figure]
    while stack:
        item = stack.pop()
        assert not isinstance(item, list)
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, tuple):
            stack.extend(item)
