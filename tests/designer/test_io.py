# tests/designer/test_io.py
"""The off-the-loop runner and the --debug transcript channel."""

from __future__ import annotations

import asyncio
import logging

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
