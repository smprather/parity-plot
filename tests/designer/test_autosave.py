"""Auto-save must be cheap, atomic, and honest about failure.

Four defects from the 2026-09-26 scan, all in the same few lines:

* **Every refresh wrote the file** -- 3-4 NFS round trips while holding the
  refresh lock, and filter/brush refreshes re-saved an *unchanged* config.
  Typing in a text control serialised one write per keystroke.
* **Writes were not atomic.** ``Path.write_text`` truncates then writes, so an
  NFS timeout, a crash, or a concurrent reader (the CLI, another tab's picker)
  can see an empty or half-written TOML.
* **Failures were invisible.** An ``OSError`` escaped ``refresh()`` *after* the
  status bar was painted "Ready", so the views behind it never updated and the
  only evidence was a line in the server log.
* **The debounce was missing**, so the above happened once per keystroke.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from parity_plot.config import ParityConfig
from parity_plot.designer.session import Debouncer, Session


def config_with(title: str) -> ParityConfig:
    return ParityConfig().merge(plot={"title": title})


def bound(tmp_path: Path, title: str = "first") -> Session:
    path = tmp_path / "parity.toml"
    path.write_text("", encoding="utf-8")
    session = Session(config_path=path)
    session.saved_config = config_with(title)
    return session


def test_an_unchanged_config_is_not_rewritten(tmp_path):
    """The single biggest saving: most refreshes have nothing to write."""
    session = bound(tmp_path)
    path = session.config_path
    assert path is not None
    path.write_text("untouched = true\n", encoding="utf-8")
    before = path.stat().st_mtime_ns

    assert not session.is_dirty(config_with("first"))
    assert session.autosave(config_with("first")) is None
    assert path.stat().st_mtime_ns == before
    assert path.read_text(encoding="utf-8") == "untouched = true\n"


def test_a_changed_config_is_written(tmp_path):
    session = bound(tmp_path)
    assert session.is_dirty(config_with("second"))
    session.autosave(config_with("second"))
    path = session.config_path
    assert path is not None
    assert "second" in path.read_text(encoding="utf-8")


def test_saving_marks_the_config_clean(tmp_path):
    """Otherwise every later refresh re-saves the same thing."""
    session = bound(tmp_path)
    session.autosave(config_with("second"))
    assert not session.is_dirty(config_with("second"))


def test_unbound_autosave_is_a_no_op():
    session = Session()
    assert session.autosave(config_with("x")) is None


def test_a_save_leaves_no_temporary_file_behind(tmp_path):
    session = bound(tmp_path)
    path = session.config_path
    assert path is not None
    session.save(config_with("second"), path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["parity.toml"]


def test_a_failed_write_leaves_the_previous_file_intact(tmp_path, monkeypatch):
    """The point of write-temp-then-rename: a torn write must not be visible.

    ``os.replace`` is where the failure is simulated because it is the last
    step; everything before it has already touched only the temp file.
    """
    session = bound(tmp_path)
    path = session.config_path
    assert path is not None
    path.write_text("original = true\n", encoding="utf-8")

    def boom(src, dst):
        raise OSError("NFS: Stale file handle")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        session.save(config_with("second"), path)

    # The old content is still there, whole, and no temp file survives.
    assert path.read_text(encoding="utf-8") == "original = true\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["parity.toml"]


def test_a_save_never_leaves_a_zero_length_file(tmp_path):
    """A reader must never observe the truncate-before-write window."""
    session = bound(tmp_path)
    path = session.config_path
    assert path is not None
    for i in range(20):
        session.save(config_with(f"title {i}"), path)
        assert path.stat().st_size > 0


def test_a_save_failure_does_not_mark_the_config_clean(tmp_path, monkeypatch):
    """Otherwise a failed save is invisible *and* never retried."""
    session = bound(tmp_path)
    monkeypatch.setattr(
        "os.replace", lambda src, dst: (_ for _ in ()).throw(OSError("nope"))
    )
    with pytest.raises(OSError):
        session.save(config_with("second"))
    assert session.is_dirty(config_with("second"))


def test_a_save_failure_is_reported_not_raised(tmp_path, monkeypatch):
    """``autosave`` is the background path: it reports, it does not explode.

    The caller's job is to put the message in the status bar; an exception here
    would abort the refresh instead, which is how the failure became invisible
    in the first place.
    """
    session = bound(tmp_path)
    monkeypatch.setattr(
        "os.replace", lambda src, dst: (_ for _ in ()).throw(OSError("Stale"))
    )
    problem = session.autosave(config_with("second"))
    assert problem is not None
    assert "Stale" in problem


def test_a_successful_autosave_reports_no_problem(tmp_path):
    session = bound(tmp_path)
    assert session.autosave(config_with("second")) is None


async def test_a_burst_of_changes_collapses_into_one_save(tmp_path):
    """Typing in a text control must not mean one NFS write per keystroke."""
    session = bound(tmp_path)
    writes: list[str] = []

    def record(config) -> None:
        writes.append(config.plot.title or "")
        session.autosave(config)

    # A plain function, not a rebound method: the Debouncer captures the
    # callable it is given, so patching `session.autosave` afterwards would
    # never be seen.
    debouncer = Debouncer(record, delay=0.01)

    for i in range(8):
        debouncer.schedule(config_with(f"keystroke {i}"))
    assert not writes, "saved during the burst instead of waiting"

    await asyncio.sleep(0.05)
    # One write, carrying the last value -- not eight writes.
    assert writes == ["keystroke 7"]


async def test_a_change_after_the_burst_schedules_again():
    writes: list[str] = []
    debouncer = Debouncer(
        lambda config: writes.append(config.plot.title or ""), delay=0.01
    )

    debouncer.schedule(config_with("one"))
    await asyncio.sleep(0.05)
    debouncer.schedule(config_with("two"))
    await asyncio.sleep(0.05)
    assert writes == ["one", "two"]


async def test_the_latest_value_wins_within_one_burst():
    """The value is read at fire time, so a mid-burst edit is not lost."""
    writes: list[str] = []
    debouncer = Debouncer(
        lambda config: writes.append(config.plot.title or ""), delay=0.01
    )

    debouncer.schedule(config_with("first"))
    debouncer.schedule(config_with("second"))
    await asyncio.sleep(0.05)
    assert writes == ["second"]


async def test_an_edit_made_while_a_save_is_in_flight_is_written():
    """On NFS a save outlasts the debounce; the edit made during it must land.

    The task used to fire once and exit: a request arriving while the work ran
    found a live task, parked itself in ``_pending``, and was never picked up --
    the bound file silently stayed one edit behind until the next keystroke.
    """
    writes: list[str] = []

    async def slow_save(config) -> None:
        await asyncio.sleep(0.05)  # the write takes longer than the delay
        writes.append(config.plot.title or "")

    debouncer = Debouncer(slow_save, delay=0.01)
    debouncer.schedule(config_with("A"))
    await asyncio.sleep(0.03)  # the save of A is now in flight
    debouncer.schedule(config_with("B"))
    await asyncio.sleep(0.2)
    assert writes == ["A", "B"]


async def test_flush_writes_a_pending_request_now():
    """A config swap flushes: the old design's last edit reaches its own file."""
    writes: list[str] = []
    debouncer = Debouncer(
        lambda config: writes.append(config.plot.title or ""), delay=10
    )

    debouncer.schedule(config_with("last edit"))
    await debouncer.flush()
    assert writes == ["last edit"]
    await asyncio.sleep(0.02)
    assert writes == ["last edit"], "the flushed request fired a second time"


async def test_flush_waits_for_a_save_in_flight_then_writes_the_pending_one():
    writes: list[str] = []

    async def slow_save(config) -> None:
        await asyncio.sleep(0.05)
        writes.append(config.plot.title or "")

    debouncer = Debouncer(slow_save, delay=0.01)
    debouncer.schedule(config_with("A"))
    await asyncio.sleep(0.03)  # A in flight
    debouncer.schedule(config_with("B"))
    await debouncer.flush()
    assert writes == ["A", "B"]


async def test_flush_with_nothing_pending_is_a_no_op():
    debouncer = Debouncer(lambda config: None, delay=0.01)
    await debouncer.flush()


def test_an_autosave_waiting_on_the_lock_writes_where_the_session_now_points(
    tmp_path,
):
    """Saves run in worker threads, so an auto-save can queue behind Save As.

    It must read the bound path once it holds the lock. Read before waiting, it
    wrote the old file and re-bound the session to it, undoing the Save As.
    """
    import threading
    import time

    from parity_plot.designer import session as session_mod

    session = bound(tmp_path)
    old = session.config_path
    new = tmp_path / "renamed.toml"

    with session_mod._SAVE_LOCK:
        worker = threading.Thread(
            target=session.autosave, args=(config_with("queued"),)
        )
        worker.start()
        time.sleep(0.05)  # the worker is now blocked on the lock
        session.config_path = new  # what a Save As does under the lock
    worker.join(timeout=5)

    assert session.config_path == new
    assert new.exists() and "queued" in new.read_text(encoding="utf-8")
    assert old is not None and old.read_text(encoding="utf-8") == ""


def test_a_symlinked_config_is_written_through_the_link(tmp_path):
    """A rename replaces the link itself; the shared target must be updated."""
    shared = tmp_path / "shared"
    shared.mkdir()
    real = shared / "parity.toml"
    real.write_text("", encoding="utf-8")
    link = tmp_path / "parity.toml"
    link.symlink_to(real)

    session = Session(config_path=link)
    session.saved_config = config_with("first")
    assert session.autosave(config_with("second")) is None

    assert link.is_symlink(), "the save replaced the link with a private copy"
    assert "second" in real.read_text(encoding="utf-8")
    assert not list(shared.glob(".*.tmp")) and not list(tmp_path.glob(".*.tmp"))


def test_a_save_keeps_the_files_permissions(tmp_path):
    session = bound(tmp_path)
    path = session.config_path
    assert path is not None
    path.chmod(0o664)
    session.autosave(config_with("second"))
    assert path.stat().st_mode & 0o777 == 0o664


async def test_the_debouncer_can_run_async_work():
    """Auto-save is file I/O, so it has to be off the event loop.

    The work is awaited rather than called inline, which is what keeps an NFS
    write from stalling the heartbeat between two keystrokes.
    """
    ran: list[str] = []

    async def work(config) -> str | None:
        await asyncio.sleep(0)
        ran.append(config.plot.title or "")
        return None

    debouncer = Debouncer(work, delay=0.01)
    debouncer.schedule(config_with("off-loop"))
    assert not ran
    await asyncio.sleep(0.05)
    assert ran == ["off-loop"]


async def test_an_async_failure_is_reported_too():
    """A debounced async save that fails must still reach the status bar."""

    async def work(config) -> str | None:
        await asyncio.sleep(0)
        return "Auto-save failed: Stale"

    debouncer = Debouncer(work, delay=0.01)
    seen: list[Any] = []
    debouncer.on_error = seen.append
    debouncer.schedule(config_with("x"))
    await asyncio.sleep(0.05)
    assert seen == ["Auto-save failed: Stale"]


def test_a_debounced_save_reports_its_failure(tmp_path, monkeypatch):
    """The debounced path must surface an OSError, not swallow it silently."""
    session = bound(tmp_path)
    monkeypatch.setattr(
        "os.replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom"))
    )
    debouncer = Debouncer(session.autosave, delay=0.01)
    seen: list[str | None] = []
    debouncer.on_error = seen.append

    async def go() -> None:
        debouncer.schedule(config_with("second"))
        await asyncio.sleep(0.05)

    asyncio.run(go())
    assert seen
    assert seen[0] is not None
    assert "boom" in seen[0]


async def test_flush_drains_a_request_scheduled_while_it_ran():
    """A swap flushes, then swaps with no await between: nothing may be left."""
    writes: list[str] = []
    debouncer: Debouncer

    async def slow_save(config) -> None:
        await asyncio.sleep(0.03)
        writes.append(config.plot.title or "")
        if config.plot.title == "A":
            debouncer.schedule(config_with("B"))  # an edit during the flush

    debouncer = Debouncer(slow_save, delay=10)
    debouncer.schedule(config_with("A"))
    await debouncer.flush()
    assert writes == ["A", "B"]
