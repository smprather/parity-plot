# parity_plot/designer/datasets.py
"""Looking at a CSV well enough to map its columns, without loading it.

Choosing which column is which needs the header and a sense of what is numeric.
Reading the whole file to learn that would make opening a large dataset feel
broken, so this reads the header and one data row and stops.
"""

from __future__ import annotations

import csv
import itertools
from dataclasses import dataclass, field
from pathlib import Path

from ..data import DataError

# Names seen in the wild for each role, best guess first. Matched
# case-insensitively against the whole column name.
KEY_NAMES = ("id", "key", "name", "part", "serial", "label", "sample", "tag")
X_NAMES = ("reference", "ref", "expected", "golden", "truth", "nominal", "x")
Y_NAMES = ("measured", "meas", "actual", "observed", "predicted", "dut", "y")


@dataclass(frozen=True)
class Peek:
    """What one glance at a CSV tells us."""

    columns: list[str] = field(default_factory=list)
    sample: dict[str, str] = field(default_factory=dict)
    numeric: set[str] = field(default_factory=set)


def peek(path: str | Path) -> Peek:
    """Read the header and the first data row. Nothing more."""
    path = Path(path)
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise DataError(f"{path}: file is empty")
            columns = [name for name in reader.fieldnames]
            sample = next(reader, None)
    except FileNotFoundError:
        raise DataError(f"input file not found: {path}") from None
    except OSError as exc:
        raise DataError(f"could not read {path}: {exc}") from None

    if not columns:
        raise DataError(f"{path}: file is empty")

    row = {k: (v or "") for k, v in (sample or {}).items() if k is not None}
    return Peek(columns=columns, sample=row, numeric=_numeric_columns(row))


def _numeric_columns(row: dict[str, str]) -> set[str]:
    found = set()
    for name, value in row.items():
        text = (value or "").strip()
        if not text:
            continue
        try:
            float(text)
        except ValueError:
            continue
        found.add(name)
    return found


@dataclass(frozen=True)
class Preview:
    """The header and the first rows of a CSV, for a quick look.

    ``numeric`` names the columns whose every non-empty value in the previewed
    rows parses as a number, so a viewer can give them a numeric schema (and
    sort them by magnitude rather than lexically).
    """

    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    numeric: set[str] = field(default_factory=set)


def preview(path: str | Path, limit: int = 100) -> Preview:
    """Read the header and up to ``limit`` data rows -- never the whole file.

    A peek at the data before column mapping, so values stay raw strings.
    Bounded like :func:`peek` (``itertools.islice`` stops the reader early), so
    previewing a huge dataset is still instant.
    """
    path = Path(path)
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise DataError(f"{path}: file is empty")
            columns = [name for name in reader.fieldnames if name is not None]
            rows = [
                {k: (v or "") for k, v in row.items() if k is not None}
                for row in itertools.islice(reader, limit)
            ]
    except FileNotFoundError:
        raise DataError(f"input file not found: {path}") from None
    except OSError as exc:
        raise DataError(f"could not read {path}: {exc}") from None

    if not columns:
        raise DataError(f"{path}: file is empty")
    return Preview(columns=columns, rows=rows, numeric=_numeric_over(columns, rows))


def _numeric_over(columns: list[str], rows: list[dict[str, str]]) -> set[str]:
    """Columns whose every non-empty previewed value is a number.

    A column with no data in the previewed rows is left out -- there is nothing
    to prove it numeric.
    """
    numeric: set[str] = set()
    for column in columns:
        values = [(row.get(column) or "").strip() for row in rows]
        present = [v for v in values if v]
        if present and all(_is_number(v) for v in present):
            numeric.add(column)
    return numeric


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def suggest_mapping(peeked: Peek) -> dict[str, str | None]:
    """Guess which column plays which role.

    A guess that is merely plausible beats an empty form: the user can see the
    plot immediately and correct the mapping if it is wrong.
    """
    taken: set[str] = set()

    key = _match(peeked.columns, KEY_NAMES, taken)
    if key is None:
        non_numeric = [c for c in peeked.columns if c not in peeked.numeric]
        key = _first(non_numeric, taken) or _first(peeked.columns, taken)
    _take(taken, key)

    x = _match(peeked.columns, X_NAMES, taken)
    if x is None:
        x = _first([c for c in peeked.columns if c in peeked.numeric], taken)
    _take(taken, x)

    y = _match(peeked.columns, Y_NAMES, taken)
    if y is None:
        y = _first([c for c in peeked.columns if c in peeked.numeric], taken)
    _take(taken, y)

    return {"key": key, "x": x, "y": y}


def _match(columns: list[str], wanted: tuple[str, ...], taken: set[str]) -> str | None:
    lowered = {c.lower(): c for c in columns if c not in taken}
    for name in wanted:
        if name in lowered:
            return lowered[name]
    return None


def _first(columns: list[str], taken: set[str]) -> str | None:
    return next((c for c in columns if c not in taken), None)


def _take(taken: set[str], column: str | None) -> None:
    if column is not None:
        taken.add(column)
