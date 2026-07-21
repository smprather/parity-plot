"""Phase 2 end to end: load a different file, map it, click a point."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.datasets import peek, suggest_mapping
from parity_plot.designer.inspector_helpers import describe
from parity_plot.designer.records import key_from_customdata
from parity_plot.designer.state import DesignerState
from parity_plot.tolerances import NamedTolerance

FIRST = "id,reference,test\nA1,10.0,11.0\nA2,20.0,21.0\n"
SECOND = "part,golden,dut\nB1,5.0,5.5\nB2,6.0,9.0\nB3,7.0,\n"

SPEC_10PCT = (NamedTolerance(name="spec", reltol=0.1),)


def _guess_kwargs(files: tuple[Path, ...], guess: dict) -> dict:
    """Translate a `suggest_mapping` guess (old key/x/y vocabulary) into the
    new `set_data_source` kwargs (files/ref/test/join), qualifying the bare
    column names with the file basename."""
    if len(files) == 1:
        f = files[0]
        return {
            "files": files,
            "ref": f"{f.name}:{guess['x']}",
            "test": f"{f.name}:{guess['y']}",
            "join": guess["key"],
        }
    # two-file join: x from the first, y from the second, join is the key
    return {
        "files": files,
        "ref": f"{files[0].name}:{guess['x']}",
        "test": f"{files[1].name}:{guess['y']}",
        "join": guess["key"],
    }


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    first = tmp_path / "first.csv"
    first.write_text(FIRST, encoding="utf-8")
    config = ParityConfig().merge(
        data={"files": (first,), "ref": "first.csv:reference",
              "test": "first.csv:test", "join": "id"}
    )
    return DesignerState(config=config, data=load(config.data))


def test_open_a_new_file_using_the_suggested_mapping(state, tmp_path: Path):
    second = tmp_path / "second.csv"
    second.write_text(SECOND, encoding="utf-8")

    guess = suggest_mapping(peek(second))
    assert guess == {"key": "part", "x": "golden", "y": "dut"}

    assert state.set_data_source(**_guess_kwargs((second,), guess)), state.last_error
    assert state.data.n_paired == 2
    assert len(state.data.missing_y) == 1


def test_clicking_a_point_then_reading_its_record(state, tmp_path: Path):
    second = tmp_path / "second.csv"
    second.write_text(SECOND, encoding="utf-8")
    state.set_data_source(**_guess_kwargs((second,), suggest_mapping(peek(second))))

    # What a Plotly click on the paired trace delivers.
    state.selection = key_from_customdata(["B2", 3.0])
    view = state.selected_record(SPEC_10PCT)

    assert view.key == "B2"
    assert view.error == pytest.approx(3.0)
    assert view.failed == ("spec",)  # 50% off a 10% tolerance


def test_clicking_a_rug_tick_resolves_to_the_unpaired_record(state, tmp_path: Path):
    """Rug traces carry a bare key, not a (key, diff, verdict) triple."""
    second = tmp_path / "second.csv"
    second.write_text(SECOND, encoding="utf-8")
    state.set_data_source(**_guess_kwargs((second,), suggest_mapping(peek(second))))

    state.selection = key_from_customdata("B3")
    view = state.selected_record(SPEC_10PCT)

    assert view.key == "B3"
    assert view.status == "missing y"
    assert view.failed is None  # never judged, not judged as failing
    assert dict(describe(view))["Test"] == "missing"


def test_the_figure_and_the_inspector_agree_about_the_data(state, tmp_path: Path):
    """Both read the same ParityData, so a swap cannot leave them disagreeing."""
    second = tmp_path / "second.csv"
    second.write_text(SECOND, encoding="utf-8")
    state.set_data_source(**_guess_kwargs((second,), suggest_mapping(peek(second))))

    figure = state.figure()
    paired = next(t for t in figure.data if t.name and t.name.startswith("paired"))

    state.selection = "B1"
    assert state.selected_record().x in list(paired.x)


def test_a_bad_mapping_leaves_everything_as_it_was(state):
    before_data = state.data
    before_figure = state.figure().to_dict()

    assert not state.set_data_source(ref="first.csv:not_a_column")

    assert state.data is before_data
    assert state.figure().to_dict() == before_figure
    assert "not_a_column" in state.last_error


def test_a_failed_load_error_survives_the_next_redraw(state):
    """The UI redraws right after a failed load, and that redraw succeeds
    because the old data is still there. If drawing cleared the error, the
    banner would blank and the user would never learn why nothing changed."""
    assert not state.set_data_source(ref="first.csv:not_a_column")
    assert "not_a_column" in state.last_error

    state.figure()  # what refresh() does immediately afterwards

    assert "not_a_column" in state.last_error


def test_a_successful_edit_clears_a_previous_error(state):
    state.set_data_source(ref="first.csv:not_a_column")
    assert state.last_error is not None

    assert state.update("plot", theme="light")

    assert state.last_error is None


def test_swapping_files_drops_a_selection_that_no_longer_exists(state, tmp_path: Path):
    """Otherwise the inspector would show a record from a file that is closed."""
    second = tmp_path / "second.csv"
    second.write_text(SECOND, encoding="utf-8")

    state.selection = "A1"
    assert state.selected_record() is not None

    state.set_data_source(**_guess_kwargs((second,), suggest_mapping(peek(second))))

    assert state.selection is None
    assert state.selected_record() is None


def test_join_mode_still_works_through_the_designer(state, tmp_path: Path):
    """Start from a wide file, then switch to two files joined on a key."""
    x = tmp_path / "ref.csv"
    y = tmp_path / "meas.csv"
    x.write_text("id,value\nA1,10.0\nA2,20.0\n", encoding="utf-8")
    y.write_text("id,value\nA1,11.0\nA3,30.0\n", encoding="utf-8")

    assert state.set_data_source(
        files=(x, y), ref="ref.csv:value", test="meas.csv:value", join="id"
    ), state.last_error
    assert state.data.n_paired == 1
    assert len(state.data.missing_y) == 1  # A2
    assert len(state.data.missing_x) == 1  # A3