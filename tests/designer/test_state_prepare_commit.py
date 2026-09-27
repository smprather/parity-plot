"""Splitting the data-source change into a thread-side prepare and a loop-side commit.

The 2026-09-26 scan found three distinct races, all one mechanism:
``set_data_source`` ran in a worker thread and did the whole job there --
snapshot the config, read every CSV, then assign ``self.config = candidate``.
Because the snapshot and the assignment straddled the read, anything the user
did on the event loop in between was silently reverted: a plot edit made during
a slow load, a config opened while a load was in flight (the old design then
auto-saved over the newly opened file), and out-of-order loads where the older
slow one overwrote the newer choice.

The fix splits the work. :meth:`DesignerState.prepare_data_source` is pure --
it validates and loads, and returns a description; :meth:`commit_data_source`
applies it on the event loop, merging *only* the ``[data]`` section into
whatever the config is by then, and dropping the result entirely if the
generation it was prepared under has moved on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.state import DesignerState


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    out = {}
    for name, rows in (
        ("a.csv", "id,reference,test\nA1,10,11\nA2,20,22\n"),
        ("b.csv", "id,reference,test\nA1,10,12\n"),
        ("c.csv", "id,reference,test\nA1,10,13\n"),
    ):
        p = tmp_path / name
        p.write_text(rows, encoding="utf-8")
        out[name] = p
    return out


def designer(
    files: dict[str, Path], ref: str, test: str, opened: tuple[str, ...] = ("a.csv",)
) -> DesignerState:
    config = ParityConfig().merge(
        data={
            "files": tuple(files[name] for name in opened),
            "ref": ref,
            "test": test,
            "join": "id",
        }
    )
    return DesignerState(config=config, data=load(config.data))


def test_a_plot_edit_during_a_load_survives_the_commit(files):
    """The scan's repro: retitle during a slow load, watch the title come back.

    Prepared before the edit, committed after -- which is exactly the ordering
    a slow NFS read produces, only made deterministic here.
    """
    state = designer(files, "a.csv:reference", "a.csv:test")

    generation = state.begin_data_source()
    prepared = state.prepare_data_source(test="a.csv:test", files=(files["a.csv"],))
    # The user types a title while the load is in flight.
    assert state.update("plot", title="Retitled")
    assert state.commit_data_source(prepared, generation)

    # Both landed: the new data, and the edit made while it was loading.
    assert state.config.data.test == "a.csv:test"
    assert state.config.plot.title == "Retitled"


def test_a_commit_after_a_config_swap_is_dropped(files):
    """Opening another config while a load is in flight must not be undone.

    The scan's second repro: the old panel's thread finishes after the swap and
    auto-saves the *old* design over the newly opened file.
    """
    state = designer(files, "a.csv:reference", "a.csv:test")

    generation = state.begin_data_source()
    prepared = state.prepare_data_source(test="b.csv:test")
    # The toolbar opens a different config while that load is still running.
    other = ParityConfig().merge(
        data={
            "files": (files["c.csv"],),
            "ref": "c.csv:reference",
            "test": "c.csv:test",
        }
    )
    state.load_session_config(other, load(other.data))

    assert not state.commit_data_source(prepared, generation)
    # The newly opened config is untouched.
    assert state.config.data.files == (files["c.csv"],)
    assert state.config.data.test == "c.csv:test"


def test_an_older_slow_load_does_not_beat_a_newer_choice(files):
    """Out-of-order: pick test=B (slow), then test=C (fast); C must win.

    Modelled in the order the real failure produced -- C commits first, then
    the older B arrives and is dropped because its generation moved. All three
    files are open, as they would be once the user has added them.
    """
    state = designer(
        files,
        "a.csv:reference",
        "a.csv:test",
        opened=("a.csv", "b.csv", "c.csv"),
    )

    older = state.begin_data_source()
    older_prepared = state.prepare_data_source(test="b.csv:test")
    newer = state.begin_data_source()
    newer_prepared = state.prepare_data_source(test="c.csv:test")

    assert state.commit_data_source(newer_prepared, newer)
    assert state.config.data.test == "c.csv:test"
    # The stale one lands late and must be ignored.
    assert not state.commit_data_source(older_prepared, older)
    assert state.config.data.test == "c.csv:test"
    assert state.data is not None
    assert state.data.n_paired == 1


def test_a_failed_load_keeps_the_previous_dataset(files):
    """The long-standing rule, now across the prepare/commit split."""
    state = designer(files, "a.csv:reference", "a.csv:test")
    before = state.data

    generation = state.begin_data_source()
    prepared = state.prepare_data_source(ref="a.csv:nope")

    assert not state.commit_data_source(prepared, generation)
    assert state.data is before
    assert state.config.data.ref == "a.csv:reference"
    assert state.last_error


def test_an_incomplete_source_is_the_empty_state_not_an_error(files):
    """Clearing ref is "not chosen yet", not a failure -- and it still commits.

    ``clear`` is how that is expressed: ``merge`` drops a ``None`` override, so
    passing ``ref=None`` on its own would silently keep the old ref (pinned
    below). The data panel passes ``clear`` for exactly this reason.
    """
    state = designer(files, "a.csv:reference", "a.csv:test")

    generation = state.begin_data_source()
    prepared = state.prepare_data_source(ref=None, clear=("ref",))

    assert state.commit_data_source(prepared, generation)
    assert state.data is None
    assert state.selection is None
    assert state.last_error is None
    assert state.config.data.ref is None


def test_a_none_override_alone_does_not_clear(files):
    """Why the panel needs ``clear``: merge drops None, so ``ref=None`` is a no-op.

    Without this, "no ref selected" in the panel would keep reloading the last
    good ref and look like the selection never took.
    """
    state = designer(files, "a.csv:reference", "a.csv:test")

    generation = state.begin_data_source()
    prepared = state.prepare_data_source(ref=None)

    assert state.commit_data_source(prepared, generation)
    assert state.config.data.ref == "a.csv:reference"
    assert state.data is not None


def test_commit_drops_a_selection_absent_from_the_new_data(files):
    """A pin that does not exist in the new dataset is cleared."""
    state = designer(
        files,
        "a.csv:reference",
        "a.csv:test",
        opened=("a.csv", "b.csv", "c.csv"),
    )
    state.selection = "A2"  # only a.csv has A2

    generation = state.begin_data_source()
    prepared = state.prepare_data_source(
        files=(files["b.csv"], files["c.csv"]),
        ref="b.csv:reference",
        test="c.csv:test",
    )
    assert state.commit_data_source(prepared, generation)
    assert state.selection is None


def test_commit_keeps_a_selection_present_in_the_new_data(files):
    state = designer(
        files,
        "a.csv:reference",
        "a.csv:test",
        opened=("a.csv", "b.csv"),
    )
    state.selection = "A1"

    generation = state.begin_data_source()
    prepared = state.prepare_data_source(
        files=(files["b.csv"],),
        ref="b.csv:reference",
        test="b.csv:test",
    )
    assert state.commit_data_source(prepared, generation)
    assert state.selection == "A1"


def test_set_data_source_still_works_synchronously(files):
    """The one-call form the non-UI callers and existing tests use."""
    state = designer(files, "a.csv:reference", "a.csv:test")
    assert state.set_data_source(
        files=(files["a.csv"], files["b.csv"]), test="b.csv:test"
    )
    assert state.config.data.test == "b.csv:test"
    assert not state.set_data_source(ref="a.csv:nope")
    assert state.last_error
