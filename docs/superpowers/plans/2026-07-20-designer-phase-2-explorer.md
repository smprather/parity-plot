# Designer Phase 2 (Explorer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load any CSV from the designer and map its columns, and click a point to see the record behind it.

**Architecture:** Two new pure modules (`datasets.py` for header inspection, `records.py` for per-record views) plus a data-source swap on `DesignerState`. The UI panels stay thin, as in Phase 1. `records.py` is deliberately shaped to serve Phase 3's table as well as this phase's inspector.

**Tech Stack:** Python ≥3.11, NiceGUI 3.14, Plotly 6.9, pytest 9.

## Global Constraints

- **Python floor `>=3.11`.** Do not change it.
- **Never reimplement plotting, statistics, or tolerance geometry.** Call `build_figure`, `stats.compute`, `Tolerance`.
- **All config edits go through `ParityConfig.merge`.** Never construct `PlotConfig(...)`/`DataConfig(...)` directly from widget values.
- **An invalid input never blanks the plot**, and now also **never loses the loaded dataset**. A failed load keeps the previous data and reports the error.
- **`ParityConfig` and its sections are frozen dataclasses.** Never `object.__setattr__` on one — that bug already cost this repo seven broken tests. Use `dataclasses.replace` or `.merge`.
- **No numpy or pandas.** Standard library only.
- **nicegui is an optional extra.** Import it inside functions, never at module scope in anything reachable from `import parity_plot`.
- **Pure modules must not import nicegui.** `datasets.py`, `records.py`, `state.py` stay browser-free and unit-tested.
- Run tests with `.venv/bin/python -m pytest`. **Baseline is 243 passing.**

---

### Task 1: `datasets.py` — inspect a CSV without loading it

**Files:**
- Create: `parity_plot/designer/datasets.py`
- Test: `tests/designer/test_datasets.py`

**Interfaces:**
- Produces:
  - `Peek(columns: list[str], sample: dict[str, str], numeric: set[str])`
  - `peek(path: str | Path) -> Peek`
  - `suggest_mapping(peek: Peek) -> dict[str, str | None]` → keys `"key"`, `"x"`, `"y"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_datasets.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.designer.datasets import Peek, peek, suggest_mapping


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_peek_reads_headers_and_one_sample_row(tmp_path):
    path = write(tmp_path, "a.csv", "id,reference,measured\nA1,10.0,11.0\nA2,20.0,21.0\n")

    result = peek(path)

    assert result.columns == ["id", "reference", "measured"]
    assert result.sample == {"id": "A1", "reference": "10.0", "measured": "11.0"}


def test_peek_identifies_numeric_columns(tmp_path):
    path = write(tmp_path, "a.csv", "id,reference,measured\nA1,10.0,11.0\n")
    assert peek(path).numeric == {"reference", "measured"}


def test_peek_does_not_read_the_whole_file(tmp_path):
    """A large file must not be pulled into memory just to list its columns."""
    rows = "\n".join(f"A{i},{i}.0,{i}.5" for i in range(200_000))
    path = write(tmp_path, "big.csv", f"id,reference,measured\n{rows}\n")

    result = peek(path)

    assert result.columns == ["id", "reference", "measured"]
    assert result.sample["id"] == "A0"


def test_peek_handles_a_header_only_file(tmp_path):
    path = write(tmp_path, "empty.csv", "id,reference,measured\n")
    result = peek(path)
    assert result.columns == ["id", "reference", "measured"]
    assert result.sample == {}
    assert result.numeric == set()


def test_peek_reports_a_missing_file_by_name(tmp_path):
    from parity_plot.data import DataError

    with pytest.raises(DataError, match="not found"):
        peek(tmp_path / "nope.csv")


def test_peek_reports_an_empty_file(tmp_path):
    from parity_plot.data import DataError

    path = write(tmp_path, "empty.csv", "")
    with pytest.raises(DataError, match="empty"):
        peek(path)


@pytest.mark.parametrize(
    "columns, expected",
    [
        (["id", "reference", "measured"], {"key": "id", "x": "reference", "y": "measured"}),
        (["name", "expected", "actual"], {"key": "name", "x": "expected", "y": "actual"}),
        (["part", "golden", "dut"], {"key": "part", "x": "golden", "y": "dut"}),
        (["serial", "ref", "meas"], {"key": "serial", "x": "ref", "y": "meas"}),
    ],
)
def test_suggest_mapping_recognises_common_names(columns, expected):
    sample = {c: ("A1" if i == 0 else "1.0") for i, c in enumerate(columns)}
    numeric = {c for c in columns[1:]}
    assert suggest_mapping(Peek(columns, sample, numeric)) == expected


def test_suggest_mapping_falls_back_to_the_first_numeric_columns():
    """Unrecognised names still need a usable starting guess."""
    peeked = Peek(
        columns=["tag", "alpha", "beta"],
        sample={"tag": "T1", "alpha": "1.0", "beta": "2.0"},
        numeric={"alpha", "beta"},
    )
    assert suggest_mapping(peeked) == {"key": "tag", "x": "alpha", "y": "beta"}


def test_suggest_mapping_leaves_gaps_when_there_is_nothing_to_guess():
    peeked = Peek(columns=["only"], sample={"only": "x"}, numeric=set())
    assert suggest_mapping(peeked) == {"key": "only", "x": None, "y": None}


def test_suggest_mapping_never_reuses_one_column_twice():
    peeked = Peek(columns=["value"], sample={"value": "1.0"}, numeric={"value"})
    guess = suggest_mapping(peeked)
    chosen = [v for v in guess.values() if v is not None]
    assert len(chosen) == len(set(chosen))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_datasets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.datasets'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_datasets.py -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/datasets.py tests/designer/test_datasets.py
git commit -m "feat(designer): peek at a CSV's columns without loading it"
```

---

### Task 2: `records.py` — one row per record

**Files:**
- Create: `parity_plot/designer/records.py`
- Test: `tests/designer/test_records.py`

**Interfaces:**
- Consumes: `parity_plot.data.ParityData`, `parity_plot.tolerance.Tolerance`
- Produces:
  - `RecordView(key, x, y, error, rel_error, status, within)`
  - `record_views(data: ParityData, tol: Tolerance | None = None) -> list[RecordView]`
  - `find_record(views: list[RecordView], key: str) -> RecordView | None`
  - `key_from_customdata(customdata) -> str | None`

Phase 3's table is built on this too — keep it general, not inspector-specific.

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_records.py
from __future__ import annotations

import pytest

from parity_plot.data import from_sequences
from parity_plot.designer.records import (
    RecordView,
    find_record,
    key_from_customdata,
    record_views,
)
from parity_plot.tolerance import Tolerance


@pytest.fixture
def data():
    return from_sequences(
        x=[10.0, 20.0, None, 40.0],
        y=[11.0, None, 33.0, 40.5],
        keys=["a", "b", "c", "d"],
    )


def test_one_view_per_record_including_unpaired(data):
    views = record_views(data)
    assert [v.key for v in views] == ["a", "d", "b", "c"]


def test_paired_records_carry_both_values_and_the_error(data):
    view = find_record(record_views(data), "a")
    assert (view.x, view.y) == (10.0, 11.0)
    assert view.error == pytest.approx(1.0)
    assert view.rel_error == pytest.approx(0.1)
    assert view.status == "paired"


def test_unpaired_records_have_no_error_to_report(data):
    missing_y = find_record(record_views(data), "b")
    assert missing_y.x == 20.0
    assert missing_y.y is None
    assert missing_y.error is None
    assert missing_y.rel_error is None
    assert missing_y.status == "missing y"
    assert missing_y.within is None

    missing_x = find_record(record_views(data), "c")
    assert missing_x.x is None
    assert missing_x.y == 33.0
    assert missing_x.status == "missing x"


def test_tolerance_marks_records_in_and_out(data):
    views = record_views(data, Tolerance(reltol=0.05))  # +/-5%

    assert find_record(views, "a").within is False  # 10% off
    assert find_record(views, "d").within is True  # 1.25% off


def test_without_a_tolerance_nothing_is_judged(data):
    for view in record_views(data):
        assert view.within is None


def test_relative_error_is_undefined_at_zero():
    """Dividing by a zero reference would be a division by zero, not a 0% error."""
    data = from_sequences(x=[0.0], y=[1.0], keys=["z"])
    view = record_views(data)[0]
    assert view.error == pytest.approx(1.0)
    assert view.rel_error is None


def test_find_record_returns_none_for_an_unknown_key(data):
    assert find_record(record_views(data), "nope") is None


@pytest.mark.parametrize(
    "customdata, expected",
    [
        (["a1", 0.5], "a1"),          # paired trace: (key, diff)
        (("a1", 0.5), "a1"),
        ("a1", "a1"),                  # rug trace: bare key
        ([], None),
        (None, None),
    ],
)
def test_key_from_customdata_handles_both_trace_shapes(customdata, expected):
    """The paired trace carries (key, diff); the rug traces carry a bare key."""
    assert key_from_customdata(customdata) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_records.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.records'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/records.py
"""A flat, per-record view of a dataset.

The plot shows records as marks; this is the same records as rows. The inspector
uses one of these, and Phase 3's table uses all of them, so nothing here is
inspector-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..data import ParityData
from ..tolerance import Tolerance

PAIRED = "paired"
MISSING_X = "missing x"
MISSING_Y = "missing y"


@dataclass(frozen=True)
class RecordView:
    key: str
    x: float | None
    y: float | None
    error: float | None       # y - x, undefined unless both are present
    rel_error: float | None   # error / x, undefined at x = 0
    status: str
    within: bool | None       # None when unpaired or no tolerance was given


def record_views(data: ParityData, tol: Tolerance | None = None) -> list[RecordView]:
    """Every record: paired first, then those missing y, then missing x."""
    views: list[RecordView] = []

    for key, x, y in zip(data.keys, data.x, data.y):
        error = y - x
        views.append(
            RecordView(
                key=key,
                x=x,
                y=y,
                error=error,
                rel_error=(error / x) if x else None,
                status=PAIRED,
                within=tol.contains(x, y) if tol else None,
            )
        )

    for key, value in zip(data.missing_y.keys, data.missing_y.values):
        views.append(RecordView(key, value, None, None, None, MISSING_Y, None))

    for key, value in zip(data.missing_x.keys, data.missing_x.values):
        views.append(RecordView(key, None, value, None, None, MISSING_X, None))

    return views


def find_record(views: Sequence[RecordView], key: str) -> RecordView | None:
    return next((v for v in views if v.key == key), None)


def key_from_customdata(customdata: Any) -> str | None:
    """Pull a record key out of a Plotly click payload.

    The paired trace carries ``(key, diff)`` while the rug traces carry a bare
    key, so a click handler sees both shapes and must not assume either.
    """
    if customdata is None:
        return None
    if isinstance(customdata, str):
        return customdata
    if isinstance(customdata, (list, tuple)):
        return str(customdata[0]) if customdata else None
    return str(customdata)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_records.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/records.py tests/designer/test_records.py
git commit -m "feat(designer): per-record views for inspection and tables"
```

---

### Task 3: Swapping the dataset on `DesignerState`

Phase 1 fixed the dataset for the session. This makes it changeable while keeping the old one when a load fails, mirroring the last-good-figure rule.

**Files:**
- Modify: `parity_plot/designer/state.py` (add two methods; change nothing existing)
- Test: `tests/designer/test_state_data.py`

**Interfaces:**
- Consumes: `record_views`, `find_record` (Task 2)
- Produces:
  - `DesignerState.set_data_source(**values) -> bool` — `values` are `DataConfig` fields
  - `DesignerState.selected_record(tol: Tolerance | None = None) -> RecordView | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_state_data.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import from_sequences, load
from parity_plot.designer.state import DesignerState
from parity_plot.tolerance import Tolerance

WIDE = "id,reference,measured\nA1,10.0,11.0\nA2,20.0,21.0\nA3,30.0,\n"
OTHER = "name,golden,dut\nB1,5.0,5.5\nB2,6.0,6.6\n"


@pytest.fixture
def first(tmp_path: Path) -> Path:
    path = tmp_path / "first.csv"
    path.write_text(WIDE, encoding="utf-8")
    return path


@pytest.fixture
def second(tmp_path: Path) -> Path:
    path = tmp_path / "second.csv"
    path.write_text(OTHER, encoding="utf-8")
    return path


@pytest.fixture
def state(first) -> DesignerState:
    config = ParityConfig().merge(data={"paths": (first,)})
    return DesignerState(config=config, data=load(config.data))


def test_swapping_to_another_file_and_mapping(state, second):
    assert state.set_data_source(paths=(second,), key="name", x="golden", y="dut")

    assert state.data.n_paired == 2
    assert state.data.x_label == "golden"
    assert state.config.data.paths == (second,)
    assert state.last_error is None


def test_a_failed_load_keeps_the_dataset_that_was_working(state, tmp_path):
    """Losing the loaded data because of a typo in a column name would be a
    much worse outcome than the error message."""
    before = state.data

    assert not state.set_data_source(x="nope")

    assert state.data is before
    assert "nope" in state.last_error


def test_a_failed_load_also_leaves_the_config_alone(state):
    before = state.config
    state.set_data_source(x="nope")
    assert state.config == before


def test_a_missing_file_is_reported_not_raised(state, tmp_path):
    assert not state.set_data_source(paths=(tmp_path / "ghost.csv",))
    assert "not found" in state.last_error


def test_the_figure_follows_the_new_dataset(state, second):
    before = state.figure().to_dict()
    state.set_data_source(paths=(second,), key="name", x="golden", y="dut")
    assert state.figure().to_dict() != before


def test_selected_record_returns_the_pinned_record(state):
    state.selection = "A1"
    view = state.selected_record()
    assert view.key == "A1"
    assert view.x == 10.0 and view.y == 11.0


def test_selected_record_judges_against_the_given_tolerance(state):
    state.selection = "A1"  # 10% off
    assert state.selected_record(Tolerance(reltol=0.05)).within is False
    assert state.selected_record(Tolerance(reltol=0.20)).within is True


def test_selected_record_is_none_when_nothing_is_pinned(state):
    assert state.selection is None
    assert state.selected_record() is None


def test_selected_record_is_none_when_the_key_is_gone(state, second):
    """Loading a different file must not leave a dangling selection."""
    state.selection = "A1"
    state.set_data_source(paths=(second,), key="name", x="golden", y="dut")
    assert state.selected_record() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_state_data.py -v`
Expected: FAIL — `AttributeError: 'DesignerState' object has no attribute 'set_data_source'`

- [ ] **Step 3: Add the two methods to `parity_plot/designer/state.py`**

Add these imports at the top, beside the existing ones:

```python
from ..data import ParityData, load
from ..tolerance import Tolerance
from .records import RecordView, find_record, record_views
```

(The existing `from ..data import ParityData` line becomes the one above.)

Add these two methods to `DesignerState`, after `update`:

```python
    def set_data_source(self, **values: Any) -> bool:
        """Point at a different file or column mapping. Returns whether it worked.

        On failure the previously loaded dataset and the config are both left
        untouched: losing a working dataset because of a typo in a column name
        would be far worse than the error message.
        """
        try:
            candidate = self.config.merge(data=values)
            data = load(candidate.data)
        except (ConfigError, DataError, ValueError) as exc:
            self.last_error = str(exc)
            return False

        self.config = candidate
        self.data = data
        self.last_error = None
        if self.selection is not None and find_record(record_views(data), self.selection) is None:
            # The pinned record does not exist in the new dataset.
            self.selection = None
        return True

    def selected_record(self, tol: Tolerance | None = None) -> RecordView | None:
        """The pinned record, judged against ``tol`` if one is given."""
        if self.selection is None:
            return None
        return find_record(record_views(self.data, tol), self.selection)
```

Add `DataError` to the config/data imports at the top:

```python
from ..data import DataError, ParityData, load
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_state_data.py -v`
Expected: PASS, 9 tests

Then confirm nothing regressed: `.venv/bin/python -m pytest -q` → all previous tests still pass.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/state.py tests/designer/test_state_data.py
git commit -m "feat(designer): swap datasets without losing the working one"
```

---

### Task 4: Data panel — choose a file and map its columns

**Files:**
- Create: `parity_plot/designer/panels/data_panel.py`
- Test: `tests/designer/test_data_panel.py`

**Interfaces:**
- Consumes: `peek`, `suggest_mapping` (Task 1), `DesignerState.set_data_source` (Task 3)
- Produces:
  - `data_panel.mapping_options(paths: tuple[Path, ...]) -> dict[str, list[str]]`
  - `data_panel.build_data_panel(state: DesignerState, on_change: Callable[[], None]) -> None`

`mapping_options` is pure and tested without a browser; `build_data_panel` is the only part touching NiceGUI.

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_data_panel.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.designer.panels.data_panel import mapping_options

WIDE = "id,reference,measured\nA1,10.0,11.0\n"
JOIN_X = "id,value\nA1,10.0\n"
JOIN_Y = "id,value\nA1,11.0\n"


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_one_file_offers_its_own_columns(tmp_path):
    path = write(tmp_path, "wide.csv", WIDE)
    options = mapping_options((path,))
    assert options["key"] == ["id", "reference", "measured"]
    assert options["x"] == ["id", "reference", "measured"]


def test_two_files_offer_only_columns_common_to_both(tmp_path):
    """In join mode the key must exist in both files or the join cannot run."""
    x = write(tmp_path, "x.csv", JOIN_X)
    y = write(tmp_path, "y.csv", JOIN_Y)
    assert mapping_options((x, y))["key"] == ["id", "value"]


def test_two_files_with_nothing_in_common_offer_no_key(tmp_path):
    x = write(tmp_path, "x.csv", "a,b\n1,2\n")
    y = write(tmp_path, "y.csv", "c,d\n3,4\n")
    assert mapping_options((x, y))["key"] == []


def test_no_paths_offers_nothing(tmp_path):
    assert mapping_options(()) == {"key": [], "x": [], "y": []}


def test_an_unreadable_file_yields_empty_options_rather_than_raising(tmp_path):
    """The panel must still render so the user can pick a different file."""
    assert mapping_options((tmp_path / "ghost.csv",)) == {"key": [], "x": [], "y": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_data_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.panels.data_panel'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/panels/data_panel.py
"""Choosing the dataset and saying which column is which."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ...data import DataError
from ..datasets import peek, suggest_mapping
from ..state import DesignerState


def mapping_options(paths: tuple[Path, ...]) -> dict[str, list[str]]:
    """Column choices for each role, given the currently selected files.

    With two files the key must be present in both, or the join cannot run, so
    only their common columns are offered. An unreadable file yields no options
    rather than an exception -- the panel still has to render so the user can
    pick a different one.
    """
    empty = {"key": [], "x": [], "y": []}
    if not paths:
        return empty

    try:
        peeks = [peek(p) for p in paths]
    except DataError:
        return empty

    if len(peeks) == 1:
        columns = list(peeks[0].columns)
        return {"key": columns, "x": list(columns), "y": list(columns)}

    common = [c for c in peeks[0].columns if all(c in p.columns for p in peeks[1:])]
    return {
        "key": common,
        "x": list(peeks[0].columns),
        "y": list(peeks[1].columns),
    }


def build_data_panel(state: DesignerState, on_change: Callable[[], None]) -> None:
    """File paths plus the column mapping, applied together."""
    from nicegui import ui

    with ui.expansion("Data", value=False).classes("w-full"):
        paths_input = ui.input(
            "Paths",
            value=", ".join(str(p) for p in state.config.data.paths),
        ).classes("w-full").tooltip(
            "One path for a wide file, or two to outer-join on the key column."
        )

        options = mapping_options(state.config.data.paths)
        key_select = ui.select(options["key"], value=state.config.data.key, label="Key column").classes("w-full")
        x_select = ui.select(options["x"], value=state.config.data.x, label="Reference column").classes("w-full")
        y_select = ui.select(options["y"], value=state.config.data.y, label="Measured column").classes("w-full")

        def parse_paths() -> tuple[Path, ...]:
            return tuple(
                Path(part.strip()) for part in paths_input.value.split(",") if part.strip()
            )

        def refresh_options() -> None:
            """Re-read the headers so the selects match the chosen files.

            Guessing a mapping means the plot appears immediately instead of
            waiting behind an empty form the user must fill in first.
            """
            paths = parse_paths()
            opts = mapping_options(paths)
            key_select.options, x_select.options, y_select.options = (
                opts["key"], opts["x"], opts["y"],
            )
            if paths:
                try:
                    guess = suggest_mapping(peek(paths[0]))
                except DataError:
                    guess = {}
                key_select.value = guess.get("key") or key_select.value
                x_select.value = guess.get("x") or x_select.value
                y_select.value = guess.get("y") or y_select.value
            for select in (key_select, x_select, y_select):
                select.update()

        def apply() -> None:
            ok = state.set_data_source(
                paths=parse_paths(),
                key=key_select.value,
                x=x_select.value,
                y=y_select.value,
            )
            if not ok:
                ui.notify(state.last_error, type="negative")
            on_change()

        with ui.row():
            ui.button("Re-read columns", on_click=refresh_options).props("flat")
            ui.button("Load", on_click=apply)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_data_panel.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/panels/data_panel.py tests/designer/test_data_panel.py
git commit -m "feat(designer): data panel for file choice and column mapping"
```

---

### Task 5: Inspector — click a point, see the record

**Files:**
- Create: `parity_plot/designer/panels/inspector.py`
- Modify: `parity_plot/designer/app.py` (wire the click handler and mount both new panels)
- Test: `tests/designer/test_inspector.py`

**Interfaces:**
- Consumes: `RecordView`, `key_from_customdata` (Task 2), `DesignerState.selected_record` (Task 3), `build_data_panel` (Task 4)
- Produces:
  - `inspector.describe(view: RecordView | None) -> list[tuple[str, str]]`
  - `inspector.build_inspector(state: DesignerState, tol_getter: Callable[[], Tolerance | None]) -> Callable[[], None]` (returns a refresh function)

`describe` is pure and holds the formatting logic, so it is tested without a browser.

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_inspector.py
from __future__ import annotations

import pytest

from parity_plot.designer.inspector_helpers import describe  # see note below
from parity_plot.designer.records import RecordView


def labelled(view):
    return dict(describe(view))


def test_nothing_selected_says_so():
    assert describe(None) == [("", "Click a point to inspect it")]


def test_a_paired_record_shows_both_values_and_the_error():
    view = RecordView("A1", 10.0, 11.0, 1.0, 0.1, "paired", None)
    fields = labelled(view)
    assert fields["Record"] == "A1"
    assert fields["Reference"] == "10"
    assert fields["Measured"] == "11"
    assert fields["Error"] == "+1"
    assert fields["Relative error"] == "+10%"


def test_an_unpaired_record_says_what_is_missing():
    view = RecordView("A2", 20.0, None, None, None, "missing y", None)
    fields = labelled(view)
    assert fields["Measured"] == "missing"
    assert fields["Error"] == "n/a"
    assert "missing y" in fields["Status"]


def test_tolerance_verdict_appears_only_when_judged():
    inside = RecordView("A1", 10.0, 10.2, 0.2, 0.02, "paired", True)
    outside = RecordView("A1", 10.0, 15.0, 5.0, 0.5, "paired", False)
    unjudged = RecordView("A1", 10.0, 10.2, 0.2, 0.02, "paired", None)

    assert labelled(inside)["Tolerance"] == "within"
    assert labelled(outside)["Tolerance"] == "OUT"
    assert "Tolerance" not in labelled(unjudged)


def test_relative_error_is_omitted_when_undefined():
    view = RecordView("Z", 0.0, 1.0, 1.0, None, "paired", None)
    assert "Relative error" not in labelled(view)
```

**Note for the implementer:** put `describe` in a module the test can import
without nicegui. Create `parity_plot/designer/inspector_helpers.py` for it, and
have `panels/inspector.py` import `describe` from there. If you would rather put
`describe` directly in `panels/inspector.py`, that file must then not import
nicegui at module scope — pick one and make the test import match.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_inspector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/inspector_helpers.py
"""Formatting a record for display. Pure, so it can be tested without a browser."""

from __future__ import annotations

from .records import RecordView


def describe(view: RecordView | None) -> list[tuple[str, str]]:
    """Label/value pairs describing one record."""
    if view is None:
        return [("", "Click a point to inspect it")]

    fields = [
        ("Record", view.key),
        ("Reference", _num(view.x)),
        ("Measured", _num(view.y)),
        ("Error", _signed(view.error)),
    ]
    if view.rel_error is not None:
        fields.append(("Relative error", _signed(view.rel_error * 100, suffix="%")))
    fields.append(("Status", view.status))
    if view.within is not None:
        fields.append(("Tolerance", "within" if view.within else "OUT"))
    return fields


def _num(value: float | None) -> str:
    return "missing" if value is None else f"{value:,.6g}"


def _signed(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:+,.6g}{suffix}"
```

```python
# parity_plot/designer/panels/inspector.py
"""The detail view for whichever point was clicked."""

from __future__ import annotations

from typing import Callable

from ...tolerance import Tolerance
from ..inspector_helpers import describe
from ..state import DesignerState


def build_inspector(
    state: DesignerState, tol_getter: Callable[[], Tolerance | None]
) -> Callable[[], None]:
    """Render the panel and return a function that refreshes it.

    The tolerance is fetched through a callable rather than passed by value,
    because the user can change it after this panel is built and the verdict
    must follow.
    """
    from nicegui import ui

    with ui.card().classes("w-full"):
        ui.label("Inspector").classes("text-base font-medium")
        body = ui.column().classes("w-full gap-1")

    def refresh() -> None:
        body.clear()
        with body:
            for label, value in describe(state.selected_record(tol_getter())):
                with ui.row().classes("w-full justify-between gap-4"):
                    if label:
                        ui.label(label).classes("opacity-70")
                    ui.label(value).classes("font-mono")

    refresh()
    return refresh
```

Then wire it into `parity_plot/designer/app.py`. Inside `page()`:

Add these imports at the top of `app.py`, beside the existing ones:

```python
from ..tolerance import Tolerance
from .panels.data_panel import build_data_panel
from .panels.inspector import build_inspector
from .records import key_from_customdata
```

In the left-hand column, mount the data panel above the settings:

```python
            with ui.column().classes("w-80 shrink-0"):
                build_data_panel(state, lambda: reload_everything())
                ui.label("Settings").classes("text-base font-medium")
                build_controls(state, lambda: refresh())
```

In the right-hand column, below the plot, mount the inspector and attach the
click handler:

```python
            with ui.column().classes("grow"):
                plot_view = ui.plotly(state.figure()).classes("w-full h-[70vh]")
                error_banner = ui.label("").classes("text-red-400 text-sm")
                refresh_inspector = build_inspector(
                    state,
                    lambda: Tolerance(
                        abstol=state.config.plot.abstol,
                        reltol=state.config.plot.reltol,
                    ),
                )

                def on_point_click(event) -> None:
                    points = (event.args or {}).get("points") or []
                    if not points:
                        return
                    state.selection = key_from_customdata(points[0].get("customdata"))
                    refresh_inspector()

                plot_view.on("plotly_click", on_point_click)
```

And extend `refresh` so the inspector follows, plus add `reload_everything`:

```python
        def refresh() -> None:
            plot_view.update_figure(state.figure())
            error_banner.text = state.last_error or ""
            status.text = "unsaved changes" if session.is_dirty(state.config) else "saved"
            refresh_inspector()

        def reload_everything() -> None:
            """After a dataset swap the whole view is stale, selection included."""
            refresh()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_inspector.py -v`
Expected: PASS, 5 tests

Then the whole suite: `.venv/bin/python -m pytest -q` — everything green.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/inspector_helpers.py parity_plot/designer/panels/inspector.py parity_plot/designer/app.py tests/designer/test_inspector.py
git commit -m "feat(designer): click a point to inspect its record"
```

---

### Task 6: Integration checks and docs

**Files:**
- Test: `tests/designer/test_phase2_integration.py`
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_phase2_integration.py
"""Phase 2 end to end: load a different file, map it, click a point."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.datasets import peek, suggest_mapping
from parity_plot.designer.records import key_from_customdata
from parity_plot.designer.state import DesignerState
from parity_plot.tolerance import Tolerance

FIRST = "id,reference,measured\nA1,10.0,11.0\nA2,20.0,21.0\n"
SECOND = "part,golden,dut\nB1,5.0,5.5\nB2,6.0,9.0\nB3,7.0,\n"


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    first = tmp_path / "first.csv"
    first.write_text(FIRST, encoding="utf-8")
    config = ParityConfig().merge(data={"paths": (first,)})
    return DesignerState(config=config, data=load(config.data))


def test_open_a_new_file_using_the_suggested_mapping(state, tmp_path: Path):
    second = tmp_path / "second.csv"
    second.write_text(SECOND, encoding="utf-8")

    guess = suggest_mapping(peek(second))
    assert guess == {"key": "part", "x": "golden", "y": "dut"}

    assert state.set_data_source(paths=(second,), **guess), state.last_error
    assert state.data.n_paired == 2
    assert len(state.data.missing_y) == 1


def test_clicking_a_point_then_reading_its_record(state, tmp_path: Path):
    second = tmp_path / "second.csv"
    second.write_text(SECOND, encoding="utf-8")
    state.set_data_source(paths=(second,), **suggest_mapping(peek(second)))

    # What a Plotly click on the paired trace delivers.
    state.selection = key_from_customdata(["B2", 3.0])
    view = state.selected_record(Tolerance(reltol=0.1))

    assert view.key == "B2"
    assert view.error == pytest.approx(3.0)
    assert view.within is False  # 50% off a 10% tolerance


def test_the_figure_and_the_inspector_agree_about_the_data(state, tmp_path: Path):
    """Both read the same ParityData, so a swap cannot leave them disagreeing."""
    second = tmp_path / "second.csv"
    second.write_text(SECOND, encoding="utf-8")
    state.set_data_source(paths=(second,), **suggest_mapping(peek(second)))

    figure = state.figure()
    paired = next(t for t in figure.data if t.name and t.name.startswith("paired"))

    state.selection = "B1"
    assert state.selected_record().x in list(paired.x)


def test_a_bad_mapping_leaves_everything_as_it_was(state, tmp_path: Path):
    before_data = state.data
    before_figure = state.figure().to_dict()

    assert not state.set_data_source(x="not_a_column")

    assert state.data is before_data
    assert state.figure().to_dict() == before_figure
    assert "not_a_column" in state.last_error
```

- [ ] **Step 2: Run to verify, then run the whole suite**

Run: `.venv/bin/python -m pytest tests/designer/test_phase2_integration.py -v` → 4 passed
Run: `.venv/bin/python -m pytest -q` → everything green

- [ ] **Step 3: Verify the server still starts**

```bash
.venv/bin/parity-plot design data/example.csv --port 8098 --no-open-browser &
sleep 4 && curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8098/
```
Expected: `200`. Kill the server afterwards.

- [ ] **Step 4: Update the docs**

Add to the README's "Interactive designer" section:

```markdown
The **Data** panel opens any CSV and maps its columns: give one path for a wide
file or two to outer-join, and the designer reads just the header to offer the
column choices, guessing the mapping from common names (`reference`/`measured`,
`expected`/`actual`, `golden`/`dut`). A mapping that fails to load leaves the
previous dataset in place rather than emptying the plot.

Click any point — including a rug tick — to inspect that record in the
**Inspector**: both values, the signed and relative error, and whether it passes
the tolerance currently set.
```

Add to `CLAUDE.md` beside the other designer notes:

```markdown
**Phase 2 pure modules:** `datasets.py` reads only a CSV's header and first row,
because loading a large file just to list its columns makes opening one feel
broken. `records.py` turns a `ParityData` into one row per record and is shared
by the inspector and (Phase 3) the table — keep it general.

`DesignerState.set_data_source` keeps the previously loaded dataset when a load
fails, for the same reason `figure()` keeps the last good figure: losing working
data to a typo is worse than the error message. It also clears a selection that
does not exist in the new dataset.

Plotly click payloads carry `customdata`, but not in one shape: the paired trace
carries `(key, diff)` while the rug traces carry a bare key. `key_from_customdata`
normalises both — do not index into it directly.
```

- [ ] **Step 5: Commit**

```bash
git add tests/designer/test_phase2_integration.py README.md CLAUDE.md
git commit -m "test(designer): phase 2 integration, plus docs"
```

---

## Self-Review

**Spec coverage.** The spec's Phase 2 asks for: file loading and column mapping (Tasks 1, 4), header reading that does not load the whole file (Task 1, asserted on a 200k-row file), point inspection with click-to-pin and a detail panel showing the record and its tolerance verdict (Tasks 2, 3, 5), and reuse of the existing `hovertemplate` and `customdata` rather than a parallel index (Task 2's `key_from_customdata`, Task 5's handler).

**Type consistency.** `RecordView`'s field order is identical in Task 2's definition, Task 5's test constructions, and the integration test. `set_data_source(**values) -> bool` matches its callers in Tasks 4 and 6. `describe(view) -> list[tuple[str, str]]` matches its use in `build_inspector`. `mapping_options(paths) -> dict[str, list[str]]` matches its use in `build_data_panel`.

**Deliberate deviation from the spec.** The spec placed `describe` in `panels/inspector.py`; this plan puts it in `inspector_helpers.py` so the tests can import it without nicegui. Task 5 states this explicitly and allows either arrangement provided the test import matches.
