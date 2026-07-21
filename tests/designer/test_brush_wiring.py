# tests/designer/test_brush_wiring.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.app import apply_brush
from parity_plot.designer.filters import FilterSet
from parity_plot.designer.state import DesignerState

WIDE = (
    "id,reference,test\n"
    "A1,10.0,11.0\n"
    "A2,50.0,51.0\n"
    "A3,90.0,95.0\n"
    "A4,200.0,201.0\n"
)


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    csv = tmp_path / "wide.csv"
    csv.write_text(WIDE, encoding="utf-8")
    config = ParityConfig().merge(
        data={"files": (csv,), "ref": "wide.csv:reference",
              "test": "wide.csv:test", "join": "id"}
    )
    return DesignerState(config=config, data=load(config.data))


def test_brushing_sets_the_x_range_and_narrows_the_view(state):
    apply_brush(state, {"range": {"x": [40.0, 100.0]}})

    assert state.filters.x_range == (40.0, 100.0)
    assert [k for k in state.visible_data().keys] == ["A2", "A3"]
    assert state.counts() == (2, 4)


def test_brushing_refreshes_every_panel(state):
    calls = []
    apply_brush(state, {"range": {"x": [0.0, 1000.0]}},
                lambda: calls.append("a"), lambda: calls.append("b"))
    assert calls == ["a", "b"]


def test_a_none_refresher_is_skipped(state):
    ran = []
    apply_brush(state, {"range": {"x": [0.0, 1.0]}}, None, lambda: ran.append(1))
    assert ran == [1]


def test_an_empty_selection_clears_the_brush(state):
    """Double-clicking to deselect must restore the full view, not freeze it."""
    apply_brush(state, {"range": {"x": [40.0, 100.0]}})
    assert state.filters.x_range is not None

    apply_brush(state, None)

    assert state.filters.x_range is None
    assert state.counts() == (4, 4)


def test_brushing_leaves_the_other_filters_alone(state):
    state.filters = FilterSet(show_unpaired=False, outside_tolerance_only=True)

    apply_brush(state, {"range": {"x": [0.0, 100.0]}})

    assert state.filters.show_unpaired is False
    assert state.filters.outside_tolerance_only is True
    assert state.filters.x_range == (0.0, 100.0)


def test_brushing_never_touches_the_config(state):
    before = state.config
    apply_brush(state, {"range": {"x": [0.0, 100.0]}})
    assert state.config == before