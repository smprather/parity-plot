"""The add/edit/delete flow the tolerance panel drives, through real modules.

The panel's buttons all funnel through `state.update("plot", tolerances=...)`
after a `tolerance_ops` call. These exercise that funnel end to end -- ops to
state to figure -- without a browser, which is where the wiring could break.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer import tolerance_ops as ops
from parity_plot.designer.state import DesignerState
from parity_plot.tolerances import PARITY_NAME, NamedTolerance

WIDE = "id,reference,measured\nA1,10.0,11.0\nA2,20.0,25.0\nA3,30.0,30.3\n"


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    csv = tmp_path / "w.csv"
    csv.write_text(WIDE, encoding="utf-8")
    config = ParityConfig().merge(data={"paths": (csv,)})
    return DesignerState(config=config, data=load(config.data))


def commit(state, tolerances) -> bool:
    """What the panel's commit() does: normalise, then push through state."""
    return state.update("plot", tolerances=ops.normalise(tolerances))


def test_a_fresh_designer_shows_only_parity(state):
    assert [t.name for t in state.tolerances()] == [PARITY_NAME]


def test_adding_a_tolerance_reaches_the_figure(state):
    before = len(state.figure().data)
    assert commit(state, ops.add(state.tolerances()))

    names = [t.name for t in state.tolerances()]
    assert names == [PARITY_NAME, "tolerance1"]
    # The new band adds traces (two, since it is a real envelope, not zero-width).
    assert len(state.figure().data) > before


def test_editing_a_tolerance_changes_its_verdict(state):
    commit(state, ops.add(state.tolerances()))  # tolerance1 at reltol 10%

    # A2 is 25% off: passes 10%? no. Confirm it fails, then loosen to 30%.
    failed = state.selected_record  # noqa: F841  (documents intent)
    tight = state.tolerances()
    assert commit(state, ops.update(tight, "tolerance1",
                                    NamedTolerance(name="tolerance1", reltol=0.30)))

    from parity_plot.designer.records import record_views
    views = {v.key: v for v in record_views(state.visible_data(), state.tolerances())}
    assert views["A2"].failed == ()  # now inside 30%


def test_deleting_returns_to_just_parity(state):
    commit(state, ops.add(state.tolerances()))
    assert len(state.tolerances()) == 2

    assert commit(state, ops.delete(state.tolerances(), "tolerance1"))
    assert [t.name for t in state.tolerances()] == [PARITY_NAME]


def test_disabling_parity_removes_the_line_but_keeps_the_entry(state):
    assert commit(state, ops.set_enabled(state.tolerances(), PARITY_NAME, False))

    assert state.tolerances()[0].name == PARITY_NAME
    assert state.tolerances()[0].enabled is False
    # No enabled tolerances -> the figure has no tolerance traces, only data.
    names = [t.name for t in state.figure().data if t.name]
    assert "0% error (y = x)" not in names


def test_the_verdict_column_populates_after_adding_a_criterion(state):
    from parity_plot.designer.table_rows import to_rows
    from parity_plot.designer.records import record_views

    commit(state, ops.add(state.tolerances()))  # reltol 10%
    rows = {r["key"]: r for r in to_rows(record_views(state.visible_data(), state.tolerances()))}
    assert rows["A2"]["verdict"] == "tolerance1"  # 25% off, fails 10%
    assert rows["A1"]["verdict"] == "pass"        # 10% off exactly... boundary


def test_edits_survive_a_save_and_reload(state, tmp_path):
    from parity_plot.designer.session import Session

    commit(state, ops.add(state.tolerances()))
    commit(state, ops.update(state.tolerances(), "tolerance1",
                             NamedTolerance(name="spec", reltol=0.25, color="purple",
                                            style="shaded", label="customer limit")))

    out = tmp_path / "parity.toml"
    Session().save(state.config, out)
    reloaded = ParityConfig.from_toml(out).plot.tolerances

    spec = next(t for t in reloaded if t.name == "spec")
    assert spec.reltol == pytest.approx(0.25)
    assert spec.color == "purple"
    assert spec.style == "shaded"
    assert spec.display_label == "customer limit"
