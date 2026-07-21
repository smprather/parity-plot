"""The empty-start -> open-file -> encode flow the Phase 3 panels drive."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.designer.panels.data_panel import column_options
from parity_plot.designer.panels.encoding import build_encoding_panel  # noqa: F401 (import guard)
from parity_plot.designer.state import DesignerState
from parity_plot.encoding import Encoding


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_a_fresh_designer_is_empty():
    state = DesignerState(config=ParityConfig())
    assert not state.has_data
    assert state.counts() == (0, 0)
    # The empty plot still builds -- just the parity line, no points.
    fig = state.figure()
    assert fig is not None
    assert not any(t.name and t.name.startswith("paired") for t in fig.data)


def test_opening_a_file_populates_the_plot(tmp_path):
    f = write(tmp_path, "d.csv", "id,reference,test\nA1,10,11\nA2,20,22\n")
    state = DesignerState(config=ParityConfig())

    opts = column_options((f,))
    assert opts["ref"] == ["d.csv:reference", "d.csv:test"]

    ok = state.set_data_source(files=(f,), ref="d.csv:reference", test="d.csv:test")
    assert ok, state.last_error
    assert state.has_data
    assert state.counts() == (2, 2)
    assert any(t.name and t.name.startswith("paired") for t in state.figure().data)


def test_group_column_enables_group_encoding(tmp_path):
    f = write(tmp_path, "d.csv",
              "id,reference,test,batch\nA1,10,11,x\nA2,20,22,y\nA3,30,29,x\n")
    state = DesignerState(config=ParityConfig())
    state.set_data_source(files=(f,), ref="d.csv:reference", test="d.csv:test",
                          group="d.csv:batch")

    assert state.update("plot", encoding=Encoding(color_by="group"))
    # One trace per group value (x, y) plus the tolerance/parity lines.
    paired = [t for t in state.figure().data if t.name in ("x", "y")]
    assert len(paired) == 2


def test_incomplete_source_stays_empty_without_erroring(tmp_path):
    """Opening a file but not yet picking ref/test is not an error."""
    f = write(tmp_path, "d.csv", "id,reference,test\nA1,10,11\n")
    state = DesignerState(config=ParityConfig())

    # files set but no ref/test -> load fails, state stays empty, no crash.
    state.set_data_source(files=(f,))
    assert not state.has_data
    assert state.figure() is not None


def test_removing_the_last_file_returns_to_empty(tmp_path):
    f = write(tmp_path, "d.csv", "id,reference,test\nA1,10,11\n")
    state = DesignerState(config=ParityConfig())
    state.set_data_source(files=(f,), ref="d.csv:reference", test="d.csv:test")
    assert state.has_data

    state.set_data_source(files=(), ref=None, test=None)
    assert not state.has_data
    assert state.counts() == (0, 0)
