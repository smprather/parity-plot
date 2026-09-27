"""One guarded commit at a time in the data panel, latest request wins.

The 2026-09-26 scan measured a single Add File turning into roughly six full
reads of every open CSV. The mechanism was the suspension guard:
``refresh_options`` raised it, assigned ``ref_sel.value``/``test_sel.value``,
and lowered it again *before any await* -- and NiceGUI runs an async
``on_change`` handler as its own background task, so every one of those
emissions re-entered the commit with the guard already down.

The guard therefore has to be checked at the moment of emission, which is the
only instant still on the caller's stack. ``CommitGate`` owns that check, plus
the coalescing that turns a burst of emissions into one commit and one follow-up
for whatever the user last chose.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from typing import Any, TypeAlias

import pytest

from parity_plot.designer.panels.data_panel import CommitGate, _row_limit

# A spawn receives a coroutine (not a bare Awaitable): the gate builds one, and
# a fake spawn that declines to run it must close() it or the un-awaited
# coroutine becomes a RuntimeWarning -- which this suite treats as an error.
Spawn: TypeAlias = Callable[[Coroutine[Any, Any, None]], None]
Work: TypeAlias = Callable[[], Awaitable[None]]


def recorder(store: list[object]) -> Spawn:
    """A spawn that records the coroutine and closes it instead of running it.

    Closing matters: the suite treats an un-awaited coroutine as an error, and a
    coroutine handed to a fake spawn is never going to run.
    """

    def spawn(awaitable: Coroutine[Any, Any, None]) -> None:
        store.append(awaitable)
        awaitable.close()

    return spawn


def catching_spawn(errors: list[BaseException]) -> Spawn:
    """A spawn that runs the coroutine as a task and captures any exception.

    Standing in for ``background_tasks.create``, which routes an escaping
    exception to NiceGUI's global handler rather than to the test.
    """

    def spawn(awaitable: Coroutine[Any, Any, None]) -> None:
        async def run() -> None:
            try:
                await awaitable
            except Exception as exc:  # noqa: BLE001 -- the test wants the type
                errors.append(exc)

        asyncio.ensure_future(run())

    return spawn


async def noop() -> None:
    return None


async def settle(times: int = 15) -> None:
    """Let the gate's spawned task(s) run to completion."""
    for _ in range(times):
        await asyncio.sleep(0)


@pytest.fixture
async def nicegui_loop():
    """Make nicegui believe it is serving, as ``launch.run`` would.

    Async because ``asyncio_mode = "auto"`` turns async fixtures into coroutine
    fixtures, and a sync one would run with no loop to hand to ``core.loop``.
    """
    from nicegui import core

    previous = core.loop
    core.loop = asyncio.get_running_loop()
    yield
    core.loop = previous


def test_a_request_inside_the_suspension_is_dropped():
    """The scan's mechanism, in one assertion: a suspended emission does nothing."""
    scheduled: list[object] = []
    gate = CommitGate(spawn=recorder(scheduled))

    with gate.suspend():
        gate.submit(noop)

    assert scheduled == []


def test_the_guessed_ref_and_test_do_not_schedule_anything():
    """What ``refresh_options`` does: assign the selects under the guard, then release.

    Both assignments emit a value change, and an unguarded commit on each is two
    extra full reads of every open file.
    """
    scheduled: list[object] = []
    gate = CommitGate(spawn=recorder(scheduled))

    with gate.suspend():
        gate.submit(noop)  # ref_sel.value = ...
        gate.submit(noop)  # test_sel.value = ...

    assert scheduled == []


def test_the_preview_row_count_survives_a_half_typed_field():
    """A ``ui.number`` mid-edit is the common case, not an edge case.

    ``int("")`` and ``int("-")`` both raise, and the preview read happens in a
    background task, so the user would see an empty dialog and no message.
    """
    assert _row_limit(None) == 100
    assert _row_limit("") == 100
    assert _row_limit("-") == 100
    assert _row_limit("1e") == 100


def test_the_preview_row_count_is_clamped():
    assert _row_limit(0) == 1
    assert _row_limit(-5) == 1
    assert _row_limit(10_000_000) == 10_000
    assert _row_limit(250) == 250


def test_a_request_outside_the_suspension_is_spawned():
    scheduled: list[object] = []
    gate = CommitGate(spawn=recorder(scheduled))

    gate.submit(noop)

    assert len(scheduled) == 1
    assert gate.in_flight == 1


def test_the_suspension_is_released_even_if_the_body_raises():
    """A leak here would wedge the panel: nothing would ever commit again."""
    gate = CommitGate(spawn=recorder([]))
    with suppress(RuntimeError):
        with gate.suspend():
            raise RuntimeError("option derivation failed")
    assert not gate.is_suspended


async def test_only_one_commit_runs_at_a_time(nicegui_loop):
    """Coalescing: a burst of edits is one commit, then one for the latest."""
    order: list[str] = []
    gate = CommitGate()

    async def slow() -> None:
        order.append("start")
        await asyncio.sleep(0)
        order.append("end")

    gate.submit(slow)
    # Let the first commit actually start before the burst arrives -- these are
    # separate browser events, so the loop turns in between them.
    await asyncio.sleep(0)
    for _ in range(3):  # arrive while the first is still in flight
        gate.submit(slow)
    await settle()

    # One run per burst: the in-flight one plus exactly one catch-up, and never
    # two overlapping -- which is what fanned six concurrent reads into one.
    assert order == ["start", "end", "start", "end"]


async def test_the_catch_up_sees_the_latest_value(nicegui_loop):
    """Latest request wins: the rerun reads current state, not a stale snapshot."""
    seen: list[str] = []
    choice = "first"
    gate = CommitGate()

    async def read_choice() -> None:
        seen.append(choice)
        await asyncio.sleep(0)

    gate.submit(read_choice)
    await asyncio.sleep(0)  # this one runs now, and sees "first"
    choice = "second"
    gate.submit(read_choice)  # both of these land while it is in flight
    choice = "third"
    gate.submit(read_choice)
    await settle()

    # Two runs, not four: the in-flight one and a single catch-up reading the
    # newest value.
    assert seen == ["first", "third"]


async def test_a_failed_commit_does_not_wedge_the_gate():
    """An exception must release the gate, or the panel dies after one error."""
    runs: list[str] = []
    errors: list[BaseException] = []
    gate = CommitGate(spawn=catching_spawn(errors))

    async def boom() -> None:
        runs.append("boom")
        await asyncio.sleep(0)
        raise RuntimeError("read failed")

    async def after() -> None:
        runs.append("after")

    gate.submit(boom)
    await settle()
    gate.submit(after)
    await settle()

    assert [type(e).__name__ for e in errors] == ["RuntimeError"]
    assert runs == ["boom", "after"]
    assert gate.in_flight == 0
