"""Running blocking file I/O off the NiceGUI event loop, and debug logging.

The designer reads CSVs, scans directories and writes configs from UI event
handlers. Those handlers run on the asyncio event loop, and the loop also
answers the websocket heartbeat: a handler that blocks on a slow filesystem
(NFS is the reported case) for a few seconds starves the heartbeat, the client
times out and the user sees the reconnect overlay while the server is in fact
fine. Every such read therefore goes through :func:`offload`, which pushes the
work to NiceGUI's thread pool via ``run.io_bound``.

When no loop is running (tests importing the pure functions directly, script
mode), :func:`offload` runs the callable inline instead.

:func:`debug_log` is a lightweight transcript channel for the designer's
``--debug`` mode: timestamped, elapsed-marked lines on stderr, always safe to
call whether or not debug mode was enabled.
"""

from __future__ import annotations

import inspect
import logging
import sys
import time
from typing import Any, Callable, TypeVar, cast

_T = TypeVar("_T")

_T0 = time.monotonic()
_log = logging.getLogger("parity.designer")


def debug_enabled() -> bool:
    """Whether the designer was started with ``--debug``."""
    return logging.getLogger("parity.designer").isEnabledFor(logging.DEBUG)


def setup_debug_logging() -> None:
    """Turn on the transcript: designer DEBUG plus framework INFO on stderr.

    Deliberately re-runnable: tests and repeated launches call it without
    duplicating handlers. Framework loggers (socket.io, uvicorn) go to INFO so
    a transcript shows connect/disconnect and request timing without the noise
    of full DEBUG.
    """
    root = logging.getLogger()
    if any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
        for h in root.handlers
    ):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-5s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    _log.setLevel(logging.DEBUG)
    for name in ("engineio.server", "socketio.server", "uvicorn.error"):
        logging.getLogger(name).setLevel(logging.INFO)


def debug_log(message: str, *args: Any) -> None:
    """Append a designer transcript line (a no-op unless ``--debug``)."""
    elapsed = time.monotonic() - _T0
    _log.debug("[%7.2fs] %s", elapsed, message % args if args else message)


async def offload(func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Run a blocking callable off the event loop and await its result.

        With NiceGUI serving, this is ``run.io_bound`` (thread pool). Without a
        running loop -- tests, script mode -- the callable runs inline, so the
        pure functions keep their synchronous behaviour under test.

    ``io_bound`` documents None-on-shutdown as an interim shape; that can only
    happen while the app is stopping, so it is detected via ``app.is_stopping``
    rather than by inspecting the result -- a callable that legitimately returns
    None (``Session.autosave`` on an unbound config) must not look cancelled.
    """
    try:
        from nicegui import core, run
    except ImportError:
        return func(*args, **kwargs)
    if not core.is_loop_running():
        return func(*args, **kwargs)
    result = await run.io_bound(func, *args, **kwargs)
    if result is None and core.app.is_stopping:  # pragma: no cover -- shutdown
        raise RuntimeError("offloaded call was cancelled during shutdown")
    # `io_bound` is typed `R | None` because None doubles as its cancellation
    # sentinel. A callable that genuinely returns None (Session.autosave on an
    # unbound config) is legitimate, and the shutdown case above is the only
    # real loss -- so narrow rather than refuse.
    return cast(_T, result)


def sync_refresher(
    refresh: Callable[[], Any], name: str = "refresh"
) -> Callable[[], None]:
    """Adapt a possibly-async ``on_change`` for a panel that commits synchronously.

    Most designer panels commit from a *sync* handler -- a switch toggled, a
    tolerance checkbox clicked -- and then call ``on_change()`` and drop the
    return value. ``app.refresh`` is async, so passing it straight through
    created a coroutine nobody awaited: no redraw, no status bar, no auto-save,
    just a ``coroutine 'refresh' was never awaited`` line in the log.

    This wrapper calls the refresher and schedules the coroutine if there is
    one, so both sync and async refreshers work in a sync slot. Panels that can
    ``await`` their ``on_change`` (the data panel) do not need it.
    """
    from nicegui import background_tasks

    def call() -> None:
        result = refresh()
        if inspect.isawaitable(result):
            background_tasks.create(result, name=name)

    return call
