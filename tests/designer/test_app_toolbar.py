"""The toolbar -- config picker, Save As, New Design -- driven in-process.

Regression guard for a P0 no other test could see: ``build_app`` assembles the
page inside a ``@ui.page`` closure, and nothing drove it. Its ``_spawn`` helper
*called* its argument while every caller passed a coroutine, so each toolbar
action raised ``'coroutine' object is not callable`` inside a click handler:
Save As wrote nothing (the status bar still said "Ready"), New Design did
nothing, and a picked config never opened. Separately the picker was built with
only the current config and never re-listed on page load, so there was nothing
else to pick.

The page function is captured by standing in for ``ui.page`` and then built
inside a ``Client``, with ``core.loop`` set so background tasks really run --
the same way a served page runs, minus the browser. Clicks go through NiceGUI's
own event dispatch, so an exception in a handler is swallowed exactly as it is
in production: these tests assert on outcomes, never on "it did not raise".
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from parity_plot.designer import app as app_mod
from parity_plot.designer.session import Session

WIDE = "id,r,t\nA,1,2\nB,2,3\n"


def toml(title: str) -> str:
    return (
        '[data]\nfiles = ["w.csv"]\nref = "w.csv:r"\ntest = "w.csv:t"\n'
        f'\n[plot]\ntitle = "{title}"\n'
    )


class Page:
    """A built designer page and the few ways a test pokes at it."""

    def __init__(self, client: Any, state: Any, directory: Path) -> None:
        self.client = client
        self.state = state
        self.directory = directory

    def element(self, text: str) -> Any:
        """The element whose text or label is ``text``."""
        for el in list(self.client.elements.values()):
            if getattr(el, "text", None) == text or el.props.get("label") == text:
                return el
        raise LookupError(text)

    def click(self, text: str) -> None:
        from nicegui import events

        el = self.element(text)
        for listener in list(el._event_listeners.values()):
            if listener.type == "click":
                events.handle_event(
                    listener.handler,
                    events.GenericEventArguments(
                        sender=el, client=self.client, args={}
                    ),
                )
                return
        raise LookupError(f"{text!r} has no click handler")

    @property
    def picker(self) -> Any:
        return self.element("Config")


async def settle(seconds: float = 0.3) -> None:
    """Let spawned background tasks (and their offloaded reads) finish."""
    await asyncio.sleep(seconds)


@pytest.fixture
async def page(tmp_path: Path, monkeypatch):
    """A designer page for ``a.toml``, with ``b.toml`` and ``z.toml`` alongside."""
    from nicegui import Client, core, ui

    (tmp_path / "w.csv").write_text(WIDE, encoding="utf-8")
    (tmp_path / "a.toml").write_text(toml("A"), encoding="utf-8")
    (tmp_path / "b.toml").write_text(toml("B"), encoding="utf-8")
    (tmp_path / "z.toml").write_text(toml("Z"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    session, config, data = Session.start((), tmp_path / "a.toml")
    captured: dict[str, Any] = {}
    real_page = ui.page
    monkeypatch.setattr(
        ui, "page", lambda *a, **k: lambda func: captured.setdefault("page", func)
    )
    state = app_mod.build_app(session, config, data)
    monkeypatch.setattr(ui, "page", real_page)

    core.loop = asyncio.get_running_loop()
    try:
        # The client context is needed only to build the page. It must not be
        # held across the yield: setup and teardown can run in different tasks,
        # and NiceGUI's slot stack is per task. Events do not need it either --
        # handle_event enters the sender's own slot.
        with Client(page=real_page("/")) as client:
            captured["page"]()
        await settle()
        yield Page(client, state, tmp_path)
        # Drain anything a test left running (a debounced save) before the
        # loop goes away.
        await settle(0.6)
    finally:
        core.loop = None


async def test_the_picker_lists_every_config_on_page_load(page):
    assert page.picker.options == ["a.toml", "b.toml", "z.toml"]
    assert page.picker.value == "a.toml"


async def test_picking_a_config_opens_it(page):
    page.picker.value = "b.toml"
    await settle()
    assert page.state.config.plot.title == "B"
    assert page.picker.value == "b.toml"


async def test_save_as_writes_the_file_and_binds_the_picker_to_it(page):
    page.click("Save As…")
    page.element("Path").value = str(page.directory / "c.toml")
    page.click("Save")
    await settle()

    written = page.directory / "c.toml"
    assert written.exists(), "Save As wrote nothing"
    assert 'title = "A"' in written.read_text(encoding="utf-8")
    # The new name is both the value and among the options -- a value missing
    # from its options is reset to None, which NiceGUI reports as a pick.
    assert page.picker.value == "c.toml"
    assert "c.toml" in page.picker.options


async def test_new_design_unbinds_to_an_empty_design(page):
    page.click("New Design")
    await settle()
    assert page.state.config.data.files == ()
    assert page.picker.value == app_mod.UNSAVED
    assert app_mod.UNSAVED in page.picker.options


async def test_an_edit_pending_at_a_swap_is_saved_to_its_own_file(page):
    """The last edit before opening another config belongs in the old file.

    The swap used to cancel the pending auto-save, dropping the edit; and the
    save looked the session up when it fired, so letting it run would have
    written the old design into the *new* file.
    """
    page.element("Title").value = "A edited"  # commits, refreshes, schedules
    await settle(0.05)  # the refresh ran; the 400 ms debounce has not fired
    page.picker.value = "b.toml"
    await settle(0.8)

    assert page.state.config.plot.title == "B"
    a_text = (page.directory / "a.toml").read_text(encoding="utf-8")
    b_text = (page.directory / "b.toml").read_text(encoding="utf-8")
    assert 'title = "A edited"' in a_text, "the last edit to a.toml was dropped"
    assert 'title = "B"' in b_text, "the old design was written into b.toml"


async def test_the_last_pick_wins_while_the_old_design_is_being_saved(
    page, monkeypatch
):
    """The swap flushes the old design's save first, and that awaits.

    A second pick made during the flush must win: the first open passed its
    generation check before the flush, so it has to check again after it.
    """
    import time

    real = Session.autosave

    def slow_autosave(self, config):
        time.sleep(0.3)  # an NFS write
        return real(self, config)

    monkeypatch.setattr(Session, "autosave", slow_autosave)
    page.element("Title").value = "A edited"
    await settle(0.05)
    page.picker.value = "b.toml"  # its swap is now flushing a.toml's edit
    await settle(0.1)
    page.picker.value = "z.toml"
    await settle(1.0)

    assert page.state.config.plot.title == "Z"
    assert page.picker.value == "z.toml"
    assert 'title = "A edited"' in (page.directory / "a.toml").read_text(
        encoding="utf-8"
    )
