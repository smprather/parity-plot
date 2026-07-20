"""Phase 3 end to end: filter to the failures and find the worst offender."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.filters import FilterSet
from parity_plot.designer.panels.table import summary_text
from parity_plot.designer.state import DesignerState
from parity_plot.designer.table_rows import to_rows

# A1 +10%, A2 +0.5%, A3 +25%, A4 unpaired
WIDE = (
    "id,reference,measured\n"
    "A1,10.0,11.0\n"
    "A2,100.0,100.5\n"
    "A3,40.0,50.0\n"
    "A4,70.0,\n"
)


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    csv = tmp_path / "wide.csv"
    csv.write_text(WIDE, encoding="utf-8")
    config = ParityConfig().merge(data={"paths": (csv,)})
    return DesignerState(config=config, data=load(config.data))


def test_filter_to_failures_then_sort_by_error(state):
    state.update("plot", reltol=0.05)
    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)

    rows = to_rows(state.visible_records())
    worst = max(rows, key=lambda r: abs(r["error"]))

    assert {r["key"] for r in rows} == {"A1", "A3"}
    assert worst["key"] == "A3"
    assert state.counts() == (2, 4)
    assert summary_text(*state.counts()) == "showing 2 of 4"


def test_the_plot_shows_exactly_what_the_table_lists(state):
    """A filtered table beside an unfiltered plot would be two answers to one
    question."""
    state.update("plot", reltol=0.05)
    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)

    figure = state.figure()
    paired = next(t for t in figure.data if t.name and t.name.startswith("paired"))
    table_keys = {r["key"] for r in to_rows(state.visible_records())}

    assert len(paired.x) == len(table_keys)
    assert {paired.customdata[i][0] for i in range(len(paired.x))} == table_keys


def test_unfiltered_designer_still_matches_the_cli(state, tmp_path: Path):
    """The Phase 1 guarantee must survive filters existing at all."""
    from parity_plot.designer.session import Session
    from parity_plot.plot import build_figure

    session, config, data = Session.start((state.config.data.paths[0],), None)
    fresh = DesignerState(config=config, data=data)
    fresh.update("plot", reltol=0.05)

    out = tmp_path / "parity.toml"
    session.save(fresh.config, out)
    from_disk = ParityConfig.from_toml(out)
    rendered = build_figure(load(from_disk.data), from_disk.plot, from_disk.stats)

    assert rendered.to_dict() == fresh.figure().to_dict()


def test_a_saved_config_carries_no_filter_state(state, tmp_path: Path):
    """A config describes the plot, not whatever you were looking at."""
    from parity_plot.designer.session import Session

    session, config, data = Session.start((state.config.data.paths[0],), None)
    live = DesignerState(config=config, data=data)
    live.filters = FilterSet(outside_tolerance_only=True, show_paired=False)

    out = tmp_path / "parity.toml"
    session.save(live.config, out)
    text = out.read_text(encoding="utf-8")

    for word in ("filter", "outside_tolerance", "show_paired", "x_range"):
        assert word not in text


def test_brushing_an_x_window_narrows_both(state):
    state.filters = FilterSet(x_range=(35.0, 75.0))

    rows = to_rows(state.visible_records())
    assert {r["key"] for r in rows} == {"A3", "A4"}  # A4's x is known
    assert state.counts() == (2, 4)


def test_clearing_the_filters_restores_everything(state):
    state.filters = FilterSet(show_paired=False)
    assert state.counts() == (1, 4)

    state.filters = FilterSet()
    assert state.counts() == (4, 4)
    assert state.visible_data().keys == state.data.keys


def test_selecting_from_the_table_and_the_plot_agree(state):
    """Both routes write through select_record, so they cannot disagree."""
    from parity_plot.designer.app import select_record
    from parity_plot.designer.records import key_from_customdata

    select_record(state, "A3")
    from_table = state.selected_record(state.tolerance())

    select_record(state, key_from_customdata(["A3", 10.0]))
    from_plot = state.selected_record(state.tolerance())

    assert from_table == from_plot
    assert from_plot.key == "A3"


def test_a_filtered_out_record_is_still_inspectable(state):
    """Filtering hides a point; it must not make what you clicked unreadable."""
    state.update("plot", reltol=0.05)
    state.selection = "A2"  # passes, so the failures filter hides it

    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)

    assert "A2" not in {r["key"] for r in to_rows(state.visible_records())}
    assert state.selected_record(state.tolerance()).key == "A2"
