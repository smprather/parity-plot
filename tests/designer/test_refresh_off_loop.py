"""The refresh does its per-record work off the event loop, and pages the table.

Regression guard for the refresh stall: every edit, a title change included,
built the figure, converted it, and built a row for every record on the asyncio
loop -- ~30-35 ms per thousand rows, so past ~60k rows the websocket heartbeat
missed its 2 s deadline and the browser showed the reconnect overlay
(``tools/slow-nfs/loop_lag_probe.py`` measures it). Timing tests would be flaky,
so these pin the *shape*: which thread does the work, and how many rows cross to
the browser.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from parity_plot.designer import state as state_mod
from parity_plot.designer import view as view_mod

from .page_harness import eventually, open_page

N = 40


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    lines = ["id,r,t"] + [
        f"R{i:02d},{i + 1},{(i + 1) * (1 + (i % 7) / 20)}" for i in range(N)
    ]
    (tmp_path / "w.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "a.toml").write_text(
        '[data]\nfiles = ["w.csv"]\nref = "w.csv:r"\ntest = "w.csv:t"\n'
        '\n[plot]\ntitle = "A"\n',
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def work_threads(monkeypatch) -> list[int]:
    """The thread of every figure build and every full row build."""
    seen: list[int] = []
    real_build, real_rows = view_mod.build_figure, view_mod.to_rows

    def build_figure(*args, **kwargs):
        seen.append(threading.get_ident())
        return real_build(*args, **kwargs)

    def to_rows(*args, **kwargs):
        seen.append(threading.get_ident())
        return real_rows(*args, **kwargs)

    monkeypatch.setattr(view_mod, "build_figure", build_figure)
    monkeypatch.setattr(view_mod, "to_rows", to_rows)
    return seen


def refuse_on_the_loop(monkeypatch, loop_thread: int) -> None:
    """Make the synchronous figure build fail loudly if the loop calls it."""
    real = state_mod.DesignerState.figure

    def figure(self):
        assert threading.get_ident() != loop_thread, "figure built on the loop"
        return real(self)

    monkeypatch.setattr(state_mod.DesignerState, "figure", figure)


async def test_page_load_and_refresh_build_nothing_on_the_loop(
    directory, monkeypatch, work_threads
):
    loop_thread = threading.get_ident()
    refuse_on_the_loop(monkeypatch, loop_thread)
    async with open_page(directory, "a.toml", monkeypatch) as page:
        assert work_threads, "the first view was never computed"
        before = len(work_threads)

        page.element("Title").value = "edited"
        await eventually(lambda: page.plot_title() == "edited")

        assert len(work_threads) > before
        assert loop_thread not in work_threads


async def test_the_table_ships_one_page_not_every_row(directory, monkeypatch):
    async with open_page(directory, "a.toml", monkeypatch) as page:
        table = page.of_type("Table")
        await eventually(lambda: table.pagination.get("rowsNumber") == N)
        assert len(table.rows) == 15
        # Paired by row position (no join), so records are keyed by it.
        assert [row["key"] for row in table.rows] == [str(i) for i in range(15)]


async def test_sorting_and_paging_happen_on_the_server(directory, monkeypatch):
    async with open_page(directory, "a.toml", monkeypatch) as page:
        table = page.of_type("Table")
        await eventually(lambda: table.pagination.get("rowsNumber") == N)

        request = {"sortBy": "error", "descending": True, "page": 1, "rowsPerPage": 15}
        page.emit(table, "request", {"pagination": request})
        await eventually(lambda: table.pagination.get("sortBy") == "error")
        errors = [row["error"] for row in table.rows]
        assert errors == sorted(errors, reverse=True)
        largest = errors[0]

        page.emit(table, "request", {"pagination": {**request, "page": 2}})
        await eventually(lambda: table.pagination.get("page") == 2)
        assert len(table.rows) == 15
        assert all(row["error"] <= largest for row in table.rows)

        # A later refresh keeps the order the user chose.
        page.element("Title").value = "edited"
        await eventually(lambda: page.plot_title() == "edited")
        assert table.pagination.get("sortBy") == "error"
        page_two = [row["error"] for row in table.rows]
        assert page_two == sorted(page_two, reverse=True)


async def test_a_plot_click_highlights_the_record_in_the_table(directory, monkeypatch):
    async with open_page(directory, "a.toml", monkeypatch) as page:
        table = page.of_type("Table")
        await eventually(lambda: table.pagination.get("rowsNumber") == N)

        page.emit(
            page.of_type("Plotly"),
            "plotly_click",
            {"points": [{"customdata": ["30", 0.0, "pass"]}]},
        )
        # Record 30 is on page 3, not the one shown; the highlight is set
        # anyway, so paging to it finds it selected.
        assert page.state.selection == "30"
        assert [row["key"] for row in table.selected] == ["30"]


async def test_a_stale_pagination_from_the_client_is_corrected(directory, monkeypatch):
    """NiceGUI stores whatever pagination the client reports, rowsNumber included."""
    async with open_page(directory, "a.toml", monkeypatch) as page:
        table = page.of_type("Table")
        await eventually(lambda: table.pagination.get("rowsNumber") == N)

        stale = {"sortBy": None, "descending": False, "page": 2, "rowsPerPage": 15}
        page.emit(table, "update:pagination", {**stale, "rowsNumber": 0})
        await eventually(lambda: table.pagination.get("rowsNumber") == N)
        assert table.pagination.get("page") == 2


class _FakeTable:
    def __init__(self) -> None:
        self.rows: list = []
        self.pagination: dict = {}
        self.selected: list = []

    def update(self) -> None:
        pass

    def props(self, *args, **kwargs):
        return self


class _FakeLabel:
    text = ""


async def test_rows_that_arrive_mid_sort_are_not_replaced_by_the_old_sort():
    """A header click sorts off the loop; a refresh can land before it finishes.

    The finished sort is of the *old* rows, so it must be dropped, and the new
    rows sorted instead -- or the table would show a dataset that is gone.
    """
    import asyncio

    from nicegui import core

    from parity_plot.config import ParityConfig
    from parity_plot.designer.panels import table as table_mod
    from parity_plot.designer.state import DesignerState
    from parity_plot.designer.table_rows import UNSORTED
    from parity_plot.designer.view import View

    def rows(*errors: float) -> list[dict]:
        return [{"key": f"k{e}", "error": e} for e in errors]

    old, new = rows(1.0, 3.0, 2.0), rows(10.0, 30.0, 20.0)
    held = threading.Event()
    first_sort: list[str] = []
    real_sort = table_mod.sort_rows

    def slow_first_sort(items, *args):
        if not first_sort:
            first_sort.append("held")
            held.wait(timeout=20)
        return real_sort(items, *args)

    core.loop = asyncio.get_running_loop()
    try:
        table_mod.sort_rows = slow_first_sort
        panel = table_mod.TablePanel(
            DesignerState(config=ParityConfig()), _FakeTable(), _FakeLabel()
        )
        await panel.show(View(figure=None, error=None, rows=old), UNSORTED)

        sorting = asyncio.ensure_future(
            panel.request({"sortBy": "error", "descending": True})
        )
        await eventually(lambda: bool(first_sort))  # the old rows are sorting
        await panel.show(View(figure=None, error=None, rows=new), UNSORTED)
        held.set()
        await sorting
    finally:
        table_mod.sort_rows = real_sort
        core.loop = None

    assert [row["error"] for row in panel.rows] == [30.0, 20.0, 10.0]
