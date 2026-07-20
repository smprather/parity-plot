# parity_plot/designer/datasets.py
"""Looking at a CSV well enough to map its columns, without loading it.

Choosing which column is which needs the header and a sense of what is numeric.
Reading the whole file to learn that would make opening a large dataset feel
broken, so this reads the header and one data row and stops.
"""

from __future__ import annotations

import csv
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