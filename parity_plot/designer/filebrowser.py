# parity_plot/designer/filebrowser.py
"""Directory listing for the designer's file browser.

Pure: no nicegui. Resolves the path so `..` navigation collapses and `cwd` is
absolute. Dot-directories are shown so the browser can navigate into them,
while dotfiles remain omitted. The filesystem root has no parent, so `parent`
is `None` there and the UI can hide its "up" button instead of looping back
onto the root.

Symlinks are followed for classification. That is the common case on NFS, where
a project's data lives behind a link; classifying with ``follow_symlinks=False``
made such an entry neither a dir nor a file, so it vanished from the listing
with no indication that anything was wrong. A dangling link is dropped instead
of raising, so one stale entry cannot break the directory around it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    name: str
    path: Path
    is_dir: bool
    size: int  # bytes for files, 0 for dirs


@dataclass(frozen=True)
class Listing:
    cwd: Path
    parent: Path | None
    entries: list[Entry]


def list_dir(path: str | Path, pattern: str = "*.csv") -> Listing:
    cwd = Path(path).resolve()
    if not cwd.is_dir():
        raise NotADirectoryError(str(cwd))

    parent: Path | None = cwd.parent if cwd.parent != cwd else None

    dirs: list[Entry] = []
    files: list[Entry] = []
    with os.scandir(cwd) as it:
        for entry in it:
            # Classify by following symlinks: a project on NFS routinely keeps
            # its data behind a link, and `follow_symlinks=False` made such an
            # entry neither a dir nor a file -- so it was silently dropped and
            # the browser looked like it had never seen the file.
            is_dir = _is_dir(entry)
            if is_dir:
                dirs.append(Entry(entry.name, Path(entry.path), True, 0))
            elif entry.name.startswith("."):
                continue
            elif fnmatch(entry.name, pattern):
                size = _size(entry)
                if size is not None:
                    files.append(Entry(entry.name, Path(entry.path), False, size))

    dirs.sort(key=lambda e: e.name)
    files.sort(key=lambda e: e.name)
    return Listing(cwd=cwd, parent=parent, entries=dirs + files)


def _is_dir(entry: os.DirEntry) -> bool:
    """Whether this entry is a directory, following a symlink if it is one.

    A dangling link (the target is gone) is not a directory and not a file, so
    it is dropped rather than raising: a half-populated mount should not break
    the listing of everything around it.
    """
    try:
        return entry.is_dir(follow_symlinks=True)
    except OSError:
        return False


def _size(entry: os.DirEntry) -> int | None:
    """Byte size of a non-directory entry, or None if it is not readable."""
    try:
        if not entry.is_file(follow_symlinks=True):
            return None
        return entry.stat(follow_symlinks=True).st_size
    except OSError:
        return None
