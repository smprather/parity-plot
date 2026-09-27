# parity_plot/designer/session.py
"""Where the designer's data and config came from, and where they go back to."""

from __future__ import annotations

import asyncio
import inspect
import os
import threading
from collections.abc import Callable, Hashable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import ConfigError, ParityConfig
from ..data import ParityData, load
from .serialize import config_to_toml

# Serialises every config write in this process. Two saves racing (Save As vs
# auto-save, or two browser tabs) would otherwise each write a temp file and
# rename it over the target, and the loser would silently overwrite the winner.
_SAVE_LOCK = threading.Lock()


def config_choices(directory: Path) -> list[Path]:
    """The parity-plot configs in ``directory``.

    Touchstone: the file parses as a ``ParityConfig`` and names at least one
    input file (``data.files``). A ``.toml`` that is malformed or unrelated is
    skipped, so the picker only offers files the designer can actually open.
    """
    out: list[Path] = []
    for path in sorted(Path(directory).glob("*.toml")):
        try:
            config = ParityConfig.from_toml(path)
        except ConfigError, ValueError, OSError:
            continue
        if config.data.files:
            out.append(path)
    return out


def config_choice_names(directory: Path, current: Path | None) -> list[str]:
    """Picker names, including a bound config outside the scanned directory."""
    names = [path.name for path in config_choices(directory)]
    if current is not None and current.name not in names:
        names.insert(0, current.name)
    return names


@dataclass
class Session:
    config_path: Path | None = None
    original_text: str | None = None
    disk_text: str | None = None
    saved_config: ParityConfig | None = None

    @classmethod
    def start(
        cls, data_paths: tuple[Path, ...], config_path: Path | None
    ) -> tuple[Session, ParityConfig, ParityData | None]:
        """Load config then data, with command-line paths winning.

        Same precedence as the CLI: an explicit path on the command line beats
        whatever the config file names. With no files anywhere, `data` is None
        and the designer starts empty.
        """
        if config_path is not None:
            text = Path(config_path).read_text(encoding="utf-8")
            config = ParityConfig.from_toml(config_path)
        else:
            text = None
            config = ParityConfig()

        if data_paths:
            overrides: dict = {"files": tuple(data_paths)}
            # Command-line paths win over the config file's files, so any ref/test
            # pointing at the old files no longer resolves. Re-derive them for a
            # single file (the first two numeric columns); for two files the user
            # must supply a config that names the right columns.
            if len(data_paths) == 1:
                from ..sources import open_sources

                cols = open_sources(data_paths).numeric_columns(config.data.na_values)
                if len(cols) < 2:
                    from ..data import DataError

                    raise DataError(
                        f"{data_paths[0].name}: need at least two numeric columns "
                        f"for ref/test; found {len(cols)} ({cols})"
                    )
                overrides["ref"] = cols[0]
                overrides["test"] = cols[1]
            config = config.merge(data=overrides)

        # No files chosen yet -> start empty rather than erroring; the file
        # browser fills this in.
        data = load(config.data) if config.data.files else None
        session = cls(
            config_path=Path(config_path) if config_path else None,
            original_text=text,
            disk_text=text,
            saved_config=config,
        )
        return session, config, data

    def is_dirty(self, config: ParityConfig) -> bool:
        return config != self.saved_config

    def save(self, config: ParityConfig, path: Path | None = None) -> Path:
        """Write ``config`` to ``path`` atomically. Returns the path written.

        Atomic because the file is hand-edited, committed, and read by the CLI
        and by other designer tabs: ``Path.write_text`` truncates first, so an
        NFS timeout, a crash, or a concurrent reader can catch an empty or
        half-written TOML. Writing a sibling temp file and renaming over the
        target makes the swap a single filesystem operation, and the old
        content stays whole until the instant it is replaced.
        """
        # One process-wide lock: two saves (Save As vs auto-save, or two tabs)
        # would otherwise interleave their temp-file renames and the loser would
        # write a stale config over the winner's.
        with _SAVE_LOCK:
            return self._save_locked(config, path)

    def _save_locked(self, config: ParityConfig, path: Path | None) -> Path:
        """The body of :meth:`save`; the caller holds ``_SAVE_LOCK``.

        The bound path is read *here*, under the lock, not by the caller. Saves
        run in worker threads now, so an auto-save that read ``config_path``
        before waiting on the lock could land after a Save As rebound the
        session -- and write the old config to the old file while re-binding the
        session back to it.
        """
        target = Path(path) if path is not None else self.config_path
        if target is None:
            raise ValueError("no config path to save to; choose one with Save As")
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        text = config_to_toml(config, existing=existing)
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(target, text)

        self.config_path = target
        self.disk_text = text
        # Marked clean only after the swap succeeded: a failed save must
        # stay dirty or it is never retried.
        self.saved_config = config
        return target

    def autosave(self, config: ParityConfig) -> str | None:
        """Write ``config`` to the bound file. Returns an error message, or None.

        The auto-save path: ``app.refresh()`` calls this after every change that
        leaves the config valid. Unbound (no file yet) is a no-op -- a New Design
        or data-only launch has nowhere to write until Save As binds a name.

        An unchanged config is skipped. Most refreshes change nothing (a brush
        that lands where it started, a filter re-applied), and each one used to
        cost several NFS round trips while the refresh lock was held.

        An ``OSError`` is *returned*, not raised. This runs inside the refresh,
        after the status bar has already been painted; letting it escape aborted
        the rest of the refresh and left the failure visible only in the server
        log. The caller puts the message in the status bar.
        """
        try:
            with _SAVE_LOCK:
                # Both checks under the lock, for the reason given in
                # _save_locked: a concurrent Save As may rebind or clean the
                # session while this call waits its turn.
                if self.config_path is None or not self.is_dirty(config):
                    return None
                self._save_locked(config, None)
        except OSError as exc:
            return f"Auto-save failed: {exc}"
        return None


def _write_atomic(target: Path, text: str) -> None:
    """Replace ``target`` with ``text`` in one step, via a sibling temp file.

    The temp file is in the same directory so the rename stays within one
    filesystem and is therefore atomic. A named temp rather than
    ``tempfile.mkstemp`` because the point is that the name is ours and the
    cleanup is ours; it is removed on every failure path, so a failed save
    leaves nothing behind but the old file.

    A symlinked config is written *through* the link, and an existing file
    keeps its permission bits. A rename replaces whatever sits at the name, so
    without both, a ``parity.toml`` linked into a shared project area would
    become a private copy and the shared file would silently stop changing, and
    a group-writable config would drop to the umask default.
    """
    target = target.resolve()
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        with suppress(FileNotFoundError):
            os.chmod(temp, target.stat().st_mode & 0o7777)
        os.replace(temp, target)
    except BaseException:
        # OSError and KeyboardInterrupt/SystemExit alike: a half-written temp
        # file would otherwise be left in the user's config directory.
        with suppress(OSError):
            temp.unlink()
        raise


class Debouncer:
    """Collapse a burst of requests into one call, carrying the latest value.

    Auto-save fires from ``app.refresh``, which a text control triggers on every
    keystroke. On a network filesystem that is one write per character. The
    work runs *after* ``delay``, so a burst of edits costs one write, and the
    argument is read at fire time rather than captured -- so the value written
    is the newest one, not the first.

    ``on_error`` receives whatever the work returned when it was a message, so
    a failed save can be reported instead of disappearing.

    A request that arrives while the work is *running* is not lost: the task
    loops until nothing is pending. On NFS a save takes longer than the delay,
    so an edit made during one is the ordinary case, not a corner.

    Requests are collapsed per ``key``: the latest one for each key is kept.
    Auto-save keys by session, because a refresh computes off the loop and can
    paint -- and schedule its save -- after another config has been opened;
    with one shared slot the new design's first save would replace, and so
    lose, the old design's last edit.
    """

    def __init__(self, work: Callable[..., Any], delay: float = 0.4) -> None:
        self._work = work
        self._delay = delay
        self._task: asyncio.Task | None = None
        self._pending: dict[Hashable, tuple[tuple, dict]] = {}
        self._calling = False
        #: Called with the work's return value, if it returned one. Set by the
        #: app to push a failure into the status bar.
        self.on_error: Callable[[Any], None] | None = None

    def schedule(self, *args: Any, key: Hashable = None, **kwargs: Any) -> None:
        """Request a call after the delay, replacing any pending one for ``key``."""
        self._pending[key] = (args, kwargs)
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.ensure_future(self._run())

    async def flush(self) -> None:
        """Run every pending request now, after any call already in flight.

        Used when the config is swapped: the pending save belongs to the design
        being replaced and must reach *its* file before the swap, not be dropped
        (the user's last edit) or delayed until the new design's first edit
        replaces it.
        """
        batch, self._pending = self._pending, {}
        task, self._task = self._task, None
        if task is not None and not task.done():
            if self._calling:
                # Let the in-flight write finish; with nothing pending, its
                # loop then exits.
                await task
            else:
                task.cancel()
        # Drain, not just one pass: a request scheduled while this awaited is
        # still the old design's, and must not be left for the next design's
        # first edit to replace.
        while batch:
            for pending in batch.values():
                await self._call(pending)
            batch, self._pending = self._pending, {}

    async def _run(self) -> None:
        while self._pending:
            await asyncio.sleep(self._delay)
            batch, self._pending = self._pending, {}
            for pending in batch.values():
                await self._call(pending)

    async def _call(self, pending: tuple[tuple, dict]) -> None:
        args, kwargs = pending
        self._calling = True
        try:
            result = self._work(*args, **kwargs)
            # The work may be async -- auto-save is a file write and has to run
            # off the event loop, so the debounced call is offloaded too.
            if inspect.isawaitable(result):
                result = await result
        finally:
            self._calling = False
        if result is not None and self.on_error is not None:
            self.on_error(result)
