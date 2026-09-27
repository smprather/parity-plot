"""A panel that commits synchronously must still run the async refresh.

Regression guard for the biggest P0 in the 2026-09-26 scan. ``app.refresh`` is
async (the data panel's commit can be an off-the-loop file read), but the
tolerance, polynomial, histogram, encoding, controls and table panels all call
``on_change()`` from a *sync* commit. Handing them the coroutine function
directly meant the coroutine was created and immediately dropped: no redraw, no
status-bar update, no auto-save -- only a ``coroutine ... was never awaited``
warning in the server log. They are wired through :func:`sync_refresher` now,
and pytest turns that ``RuntimeWarning`` into an error so a dropped awaitable
anywhere in the suite is a failure.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.io import sync_refresher
from parity_plot.designer.state import DesignerState

WIDE = "id,reference,test\nA1,10.0,11.0\nA2,20.0,25.0\n"


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    csv = tmp_path / "w.csv"
    csv.write_text(WIDE, encoding="utf-8")
    config = ParityConfig().merge(
        data={
            "files": (csv,),
            "ref": "w.csv:reference",
            "test": "w.csv:test",
            "join": "id",
        }
    )
    return DesignerState(config=config, data=load(config.data))


async def test_sync_refresher_runs_the_coroutine_it_is_given():
    """The whole point: the coroutine must actually run, not be discarded."""
    from nicegui import core

    calls: list[str] = []

    async def refresh() -> None:
        calls.append("refreshed")

    core.loop = asyncio.get_running_loop()
    try:
        sync_refresher(refresh)()
        # background_tasks.create schedules, not awaits -- yield so the task runs.
        await asyncio.sleep(0)
        assert calls == ["refreshed"]
    finally:
        core.loop = None


async def test_sync_refresher_passes_a_sync_result_through_untouched():
    """A sync refresher stays callable -- the type allows both."""
    calls: list[str] = []

    def refresh() -> None:
        calls.append("refreshed")

    assert sync_refresher(refresh)() is None
    assert calls == ["refreshed"]


async def test_a_sync_panel_commit_runs_the_async_refresh(state):
    """The tolerance panel drives this end to end through the real shim.

    Toggling a tolerance's checkbox is a *sync* commit; ``on_change`` is the
    async refresh. Before the fix this coroutine was dropped on the floor and
    nothing downstream -- plot, status bar, auto-save -- ever ran.
    """
    from nicegui import Client, core, ui

    from parity_plot.designer.panels.tolerances import build_tolerances_panel

    refreshed: list[int] = []

    async def refresh() -> None:
        refreshed.append(1)

    core.loop = asyncio.get_running_loop()
    try:
        with Client(page=ui.page("/")) as client:
            build_tolerances_panel(state, sync_refresher(refresh))
            # The panel renders one checkbox per tolerance; toggling it is the
            # user gesture that used to lose the refresh.
            box = next(
                e
                for e in client.elements.values()
                if isinstance(e, ui.checkbox) and e.props.get("dense") is not None
            )
            assert box.value is True
            box.set_value(False)
            await asyncio.sleep(0)
        assert refreshed, "the panel's commit dropped the async refresh"
    finally:
        core.loop = None
    # And the commit itself did land -- a lost refresh is not a failed commit.
    assert state.tolerances()[0].enabled is False


SYNC_COMMIT_PANELS = (
    "build_tolerances_panel",
    "build_polynomial_lines_panel",
    "build_histogram_panel",
    "build_encoding_panel",
    "build_controls",
)


def test_every_sync_commit_panel_is_wired_through_the_shim():
    """Pin the wiring itself: sync panels must not receive the bare coroutine.

    This one is a source-level pin on purpose. Which callback each panel
    receives is decided inside ``build_app``, and the consequence -- a plot that
    stops redrawing and a config that stops auto-saving -- is invisible to the
    rest of the suite, which never drives the assembled page. A structural
    assertion is the only place that can catch a regression here; the behaviour
    it guards is covered end to end by the panel test above.
    """
    import inspect

    from parity_plot.designer import app

    source = inspect.getsource(app.build_app)
    for builder in SYNC_COMMIT_PANELS:
        line = next(
            line
            for line in source.splitlines()
            if line.strip().startswith(f"{builder}(state,")
        )
        assert "notify" in line, f"{builder} gets the raw refresher: {line.strip()}"
