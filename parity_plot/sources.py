# parity_plot/sources.py
"""Opening an arbitrary set of CSV files and resolving `file:column` references.

The plot compares two columns. In the general case they live in different files
with different layouts, so a source column is named `file:column` and resolved
against the open set. This module only reads and indexes; parsing to floats and
pairing stay in data.py.
"""

from __future__ import annotations

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
        return [f"{path.name}:{col}" for path in self.order for col in self.tables[path]]

    def numeric_columns(self, na_values: Sequence[str] = DEFAULT_NA_VALUES) -> list[str]:
        na = _na_set(na_values)
        out = []
        for path in self.order:
            for col, values in self.tables[path].items():
                if _is_numeric(values, na):
                    out.append(f"{path.name}:{col}")
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


def open_sources(
    paths: Sequence[Path], na_values: Sequence[str] = DEFAULT_NA_VALUES
) -> Sources:
    order = tuple(Path(p) for p in paths)
    tables: dict[Path, dict[str, list[str]]] = {}
    for path in order:
        rows = _read_rows(path)          # raises DataError for missing/unreadable
        if not rows:
            raise DataError(f"{path}: file is empty")
        header = list(rows[0][1].keys())
        table: dict[str, list[str]] = {col: [] for col in header}
        for _, row in rows:
            for col in header:
                table[col].append((row.get(col) or ""))
        tables[path] = table
    return Sources(order=order, tables=tables)


def _is_numeric(values: list[str], na: frozenset[str]) -> bool:
    seen_number = False
    for raw in values:
        text = raw.strip()
        if text.lower() in na:
            continue
        try:
            float(text)
        except ValueError:
            return False
        seen_number = True
    return seen_number