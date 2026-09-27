"""The data panel, driven for real: races and page-load behaviour.

Each test builds the actual panel inside a NiceGUI ``Client`` with ``core.loop``
set, so gated commits, offloaded reads and background tasks run as they do when
served. A slow filesystem is modelled with a ``threading.Event`` that holds the
option read open, so each interleaving is deterministic rather than timed.

* A config opened while the old panel was mid-read had its ``[data]`` replaced
  by the old panel's: ``apply`` claimed its generation *after* the read, when a
  claim is current by construction.
* Page load guessed ref/test into the selects under suspension and never
  committed them -- a chosen-looking axis pair over an empty plot.
* The option refresh dropped the configured colour column (a single select
  resets to None when its value leaves the options), and a failed read emptied
  the pinned hover columns, which the next edit then saved.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import DataError, load
from parity_plot.designer.panels import data_panel
from parity_plot.designer.state import DesignerState
from parity_plot.sources import clear_cache


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class Panel:
    def __init__(self, client: Any, state: DesignerState) -> None:
        self.client = client
        self.state = state

    def select(self, label: str) -> Any:
        for el in self.client.elements.values():
            if el.props.get("label") == label:
                return el
        raise LookupError(label)


@pytest.fixture
async def build(monkeypatch):
    """Build a data panel for a state; yields a builder, cleans the loop up."""
    from nicegui import Client, core, ui

    clear_cache()
    core.loop = asyncio.get_running_loop()
    commits: list[str] = []

    async def build_for(state: DesignerState) -> Panel:
        async def on_change() -> None:
            commits.append("commit")

        with Client(page=ui.page("/")) as client:
            data_panel.build_data_panel(state, on_change)
        await asyncio.sleep(0.2)  # the page-load option refresh
        panel = Panel(client, state)
        panel.commits = commits  # type: ignore[attr-defined]
        return panel

    try:
        yield build_for
    finally:
        await asyncio.sleep(0.05)
        core.loop = None
        clear_cache()


def blocking_options(monkeypatch) -> tuple[threading.Event, threading.Event]:
    """Make the panel's option read block until released.

    Returns ``(entered, release)``: ``entered`` is set once the read is in
    flight, ``release`` lets it finish.
    """
    entered, release = threading.Event(), threading.Event()
    real = data_panel.read_column_options

    def slow(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return real(*args, **kwargs)

    monkeypatch.setattr(data_panel, "read_column_options", slow)
    return entered, release


async def wait_for(event: threading.Event) -> None:
    for _ in range(200):
        if event.is_set():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the read never started")


async def test_a_config_opened_during_the_pre_commit_read_is_not_overwritten(
    tmp_path, build, monkeypatch
):
    a = write(tmp_path, "a.csv", "id,r,t,u\nA1,1,2,3\nA2,2,3,4\n")
    b = write(tmp_path, "b.csv", "id,x,y\nB1,5,6\nB2,6,7\n")
    cfg_a = ParityConfig().merge(
        data={"files": (a,), "ref": "a.csv:r", "test": "a.csv:t"},
        plot={"title": "A"},
    )
    cfg_b = ParityConfig().merge(
        data={"files": (b,), "ref": "b.csv:x", "test": "b.csv:y"},
        plot={"title": "B"},
    )
    state = DesignerState(config=cfg_a, data=load(cfg_a.data))
    panel = await build(state)
    entered, release = blocking_options(monkeypatch)

    panel.select("Test").value = "a.csv:u"  # the old design's edit ...
    await wait_for(entered)  # ... is now inside its option read
    state.load_session_config(cfg_b, load(cfg_b.data))  # what _swap does
    release.set()
    await asyncio.sleep(0.3)

    assert state.config.plot.title == "B"
    assert state.config.data.files == (b,), "the old panel committed over B"
    assert state.config.data.test == "b.csv:y"
    assert panel.commits == [], "the old panel refreshed (and so auto-saved)"


async def test_page_load_does_not_show_an_uncommitted_axis_guess(tmp_path, build):
    """`parity-plot design a.csv b.csv`: files, but no ref/test chosen yet."""
    a = write(tmp_path, "a.csv", "id,r,t\nA1,1,2\nA2,2,3\n")
    b = write(tmp_path, "b.csv", "id,x\nA1,5\nA2,6\n")
    state = DesignerState(config=ParityConfig().merge(data={"files": (a, b)}))
    panel = await build(state)

    assert panel.select("Reference").value == state.config.data.ref
    assert panel.select("Test").value == state.config.data.test


async def test_page_load_keeps_a_path_form_colour_column(tmp_path, build):
    """The loader accepts a path-form ref; the colour select must keep it."""
    f = write(tmp_path, "d.csv", "id,r,t,temp\nA1,1,2,30\nA2,2,3,40\n")
    colour = f"{f}:temp"
    config = ParityConfig().merge(
        data={
            "files": (f,),
            "ref": "d.csv:r",
            "test": "d.csv:t",
            "color_column": colour,
        }
    )
    state = DesignerState(config=config, data=load(config.data))
    panel = await build(state)

    assert panel.select("Colour column (numeric, for colorscale)").value == colour


async def test_a_failed_read_does_not_drop_pinned_hover_columns(
    tmp_path, build, monkeypatch
):
    """A briefly unreadable file must not cost the user their hover selection."""
    f = write(tmp_path, "d.csv", "id,r,t,note\nA1,1,2,x\nA2,2,3,y\n")
    config = ParityConfig().merge(
        data={
            "files": (f,),
            "ref": "d.csv:r",
            "test": "d.csv:t",
            "hover_columns": ("d.csv:note",),
        }
    )
    state = DesignerState(config=config, data=load(config.data))

    def unreadable(paths):
        raise DataError("could not read d.csv: Stale file handle")

    monkeypatch.setattr(data_panel, "open_sources", unreadable)
    panel = await build(state)
    assert panel.select("Hover columns").value == ["d.csv:note"]

    # The next data edit commits what the widgets hold.
    monkeypatch.undo()
    panel.select("Group by (one or more columns)").value = ["note"]
    await asyncio.sleep(0.3)
    assert state.config.data.hover_columns == ("d.csv:note",)


async def test_a_pin_into_a_removed_file_is_still_pruned(tmp_path, build):
    """The prune exists for this case; gating it on a good read must keep it.

    b.csv backs ``test`` and carries the pinned hover column. Removing it
    points ``test`` elsewhere, so the pin is no longer a candidate -- and
    ``load`` would refuse it -- so it must go.
    """
    from nicegui import events

    a = write(tmp_path, "a.csv", "id,r,t\nA1,1,2\nA2,2,3\n")
    b = write(tmp_path, "b.csv", "id,m,extra\nA1,9,p\nA2,8,q\n")
    config = ParityConfig().merge(
        data={
            "files": (a, b),
            "ref": "a.csv:r",
            "test": "b.csv:m",
            "join": "id",
            "hover_columns": ("b.csv:extra",),
        }
    )
    state = DesignerState(config=config, data=load(config.data))
    panel = await build(state)
    panel.select("Test").value = "a.csv:t"  # stop using b.csv first
    await asyncio.sleep(0.3)
    assert state.config.data.hover_columns == ()

    remove_b = [
        el for el in panel.client.elements.values() if el.props.get("icon") == "close"
    ][1]
    for listener in list(remove_b._event_listeners.values()):
        if listener.type == "click":
            events.handle_event(
                listener.handler,
                events.GenericEventArguments(
                    sender=remove_b, client=panel.client, args={}
                ),
            )
    await asyncio.sleep(0.3)

    assert state.config.data.files == (a,)
    assert state.last_error is None


async def test_a_sync_on_change_is_legal_for_a_commit(tmp_path, monkeypatch):
    """The docstring allows a sync ``on_change``; a commit must not await None.

    The failure is invisible from outside: the commit and the callback both
    happen, then ``await None`` raises inside a background task and NiceGUI
    logs it. So the test listens where NiceGUI reports it.
    """
    from nicegui import Client, core, ui

    f = write(tmp_path, "d.csv", "id,r,t,u\nA1,1,2,3\nA2,2,3,4\n")
    config = ParityConfig().merge(
        data={"files": (f,), "ref": "d.csv:r", "test": "d.csv:t"}
    )
    state = DesignerState(config=config, data=load(config.data))
    seen: list[str] = []
    raised: list[Exception] = []
    monkeypatch.setattr(core.app, "handle_exception", raised.append)
    core.loop = asyncio.get_running_loop()
    try:
        with Client(page=ui.page("/")) as client:
            data_panel.build_data_panel(state, lambda: seen.append("changed"))
        await asyncio.sleep(0.2)
        panel = Panel(client, state)
        panel.select("Test").value = "d.csv:u"
        await asyncio.sleep(0.3)
    finally:
        core.loop = None
    assert state.config.data.test == "d.csv:u"
    assert seen == ["changed"]
    assert raised == []
