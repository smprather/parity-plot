# parity_plot/sources.py
"""Opening an arbitrary set of CSV files and resolving `file:column` references.

The plot compares two columns. In the general case they live in different files
with different layouts, so a source column is named `file:column` and resolved
against the open set. This module only reads and indexes; parsing to floats and
pairing stay in data.py.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .config import DEFAULT_NA_VALUES
from .data import DataError, _na_set, _read_rows


@dataclass(frozen=True)
class Column:
    file: Path
    name: str
    values: list[str]


@dataclass(frozen=True)
class Sources:
    order: tuple[Path, ...]
    tables: dict[Path, dict[str, list[str]]] = field(default_factory=dict)

    def columns(self) -> list[str]:
        return [
            f"{path.name}:{col}" for path in self.order for col in self.tables[path]
        ]

    def numeric_columns(
        self, na_values: Sequence[str] = DEFAULT_NA_VALUES
    ) -> list[str]:
        na = _na_set(na_values)
        out = []
        for path in self.order:
            for col, values in self.tables[path].items():
                if _is_numeric(values, na):
                    out.append(f"{path.name}:{col}")
        return out

    def numeric_refs(self, na_values: Sequence[str] = DEFAULT_NA_VALUES) -> list[str]:
        """Numeric columns as refs that :meth:`resolve` will actually accept.

        Same list as :meth:`numeric_columns`, but a file whose basename repeats
        among the open set is named by its full path -- see :meth:`ref`.
        """
        na = _na_set(na_values)
        out = []
        for path in self.order:
            for col, values in self.tables[path].items():
                if _is_numeric(values, na):
                    out.append(self.ref(path, col))
        return out

    def resolve(self, ref: str) -> Column:
        file_part, _, column = ref.rpartition(":")
        if not file_part:
            raise DataError(f"{ref!r} is not a file:column reference")
        path = self._match(file_part)
        table = self.tables[path]
        if column not in table:
            raise DataError(
                f"{path.name}: no column {column!r}; available: {sorted(table)}"
            )
        return Column(file=path, name=column, values=table[column])

    def length(self, file: Path) -> int:
        return max((len(v) for v in self.tables[file].values()), default=0)

    def ref(self, path: Path, column: str) -> str:
        """The ``file:column`` text that unambiguously names this column.

        A bare ``name:column`` resolves only while the basename is unique; when
        two open files share a basename, :meth:`_match` refuses it as ambiguous
        and demands the full path. Option lists must therefore be spelled the
        way the resolver accepts, or the picker offers a selection that always
        errors.
        """
        repeated = sum(1 for other in self.order if other.name == path.name) > 1
        return f"{path if repeated else path.name}:{column}"

    def files_with_column(self, name: str) -> list[Path]:
        """Every open file that has a column of this bare name, in open order.

        Used for file-independent columns like the group label, which may live
        in one file or several.
        """
        return [f for f in self.order if name in self.tables[f]]

    def _match(self, file_part: str) -> Path:
        by_name = [p for p in self.order if p.name == file_part]
        if len(by_name) == 1:
            return by_name[0]
        if len(by_name) > 1:
            raise DataError(
                f"ambiguous file {file_part!r}; matches {[str(p) for p in by_name]} "
                f"-- use the full path"
            )
        by_path = [p for p in self.order if str(p) == file_part]
        if by_path:
            return by_path[0]
        raise DataError(
            f"no open file {file_part!r}; open files are {[p.name for p in self.order]}"
        )


# How many parsed files to keep. A designer session realistically holds a
# handful of open CSVs, and a parsed table is the full file in memory -- so the
# bound keeps a long session from growing without limit, at the cost of one
# re-read for the least recently used file.
CACHE_LIMIT = 8

# (path, mtime_ns, size) -> Sources, in least-recently-used order.
_CACHE: "OrderedDict[tuple[Path, int, int], Sources]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    """Drop every cached parse. For tests, and for a deliberate reload."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _stamp(path: Path) -> tuple[int, int]:
    """The file identity a cache entry is keyed on.

    ``st_mtime_ns`` rather than seconds: a rewrite within the same second is
    exactly the case a size check alone would miss.
    """
    info = path.stat()
    return info.st_mtime_ns, info.st_size


def open_sources(paths: Sequence[Path]) -> Sources:
    """Read every named CSV in full and index it by column.

    Takes no ``na_values``: this only reads and splits, and the null vocabulary
    belongs to the numeric tests (:meth:`Sources.numeric_columns`) and to
    :mod:`parity_plot.data`. A parameter here that did nothing would read as
    though it did.

    Results are cached against ``(path, mtime_ns, size)``. The stat is one
    cheap round trip against the full read it saves, and a genuine rewrite
    changes mtime or size, so a stale entry cannot outlive an edit. The returned
    :class:`Sources` is shared between callers and must be treated as
    read-only -- every consumer in this package already is.
    """
    order = tuple(Path(p) for p in paths)
    cached = _lookup(order)
    if cached is not None:
        return cached

    tables: dict[Path, dict[str, list[str]]] = {}
    for path in order:
        rows = _read_rows(path)  # raises DataError for missing/unreadable
        if not rows:
            raise DataError(f"{path}: file is empty")
        header = list(rows[0][1].keys())
        table: dict[str, list[str]] = {col: [] for col in header}
        for _, row in rows:
            for col in header:
                table[col].append((row.get(col) or ""))
        tables[path] = table
        _store(path, table)
    return Sources(order=order, tables=tables)


def _lookup(order: tuple[Path, ...]) -> Sources | None:
    """Every file's cached parse, or None if any one of them is not current.

    All-or-nothing on purpose. A partial hit would have to be stitched together
    per file, and the only reason to miss is that a file changed or was never
    read -- in which case the misses are re-read and stored individually, so the
    *next* call hits every file.
    """
    if not order:
        return Sources(order=(), tables={})
    keys: list[tuple[Path, int, int]] = []
    for path in order:
        try:
            stamp = _stamp(path)
        except OSError:
            return None  # missing or unreadable: let the read raise and name it
        keys.append((path, *stamp))
    with _CACHE_LOCK:
        if any(key not in _CACHE for key in keys):
            return None
        tables = {key[0]: _CACHE[key].tables[key[0]] for key in keys}
        for key in keys:  # least-recently-used order
            _CACHE.move_to_end(key)
    return Sources(order=order, tables=tables)


def _store(path: Path, table: dict[str, list[str]]) -> None:
    """Record one file's parse, evicting the least recently used if full."""
    try:
        stamp = _stamp(path)
    except OSError:  # pragma: no cover -- the read just succeeded
        return
    key = (path, *stamp)
    part = Sources(order=(path,), tables={path: table})
    with _CACHE_LOCK:
        _CACHE[key] = part
        _CACHE.move_to_end(key)
        while len(_CACHE) > CACHE_LIMIT:
            _CACHE.popitem(last=False)


def _is_numeric(values: list[str], na: frozenset[str]) -> bool:
    """Whether a column is numeric, in the strict sense plot data must be.

    Requires at least one real number (an all-blank column proves nothing) and
    rejects infinities: ``float("inf")`` parses, so a lax check would offer a
    colour column that then fails to load, or an axis that fails at plot time.
    """
    seen_number = False
    for raw in values:
        text = raw.strip()
        if text.lower() in na:
            continue
        try:
            number = float(text)
        except ValueError:
            return False
        if not math.isfinite(number):
            return False
        seen_number = True
    return seen_number
