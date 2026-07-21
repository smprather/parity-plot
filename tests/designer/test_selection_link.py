# tests/designer/test_selection_link.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.app import select_record
from parity_plot.designer.state import DesignerState

WIDE = "id,reference,test\nA1,10.0,11.0\nA2,20.0,21.0\nA3,30.0,\n"


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    csv = tmp_path / "wide.csv"
    csv.write_text(WIDE, encoding="utf-8")
    config = ParityConfig().merge(
        data={"files": (csv,), "ref": "wide.csv:reference",
              "test": "wide.csv:test", "join": "id"}
    )
    return DesignerState(config=config, data=load(config.data))


def test_selecting_sets_the_one_shared_selection(state):
    """Plot and table both route through here, so they cannot disagree."""
    calls = []
    select_record(state, "A2", lambda: calls.append("a"), lambda: calls.append("b"))

    assert state.selection == "A2"
    assert calls == ["a", "b"]


def test_selecting_none_clears_it(state):
    state.selection = "A1"
    select_record(state, None)
    assert state.selection is None


def test_reselecting_the_same_record_is_harmless(state):
    select_record(state, "A1")
    select_record(state, "A1")
    assert state.selection == "A1"


def test_every_refresh_callback_runs_even_if_one_is_none(state):
    ran = []
    select_record(state, "A1", None, lambda: ran.append(1))
    assert ran == [1]