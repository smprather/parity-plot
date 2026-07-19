"""CSV loading, outer joining, and null classification.

Everything downstream consumes a single :class:`ParityData` struct, so neither
input mode (wide file vs. two joined files) leaks past this module.

A record that exists in one dataset but not the other cannot be a point on the
plot -- it has only one coordinate. Rather than dropping it, such a record is
kept in ``missing_x`` or ``missing_y`` so the plot can show it as a rug mark on
the axis of the value that *is* known.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .config import DataConfig


class DataError(ValueError):
    """Raised for unreadable, malformed, or ambiguous input data."""


@dataclass(frozen=True)
class Unpaired:
    """Records with a value in one dataset and nothing in the other."""

    keys: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.values)


@dataclass(frozen=True)
class ParityData:
    keys: list[str] = field(default_factory=list)
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    missing_y: Unpaired = field(default_factory=Unpaired)
    missing_x: Unpaired = field(default_factory=Unpaired)
    n_dropped: int = 0
    x_label: str = "x"
    y_label: str = "y"

    @property
    def n_paired(self) -> int:
        return len(self.x)

    @property
    def n_unpaired(self) -> int:
        return len(self.missing_x) + len(self.missing_y)

    def all_values(self) -> list[float]:
        """Every finite value, paired or not -- the basis for the axis range.

        Unpaired values are included so a rug mark can never fall outside the
        plotted range.
        """
        return [*self.x, *self.y, *self.missing_y.values, *self.missing_x.values]


def load(cfg: DataConfig) -> ParityData:
    """Load according to ``cfg``, dispatching on how many paths were given."""
    paths = cfg.paths
    if not paths:
        raise DataError("no input paths configured; pass a CSV path or set data.paths")
    if len(paths) == 1:
        return load_wide(
            paths[0],
            x_col=cfg.x,
            y_col=cfg.y,
            key_col=cfg.key,
            na_values=cfg.na_values,
        )
    if len(paths) == 2:
        return load_pair(
            paths[0],
            paths[1],
            key_col=cfg.key,
            value_col=cfg.value,
            x_col=cfg.x,
            y_col=cfg.y,
            na_values=cfg.na_values,
        )
    raise DataError(
        f"expected 1 path (wide mode) or 2 paths (join mode), got {len(paths)}"
    )


def load_wide(
    path: str | Path,
    x_col: str,
    y_col: str,
    key_col: str | None = None,
    na_values: Sequence[str] = (),
) -> ParityData:
    """Load one CSV holding both value columns. An empty cell is a null."""
    path = Path(path)
    na = _na_set(na_values)
    rows = _read_rows(path)
    if not rows:
        raise DataError(f"{path}: file is empty")

    header = rows[0][1].keys()
    _require_columns(path, header, {x_col, y_col} | ({key_col} if key_col else set()))

    builder = _Builder(x_label=x_col, y_label=y_col)
    for line, row in rows:
        key = row[key_col].strip() if key_col else str(line - 1)
        builder.add(
            key,
            _parse(row.get(x_col), na, path, line, x_col),
            _parse(row.get(y_col), na, path, line, y_col),
        )
    return builder.build()


def load_pair(
    x_path: str | Path,
    y_path: str | Path,
    key_col: str | None = "id",
    value_col: str = "value",
    x_col: str | None = None,
    y_col: str | None = None,
    na_values: Sequence[str] = (),
) -> ParityData:
    """Outer-join two CSVs on ``key_col``.

    A key present in only one file is the null case -- there is genuinely no
    corresponding measurement, as opposed to a blank cell.
    """
    x_path, y_path = Path(x_path), Path(y_path)
    if not key_col:
        raise DataError("join mode needs a key column; set data.key or pass --key-col")
    na = _na_set(na_values)

    x_vals, x_label = _read_keyed(x_path, key_col, value_col, x_col, na)
    y_vals, y_label = _read_keyed(y_path, key_col, value_col, y_col, na)

    # x-file order first, then keys only present in the y file, so the output is
    # deterministic and mirrors how the user laid the data out.
    ordered = list(x_vals) + [k for k in y_vals if k not in x_vals]

    builder = _Builder(x_label=x_label, y_label=y_label)
    for key in ordered:
        builder.add(key, x_vals.get(key), y_vals.get(key))
    return builder.build()


def from_sequences(
    x: Iterable[float | None],
    y: Iterable[float | None],
    keys: Sequence[str] | None = None,
    x_label: str = "x",
    y_label: str = "y",
) -> ParityData:
    """Build from in-memory sequences, treating ``None``/NaN as null.

    This is the entry point for the Python API when the caller already has
    arrays in hand (lists, pandas Series, numpy arrays -- anything iterable).
    """
    xs, ys = list(x), list(y)
    if len(xs) != len(ys):
        raise DataError(f"x and y differ in length: {len(xs)} vs {len(ys)}")
    if keys is not None and len(keys) != len(xs):
        raise DataError(f"keys has length {len(keys)}, expected {len(xs)}")

    builder = _Builder(x_label=x_label, y_label=y_label)
    for i, (xv, yv) in enumerate(zip(xs, ys)):
        key = keys[i] if keys is not None else str(i)
        builder.add(str(key), _clean(xv), _clean(yv))
    return builder.build()


class _Builder:
    """Accumulates records and sorts them into paired / unpaired / dropped."""

    def __init__(self, x_label: str, y_label: str) -> None:
        self.keys: list[str] = []
        self.x: list[float] = []
        self.y: list[float] = []
        self.missing_y_keys: list[str] = []
        self.missing_y_vals: list[float] = []
        self.missing_x_keys: list[str] = []
        self.missing_x_vals: list[float] = []
        self.n_dropped = 0
        self.x_label = x_label
        self.y_label = y_label

    def add(self, key: str, xv: float | None, yv: float | None) -> None:
        if xv is not None and yv is not None:
            self.keys.append(key)
            self.x.append(xv)
            self.y.append(yv)
        elif xv is not None:
            self.missing_y_keys.append(key)
            self.missing_y_vals.append(xv)
        elif yv is not None:
            self.missing_x_keys.append(key)
            self.missing_x_vals.append(yv)
        else:
            self.n_dropped += 1

    def build(self) -> ParityData:
        return ParityData(
            keys=self.keys,
            x=self.x,
            y=self.y,
            missing_y=Unpaired(self.missing_y_keys, self.missing_y_vals),
            missing_x=Unpaired(self.missing_x_keys, self.missing_x_vals),
            n_dropped=self.n_dropped,
            x_label=self.x_label,
            y_label=self.y_label,
        )


def _read_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    """Return ``(line_number, row)`` pairs; line 1 is the header."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                return []
            return [(i, row) for i, row in enumerate(reader, start=2)]
    except FileNotFoundError:
        raise DataError(f"input file not found: {path}") from None
    except OSError as exc:
        raise DataError(f"could not read {path}: {exc}") from None


def _read_keyed(
    path: Path,
    key_col: str,
    value_col: str,
    axis_col: str | None,
    na: frozenset[str],
) -> tuple[dict[str, float | None], str]:
    """Read one side of a join into ``{key: value}``.

    The value column is ``value_col`` if the file has it, otherwise the
    axis-specific name -- so ``reference.csv`` may use either ``value`` or
    ``reference`` as its column header.
    """
    rows = _read_rows(path)
    if not rows:
        raise DataError(f"{path}: file is empty")

    header = set(rows[0][1].keys())
    _require_columns(path, header, {key_col})

    if value_col in header:
        column = value_col
    elif axis_col and axis_col in header:
        column = axis_col
    else:
        wanted = f"'{value_col}'" + (f" or '{axis_col}'" if axis_col else "")
        raise DataError(
            f"{path}: no value column {wanted}; available columns are "
            f"{sorted(header)}"
        )

    values: dict[str, float | None] = {}
    seen_at: dict[str, int] = {}
    for line, row in rows:
        key = (row.get(key_col) or "").strip()
        if key in seen_at:
            raise DataError(
                f"{path}:{line}: duplicate key {key!r} (first seen on line "
                f"{seen_at[key]}); the join would be ambiguous"
            )
        seen_at[key] = line
        values[key] = _parse(row.get(column), na, path, line, column)
    return values, column


def _require_columns(path: Path, header: Iterable[str], needed: Iterable[str]) -> None:
    available = set(header)
    missing = sorted(set(needed) - available)
    if missing:
        raise DataError(
            f"{path}: missing column(s) {missing}; available columns are "
            f"{sorted(available)}"
        )


def _na_set(na_values: Sequence[str]) -> frozenset[str]:
    return frozenset(v.strip().lower() for v in na_values)


def _parse(
    raw: str | None, na: frozenset[str], path: Path, line: int, column: str
) -> float | None:
    """Parse one cell to a float, or ``None`` if it is null.

    A value that is neither null nor numeric is an error rather than a silent
    null: quietly coercing it would corrupt every statistic downstream.
    """
    if raw is None:
        return None
    text = raw.strip()
    if text.lower() in na:
        return None
    try:
        value = float(text)
    except ValueError:
        raise DataError(
            f"{path}:{line}: column {column!r} has non-numeric value {text!r}"
        ) from None
    if math.isnan(value):
        return None
    if math.isinf(value):
        raise DataError(f"{path}:{line}: column {column!r} is infinite")
    return value


def _clean(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) else number
