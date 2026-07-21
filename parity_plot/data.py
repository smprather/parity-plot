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
    # Per-paired-point group label, or None when no group column was chosen.
    # Aligned to `keys`/`x`/`y`; an entry may be None if that point's group cell
    # was blank. Drives colour/symbol-by-group in Phase 2.
    group: list[str | None] | None = None

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
    """Load per the config: N files, ref/test as file:column, join or order.

    The two plotted series are ``ref`` and ``test``, each a ``file:column`` into
    the open set. A ``join`` column aligns rows across files by key; without one,
    rows pair by position and the longer column's tail is left unpaired. An
    optional ``group`` column labels each paired point.

    Both former modes are special cases: one file with two columns and no join is
    the old wide mode; two files with a join is the old pair mode. There is no
    dispatch on file count.
    """
    from .sources import open_sources  # lazy: sources imports helpers from here

    if not cfg.files:
        raise DataError("no input files; pass a CSV path or set data.files")
    if not cfg.ref or not cfg.test:
        raise DataError("both a ref and a test column are required (file:column)")

    src = open_sources(cfg.files, cfg.na_values)
    na = _na_set(cfg.na_values)

    ref_col = src.resolve(cfg.ref)
    test_col = src.resolve(cfg.test)
    _require_numeric(ref_col, na, "ref")
    _require_numeric(test_col, na, "test")
    group_col = src.resolve(cfg.group) if cfg.group else None

    builder = _Builder(x_label=ref_col.name, y_label=test_col.name)
    if cfg.join:
        _load_joined(builder, src, ref_col, test_col, group_col, cfg.join, na)
    else:
        _load_by_order(builder, ref_col, test_col, group_col, na)
    return builder.build()


def _require_numeric(col, na: frozenset[str], role: str) -> None:
    """ref and test are the axes -- every non-NA cell must be a number."""
    for index, raw in enumerate(col.values):
        text = (raw or "").strip()
        if text.lower() in na:
            continue
        try:
            float(text)
        except ValueError:
            raise DataError(
                f"{col.file}:{index + 2}: {role} column {col.name!r} has "
                f"non-numeric value {text!r}"
            ) from None


def _load_by_order(builder: "_Builder", ref_col, test_col, group_col, na) -> None:
    """Pair rows by position; the longer column's tail becomes unpaired."""
    n = max(len(ref_col.values), len(test_col.values))
    for i in range(n):
        rv = ref_col.values[i] if i < len(ref_col.values) else None
        tv = test_col.values[i] if i < len(test_col.values) else None
        gv = group_col.values[i] if group_col and i < len(group_col.values) else None
        builder.add(
            str(i),
            _parse(rv, na, ref_col.file, i + 2, ref_col.name) if rv is not None else None,
            _parse(tv, na, test_col.file, i + 2, test_col.name) if tv is not None else None,
            group=_group_value(gv, na),
        )


def _load_joined(builder: "_Builder", src, ref_col, test_col, group_col, join, na) -> None:
    """Outer-join ref and test files on ``join``; a key on one side is unpaired."""
    ref_by = _index_by_key(src, ref_col, join)
    test_by = _index_by_key(src, test_col, join)
    group_by = _index_by_key(src, group_col, join) if group_col else {}

    # ref-file order first, then keys only in the test file -- deterministic and
    # mirroring how the data was laid out.
    ordered = list(ref_by) + [k for k in test_by if k not in ref_by]
    for key in ordered:
        rline, rraw = ref_by.get(key, (0, None))
        tline, traw = test_by.get(key, (0, None))
        _, graw = group_by.get(key, (0, None))
        builder.add(
            key,
            _parse(rraw, na, ref_col.file, rline, ref_col.name) if rraw is not None else None,
            _parse(traw, na, test_col.file, tline, test_col.name) if traw is not None else None,
            group=_group_value(graw, na),
        )


def _index_by_key(src, col, join: str) -> dict[str, tuple[int, str]]:
    """{join-key: (line, raw value)} for one column, keyed on the join column.

    The key file must contain the join column, and its keys must be unique -- a
    duplicate would make the join ambiguous.
    """
    table = src.tables[col.file]
    if join not in table:
        raise DataError(
            f"{col.file}: join column {join!r} not found; available: {sorted(table)}"
        )
    keys = table[join]
    out: dict[str, tuple[int, str]] = {}
    for index, (key, value) in enumerate(zip(keys, col.values)):
        key = (key or "").strip()
        if key in out:
            raise DataError(
                f"{col.file}:{index + 2}: duplicate join key {key!r}; the join "
                f"would be ambiguous"
            )
        out[key] = (index + 2, value)
    return out


def _group_value(raw: str | None, na: frozenset[str]) -> str | None:
    """A group label, or None when the cell is blank/NA."""
    if raw is None:
        return None
    text = raw.strip()
    return None if text.lower() in na else text


def from_sequences(
    x: Iterable[float | None],
    y: Iterable[float | None],
    keys: Sequence[str] | None = None,
    group: Sequence[str | None] | None = None,
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
    groups = list(group) if group is not None else None
    if groups is not None and len(groups) != len(xs):
        raise DataError(f"group has length {len(groups)}, expected {len(xs)}")

    builder = _Builder(x_label=x_label, y_label=y_label)
    for i, (xv, yv) in enumerate(zip(xs, ys)):
        key = keys[i] if keys is not None else str(i)
        gv = groups[i] if groups is not None else None
        builder.add(str(key), _clean(xv), _clean(yv), group=gv)
    return builder.build()


class _Builder:
    """Accumulates records and sorts them into paired / unpaired / dropped."""

    def __init__(self, x_label: str, y_label: str) -> None:
        self.keys: list[str] = []
        self.x: list[float] = []
        self.y: list[float] = []
        self.groups: list[str | None] = []
        self.missing_y_keys: list[str] = []
        self.missing_y_vals: list[float] = []
        self.missing_x_keys: list[str] = []
        self.missing_x_vals: list[float] = []
        self.n_dropped = 0
        self.x_label = x_label
        self.y_label = y_label

    def add(
        self, key: str, xv: float | None, yv: float | None, group: str | None = None
    ) -> None:
        if xv is not None and yv is not None:
            self.keys.append(key)
            self.x.append(xv)
            self.y.append(yv)
            # Group is a property of a paired point only; unpaired records have
            # no place in the encoded scatter, so their group is not tracked.
            self.groups.append(group)
        elif xv is not None:
            self.missing_y_keys.append(key)
            self.missing_y_vals.append(xv)
        elif yv is not None:
            self.missing_x_keys.append(key)
            self.missing_x_vals.append(yv)
        else:
            self.n_dropped += 1

    def build(self) -> ParityData:
        # None unless a group column actually supplied a label somewhere.
        group = self.groups if any(g is not None for g in self.groups) else None
        return ParityData(
            keys=self.keys,
            x=self.x,
            y=self.y,
            missing_y=Unpaired(self.missing_y_keys, self.missing_y_vals),
            missing_x=Unpaired(self.missing_x_keys, self.missing_x_vals),
            n_dropped=self.n_dropped,
            x_label=self.x_label,
            y_label=self.y_label,
            group=group,
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
