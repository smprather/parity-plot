"""Starting the designer, and failing clearly when it cannot start."""

from __future__ import annotations

import socket
from pathlib import Path


class MissingDependencyError(RuntimeError):
    """The designer extra is not installed."""


def require_nicegui() -> None:
    """Fail with the install command rather than a bare ImportError."""
    try:
        import nicegui  # noqa: F401
    except ImportError as exc:
        raise MissingDependencyError(
            "the designer needs NiceGUI, which is an optional extra. "
            "Install it with:  uv sync --extra designer"
        ) from exc


def free_port(preferred: int) -> int:
    """Return ``preferred`` if it is free, otherwise any open port.

    Refusing to start because a stale server holds the port is a worse
    experience than moving to another one and saying so.
    """
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run(
    data_paths: tuple[Path, ...],
    config_path: Path | None,
    port: int,
    open_browser: bool,
) -> None:
    """Build the app and serve it. Imports NiceGUI lazily.

    Data and config are loaded *before* any UI machinery is touched, so a bad
    CSV or a malformed TOML fails immediately with a plain message instead of
    after a server has already started listening.
    """
    require_nicegui()

    from .session import Session

    session, config, data = Session.start(data_paths, config_path)

    from nicegui import ui

    from .app import build_app

    build_app(session, config, data)

    chosen = free_port(port)
    if chosen != port:
        print(f"port {port} is in use; serving on {chosen} instead")

    ui.run(
        port=chosen,
        show=open_browser,
        title="parity-plot designer",
        reload=False,
        favicon="📉",
    )