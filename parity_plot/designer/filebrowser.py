# parity_plot/designer/filebrowser.py
"""Directory listing for the designer's file browser.

Pure: no nicegui. Resolves the path so `..` navigation collapses and `cwd` is
absolute. Dotfiles are omitted so the browser is not cluttered with `.git`,
`.venv`, etc. The filesystem root has no parent, so `parent` is `None` there
and the UI can hide its "up" button instead of looping back onto the root.
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
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                dirs.append(Entry(entry.name, Path(entry.path), True, 0))
            elif entry.is_file(follow_symlinks=False) and fnmatch(entry.name, pattern):
                files.append(
                    Entry(entry.name, Path(entry.path), False, entry.stat().st_size)
                )

    dirs.sort(key=lambda e: e.name)
    files.sort(key=lambda e: e.name)
    return Listing(cwd=cwd, parent=parent, entries=dirs + files)