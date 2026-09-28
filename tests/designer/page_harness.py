"""Building the real designer page in-process, and poking at it.

``build_app`` registers its page inside a ``@ui.page`` closure; the page
function is captured by standing in for ``ui.page`` and built inside a
``Client``, with ``core.loop`` set so background tasks and offloaded work really
run -- the way a served page runs, minus the browser. Clicks go through
NiceGUI's own event dispatch, so an exception in a handler is swallowed exactly
as it is in production: tests assert on outcomes, never on "it did not raise".
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from parity_plot.designer import app as app_mod
from parity_plot.designer.session import Session


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

    def of_type(self, name: str) -> Any:
        """The one element of NiceGUI class ``name`` (``"Plotly"``, ``"Table"``)."""
        for el in self.client.elements.values():
            if type(el).__name__ == name:
                return el
        raise LookupError(name)

    def emit(self, element: Any, event: str, args: Any = None) -> None:
        """Fire ``event`` on ``element`` as the browser would."""
        from nicegui import events

        for listener in list(element._event_listeners.values()):
            if listener.type == event:
                events.handle_event(
                    listener.handler,
                    events.GenericEventArguments(
                        sender=element, client=self.client, args=args or {}
                    ),
                )
                return
        raise LookupError(f"no {event!r} handler")

    def click(self, text: str) -> None:
        self.emit(self.element(text), "click")

    @property
    def picker(self) -> Any:
        return self.element("Config")

    def plot_title(self) -> str:
        """The title of the figure the plot currently shows."""
        title = (self.of_type("Plotly").figure.get("layout") or {}).get("title") or {}
        return title.get("text") or ""


async def eventually(predicate, timeout: float = 20.0) -> None:
    """Poll until ``predicate()`` holds.

    Never a fixed sleep: these tests once slept 0.3 s and passed on a local disk,
    then failed under ./check-slow-nfs, where each read or write of the configs
    costs hundreds of milliseconds.
    """
    deadline = time.monotonic() + timeout
    while not _holds(predicate):
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached before the timeout")
        await asyncio.sleep(0.02)


def _holds(predicate) -> bool:
    """``predicate()``, with a filesystem error read as "not yet".

    A predicate that reads a config back can race the designer's atomic save:
    over NFSv3 a read that looked the file up just before the rename then finds
    its handle gone. The kernel client retries that; the harness's fuse-nfs
    fallback reports ENOENT. Either way the next poll sees the new file.
    """
    try:
        return bool(predicate())
    except OSError:
        return False


@asynccontextmanager
async def open_page(directory: Path, config: str, monkeypatch) -> AsyncIterator[Page]:
    """The designer page for ``directory/config``, built and loaded."""
    from nicegui import Client, core, ui

    monkeypatch.chdir(directory)
    session, cfg, data = Session.start((), directory / config)
    captured: dict[str, Any] = {}
    real_page = ui.page
    monkeypatch.setattr(
        ui, "page", lambda *a, **k: lambda func: captured.setdefault("page", func)
    )
    state = app_mod.build_app(session, cfg, data)
    monkeypatch.setattr(ui, "page", real_page)

    core.loop = asyncio.get_running_loop()
    try:
        # The client context is needed only to build the page. It must not be
        # held across a fixture's yield: setup and teardown can run in different
        # tasks, and NiceGUI's slot stack is per task. Events do not need it
        # either -- handle_event enters the sender's own slot.
        with Client(page=real_page("/")) as client:
            captured["page"]()
        page = Page(client, state, directory)
        # Loaded once the first view has painted the configured figure.
        await eventually(lambda: page.plot_title() == (cfg.plot.title or ""))
        yield page
        # Give a debounced save a test left behind its 400 ms before the loop
        # goes away.
        await asyncio.sleep(0.6)
    finally:
        core.loop = None
