# tests/designer/test_add_file_flow.py
"""The add-file flow must not block the event loop, and must still work.

Regression guard for the NFS report: Add File used to read every open CSV
synchronously inside the click handler, on the asyncio event loop. On a
laggy filesystem that blocked the websocket heartbeat long enough for the
browser to drop the connection (the "Searching for server..." overlay) while
the server was in fact alive. The fix runs every file read through
``io.offload`` (NiceGUI's thread pool) from async handlers; these tests pin
that shape so it cannot silently regress to sync.

The last test drives the whole thing through the assembled page -- the Add
File button, the browser dialog's listing, the file pick and the commit --
so a break anywhere in that wiring is caught, not just in the read shape.
"""

from __future__ import annotations

import asyncio

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.io import offload
from parity_plot.designer.state import DesignerState

from .page_harness import eventually, open_page


async def test_offload_does_not_stall_the_loop(tmp_path):
    """With a running loop, offload must not run the read on the loop thread.

    A blocking read executed inline would stall the heartbeat; offload hands
    it to the thread pool instead. The read lands and the loop stays live
    throughout -- proven by a ticker task that keeps firing while the
    (artificially slow) read is in flight.
    """
    from nicegui import core

    csv = tmp_path / "wide.csv"
    csv.write_text("id,reference,test\nA1,10,11\n", encoding="utf-8")
    assert csv.exists()

    ticks: list[int] = []

    async def ticker() -> None:
        while True:
            ticks.append(1)
            await asyncio.sleep(0.005)

    def slow_read() -> int:
        import time

        time.sleep(0.12)  # longer than several tick periods
        return 1

    loop = asyncio.get_running_loop()
    core.loop = loop  # pretend NiceGUI is serving, as launch.run would
    try:
        task = loop.create_task(ticker())
        result = await asyncio.wait_for(offload(slow_read), timeout=5)
        task.cancel()
        assert result == 1
        # The loop was free to run the ticker throughout the blocking read.
        assert len(ticks) > 3, "event loop stalled during the offloaded read"
    finally:
        core.loop = None


async def test_set_data_source_via_offload_adds_a_file(tmp_path):
    """The production add-file commit path: a new file list through offload."""
    csv = tmp_path / "wide.csv"
    csv.write_text("id,reference,test\nA1,10,11\n", encoding="utf-8")
    second = tmp_path / "second.csv"
    second.write_text("id,extra\nA1,99.0\n", encoding="utf-8")

    config = ParityConfig().merge(
        data={"files": (csv,), "ref": "wide.csv:reference", "test": "wide.csv:test"}
    )
    state = DesignerState(config=config, data=load(config.data))
    assert state.counts() == (1, 1)

    ok = await offload(
        state.set_data_source,
        files=(csv, second),
        ref="wide.csv:reference",
        test="wide.csv:test",
    )
    assert ok, state.last_error
    assert state.has_data
    assert state.counts() == (1, 1)  # second file carries no axis pair by itself


async def test_set_data_source_via_offload_rejects_a_bad_column(tmp_path):
    csv = tmp_path / "wide.csv"
    csv.write_text("id,reference,test\nA1,10,11\n", encoding="utf-8")
    config = ParityConfig().merge(
        data={"files": (csv,), "ref": "wide.csv:reference", "test": "wide.csv:test"}
    )
    state = DesignerState(config=config, data=load(config.data))

    ok = await offload(state.set_data_source, ref="wide.csv:nonexistent")
    assert not ok
    assert state.last_error
    # Failure keeps the previously loaded dataset, as the designer promises.
    assert state.has_data


def test_build_data_panel_accepts_a_sync_callback(tmp_path):
    """The panel awaits ``on_change()``; sync callbacks must still be legal.

    The designer's own refresh is async, but the type allows plain sync
    functions and tests may pass them.
    """
    from nicegui import Client, ui

    from parity_plot.designer.panels.data_panel import build_data_panel

    csv = tmp_path / "wide.csv"
    csv.write_text("id,reference,test\nA1,10,11\n", encoding="utf-8")
    config = ParityConfig().merge(
        data={"files": (csv,), "ref": "wide.csv:reference", "test": "wide.csv:test"}
    )
    state = DesignerState(config=config, data=load(config.data))

    seen: list[str] = []

    def on_change() -> None:
        seen.append("change")

    with Client(page=ui.page("/")) as client:
        build_data_panel(state, on_change)
        assert len(client.elements) > 1  # the panel actually built


async def test_add_file_through_the_browser_dialog(tmp_path, monkeypatch):
    """Add File, from the button to the committed config, on the real page.

    Nothing else drives ``_browse``: the dialog's listing, the ``📄 name``
    button and the gated ``_add`` commit were all unexercised. This opens
    the assembled page, clicks ``Add File``, waits for the browser to list
    the directory, clicks the second CSV and asserts it reached the config
    *and* the bound file on disk. Every wait is on a condition, so it holds
    under the slow link of ``./check-slow-nfs``.
    """
    (tmp_path / "a.csv").write_text("id,r,t\nA,1,2\nB,2,3\n", encoding="utf-8")
    (tmp_path / "b.csv").write_text("id,x,y\nA,5,6\nB,6,7\n", encoding="utf-8")
    (tmp_path / "a.toml").write_text(
        '[data]\nfiles = ["a.csv"]\nref = "a.csv:r"\ntest = "a.csv:t"\n'
        '\n[plot]\ntitle = "A"\n',
        encoding="utf-8",
    )

    async with open_page(tmp_path, "a.toml", monkeypatch) as page:
        assert [p.name for p in page.state.config.data.files] == ["a.csv"]

        page.click("Add File")

        def listed(name: str) -> bool:
            """Whether the browser dialog has rendered a button for ``name``."""
            try:
                page.element(f"📄 {name}")
                return True
            except LookupError:
                return False

        await eventually(lambda: listed("b.csv"))  # the listing is async
        page.click("📄 b.csv")

        def picked_up() -> bool:
            return {p.name for p in page.state.config.data.files} == {
                "a.csv",
                "b.csv",
            }

        await eventually(picked_up)
        assert page.state.has_data
        assert page.state.last_error is None

        # The GUI commit also reached the bound config through the auto-save.
        def on_disk() -> str:
            return (tmp_path / "a.toml").read_text(encoding="utf-8")

        await eventually(lambda: "b.csv" in on_disk())
