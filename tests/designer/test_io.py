# tests/designer/test_io.py
"""The off-the-loop runner and the --debug transcript channel."""

from __future__ import annotations

import asyncio
import logging

import pytest

from parity_plot.designer import io as designer_io


async def test_offload_runs_inline_without_a_running_loop():
    """Outside a NiceGUI loop, offload must behave like a plain call.

    Tests and script mode have no loop; the pure functions keep their
    synchronous behaviour, and no nicegui machinery is required.
    """

    def slow_read(x: int) -> int:
        return x * 2

    assert await designer_io.offload(slow_read, 21) == 42


async def test_offload_passes_kwargs_through():
    def add(a: int, b: int = 0) -> int:
        return a + b

    assert await designer_io.offload(add, 1, b=2) == 3


def test_offload_works_sync_too():
    """A caller may not have an event loop at all (plain test function)."""
    result = asyncio.run(designer_io.offload(len, "abc"))
    assert result == 3


def test_setup_debug_logging_is_idempotent():
    designer_io.setup_debug_logging()
    handlers_before = len(logging.getLogger().handlers)
    designer_io.setup_debug_logging()
    assert len(logging.getLogger().handlers) == handlers_before
    assert designer_io.debug_enabled()


def test_debug_log_is_a_no_op_when_disabled(caplog):
    with caplog.at_level(logging.WARNING, logger="parity.designer"):
        designer_io.debug_log("nothing %s", "here")
        assert "nothing" not in caplog.text


async def test_a_cancelled_offload_is_cancelled_not_none():
    """``run.io_bound`` swallows a cancellation and returns None.

    ``offload`` used to pass that None on as the call's result whenever the app
    was not stopping, so a cancelled handler carried on with it -- and crashed
    unpacking it ("cannot unpack non-iterable NoneType object"), which is how it
    showed up under ./check-slow-nfs at test teardown. A cancelled await must
    stay a cancellation.
    """
    import time

    from nicegui import core

    from parity_plot.designer.io import offload

    continued: list[str] = []

    async def caller() -> None:
        await offload(lambda: time.sleep(0.3) or ("result", True))
        continued.append("carried on after the cancel")

    core.loop = asyncio.get_running_loop()
    try:
        task = asyncio.ensure_future(caller())
        await asyncio.sleep(0.05)  # the call is in the thread pool
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        core.loop = None
    assert continued == []


# --- Coalescer ---------------------------------------------------------------


async def test_a_burst_during_a_run_is_one_more_run_not_many():
    from parity_plot.designer.io import Coalescer

    runs: list[int] = []
    gate = asyncio.Event()

    async def job() -> None:
        runs.append(len(runs))
        if len(runs) == 1:
            await gate.wait()

    coalescer = Coalescer(job)
    first = asyncio.ensure_future(coalescer.request())
    await asyncio.sleep(0)  # run 1 is in flight
    burst = [asyncio.ensure_future(coalescer.request()) for _ in range(5)]
    await asyncio.sleep(0)
    assert coalescer.pending
    gate.set()
    await asyncio.gather(first, *burst)
    assert runs == [0, 1]
    assert not coalescer.pending


async def test_a_request_resumes_only_after_a_run_that_started_after_it():
    from parity_plot.designer.io import Coalescer

    seen: list[str] = []
    state = {"value": "old"}
    gate = asyncio.Event()

    async def job() -> None:
        snapshot = state["value"]
        await gate.wait()
        seen.append(snapshot)

    coalescer = Coalescer(job)
    first = asyncio.ensure_future(coalescer.request())
    await asyncio.sleep(0)  # a run with "old" is in flight
    state["value"] = "new"
    later = asyncio.ensure_future(coalescer.request())
    gate.set()
    await later
    assert seen[-1] == "new"
    await first


async def test_a_cancelled_caller_does_not_cancel_the_run():
    from parity_plot.designer.io import Coalescer

    done: list[str] = []
    gate = asyncio.Event()

    async def job() -> None:
        await gate.wait()
        done.append("ran")

    coalescer = Coalescer(job)
    caller = asyncio.ensure_future(coalescer.request())
    await asyncio.sleep(0)
    caller.cancel()
    gate.set()
    await asyncio.sleep(0.01)
    assert done == ["ran"]
