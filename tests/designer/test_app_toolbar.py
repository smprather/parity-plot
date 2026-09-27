"""The toolbar -- config picker, Save As, New Design -- driven in-process.

Regression guard for a P0 no other test could see: ``build_app`` assembles the
page inside a ``@ui.page`` closure, and nothing drove it. Its ``_spawn`` helper
*called* its argument while every caller passed a coroutine, so each toolbar
action raised ``'coroutine' object is not callable`` inside a click handler:
Save As wrote nothing (the status bar still said "Ready"), New Design did
nothing, and a picked config never opened. Separately the picker was built with
only the current config and never re-listed on page load, so there was nothing
else to pick.

The page is built by ``page_harness.open_page``, which says how.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from parity_plot.designer import app as app_mod
from parity_plot.designer.session import Debouncer, Session

from .page_harness import eventually, open_page

WIDE = "id,r,t\nA,1,2\nB,2,3\n"


def toml(title: str) -> str:
    return (
        '[data]\nfiles = ["w.csv"]\nref = "w.csv:r"\ntest = "w.csv:t"\n'
        f'\n[plot]\ntitle = "{title}"\n'
    )


@pytest.fixture
async def page(tmp_path: Path, monkeypatch):
    """A designer page for ``a.toml``, with ``b.toml`` and ``z.toml`` alongside."""
    (tmp_path / "w.csv").write_text(WIDE, encoding="utf-8")
    for name in "abz":
        (tmp_path / f"{name}.toml").write_text(toml(name.upper()), encoding="utf-8")
    async with open_page(tmp_path, "a.toml", monkeypatch) as page:
        # Ready once the background listing has filled the picker, too.
        await eventually(lambda: len(page.picker.options) == 3)
        yield page


async def test_the_picker_lists_every_config_on_page_load(page):
    assert page.picker.options == ["a.toml", "b.toml", "z.toml"]
    assert page.picker.value == "a.toml"


async def test_picking_a_config_opens_it(page):
    page.picker.value = "b.toml"
    await eventually(lambda: page.state.config.plot.title == "B")
    assert page.picker.value == "b.toml"


async def test_save_as_writes_the_file_and_binds_the_picker_to_it(page):
    page.click("Save As…")
    page.element("Path").value = str(page.directory / "c.toml")
    page.click("Save")
    written = page.directory / "c.toml"
    await eventually(lambda: page.picker.value == "c.toml")

    assert written.exists(), "Save As wrote nothing"
    assert 'title = "A"' in written.read_text(encoding="utf-8")
    # The new name is both the value and among the options -- a value missing
    # from its options is reset to None, which NiceGUI reports as a pick.
    assert page.picker.value == "c.toml"
    assert "c.toml" in page.picker.options


async def test_new_design_unbinds_to_an_empty_design(page):
    page.click("New Design")
    await eventually(lambda: page.picker.value == app_mod.UNSAVED)
    assert page.state.config.data.files == ()
    assert page.picker.value == app_mod.UNSAVED
    assert app_mod.UNSAVED in page.picker.options


async def test_an_edit_pending_at_a_swap_is_saved_to_its_own_file(page):
    """The last edit before opening another config belongs in the old file.

    The swap used to cancel the pending auto-save, dropping the edit; and the
    save looked the session up when it fired, so letting it run would have
    written the old design into the *new* file.
    """
    a_toml = page.directory / "a.toml"
    page.element("Title").value = "A edited"  # commits, spawns the refresh
    # The refresh runs before the open (tasks are FIFO), so the save is pending
    # -- not yet fired: the debounce is 400 ms -- when the swap starts.
    page.picker.value = "b.toml"
    await eventually(lambda: page.state.config.plot.title == "B")
    await eventually(lambda: 'title = "A edited"' in a_toml.read_text("utf-8"))

    b_text = (page.directory / "b.toml").read_text(encoding="utf-8")
    assert 'title = "B"' in b_text, "the old design was written into b.toml"


async def test_the_last_pick_wins_while_the_old_design_is_being_saved(
    page, monkeypatch
):
    """The swap flushes the old design's save first, and that awaits.

    A second pick made during the flush must win: the first open passed its
    generation check before the flush, so it has to check again after it. The
    save is held open with an event, so the second pick provably lands while
    the first swap is inside its flush.
    """
    real_autosave = Session.autosave
    real_flush = Debouncer.flush
    saving, release = threading.Event(), threading.Event()
    flushes: list[str] = []

    def held_autosave(self, config):
        saving.set()
        release.wait(timeout=20)
        return real_autosave(self, config)

    async def observed_flush(self):
        flushes.append("start")
        await real_flush(self)
        flushes.append("done")

    monkeypatch.setattr(Session, "autosave", held_autosave)
    monkeypatch.setattr(Debouncer, "flush", observed_flush)

    page.element("Title").value = "A edited"
    # The save is scheduled when the refresh's view lands -- wait for that, so
    # it is pending when b's swap flushes.
    await eventually(lambda: "A edited" in page.plot_title())
    page.picker.value = "b.toml"
    await eventually(lambda: saving.is_set() and "start" in flushes)
    page.picker.value = "z.toml"  # b's swap is blocked inside its flush
    await eventually(lambda: page.state.config.plot.title == "Z")
    release.set()
    # b's flush returning is the moment its swap re-checks the generation --
    # and without that re-check, swaps to B.
    await eventually(lambda: flushes.count("done") == 2)

    assert page.state.config.plot.title == "Z"
    assert page.picker.value == "z.toml"
    assert 'title = "A edited"' in (page.directory / "a.toml").read_text(
        encoding="utf-8"
    )


async def test_a_refresh_that_lands_after_a_swap_saves_to_its_own_file(
    page, monkeypatch
):
    """The refresh computes off the loop, so it can finish after a config swap.

    Its save must still go to the design it was computed from. Scheduled from
    the state as it stood when it landed, it paired the old session with the
    *new* design, writing b.toml's content into a.toml. The compute is held
    open so the swap provably happens in between.
    """
    real_compute = app_mod.compute_view
    hold = threading.Event()
    held: list[str] = []

    def held_compute(inputs):
        if inputs.config.plot.title == "A edited" and not held:
            held.append("held")
            hold.wait(timeout=20)
        return real_compute(inputs)

    monkeypatch.setattr(app_mod, "compute_view", held_compute)
    a_toml, b_toml = page.directory / "a.toml", page.directory / "b.toml"
    b_before = b_toml.read_text(encoding="utf-8")

    page.element("Title").value = "A edited"
    await eventually(lambda: bool(held))  # A's refresh is inside its compute
    page.picker.value = "b.toml"
    await eventually(lambda: page.state.config.plot.title == "B")
    hold.set()
    await eventually(lambda: 'title = "A edited"' in a_toml.read_text("utf-8"))

    assert page.state.config.plot.title == "B"
    await eventually(lambda: page.plot_title() == "B")  # the stale view is not shown
    assert b_toml.read_text(encoding="utf-8") == b_before
