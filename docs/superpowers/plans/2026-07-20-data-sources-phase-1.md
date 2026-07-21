# Data Sources Phase 1 (Multi-file Model) Implementation Plan

> **For agentic workers:** Implement one task only, as fenced in your prompt.

**Goal:** Replace `DataConfig.paths + x + y + key` with an N-file model where the two
plotted series are chosen as `file:column` refs, joined on a key or paired by row order,
with an optional group column. The current one-file and two-file modes become special
cases of the general path.

**Definition of done:** full suite green (zero xfailed, zero XPASS); `parity-plot plot
data/example.csv` with no flags still renders; a two-file join and a pair-by-order case both
render.

## Global Constraints

- **`ref` and `test` must be numeric columns** (they are the axes); resolving a non-numeric
  column for either raises `DataError`. `join` and `group` may be **any** column — string,
  integer, even float — and their values are compared/used as **raw strings** as they come
  from the CSV (so integer key `42` matches `42`; a float key compares textually).
- **Clean break from 0.2.0.** `paths`/`x`/`y`/`key`/`value` in a `[data]` table raise a
  `ConfigError` naming the new keys, like the tolerance rework did for `[plot]`.
- **Reuse `data.py`'s existing machinery** — `_read_rows`, `_parse`, `_na_set`,
  `_require_columns`, `_Builder`. Do not write a second CSV parser.
- **No numpy or pandas.** Frozen dataclasses; never `object.__setattr__`.
- Python 3.14 floor. Pure modules import neither nicegui nor plotly.
- Run tests with `.venv/bin/python -m pytest`. **Baseline is 491 passing.** This phase
  breaks many data-facing tests; Task 4 owns fixing them.

---

### Task 1: `sources.py` — open N files, resolve `file:column`

**Files:** create `parity_plot/sources.py`, `tests/test_sources.py`

**Interfaces produced:**
- `Column(file: Path, name: str, values: list[str])`
- `Sources(order: tuple[Path, ...], tables: dict[Path, dict[str, list[str]]])`
  - `.columns() -> list[str]` — `"file:column"` for every column, in file then header order
  - `.numeric_columns(na_values) -> list[str]` — only columns whose every non-NA cell parses as float
  - `.resolve(ref: str) -> Column` — `"file:column"` → the Column
  - `.length(file: Path) -> int`
- `open_sources(paths, na_values=DEFAULT_NA_VALUES) -> Sources`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sources.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import DEFAULT_NA_VALUES
from parity_plot.data import DataError
from parity_plot.sources import Sources, open_sources


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_opens_a_file_and_lists_qualified_columns(tmp_path):
    f = write(tmp_path, "meas.csv", "id,voltage,batch\nA1,10.0,x\nA2,20.0,y\n")
    src = open_sources((f,))
    assert src.columns() == ["meas.csv:id", "meas.csv:voltage", "meas.csv:batch"]


def test_resolve_returns_the_column_values(tmp_path):
    f = write(tmp_path, "meas.csv", "id,voltage\nA1,10.0\nA2,20.0\n")
    col = open_sources((f,)).resolve("meas.csv:voltage")
    assert col.name == "voltage"
    assert col.values == ["10.0", "20.0"]


def test_numeric_columns_excludes_text(tmp_path):
    f = write(tmp_path, "d.csv", "id,voltage,label\nA1,10.0,hi\nA2,20.0,lo\n")
    src = open_sources((f,))
    # id is text (A1/A2), label is text; only voltage is numeric.
    assert src.numeric_columns(DEFAULT_NA_VALUES) == ["d.csv:voltage"]


def test_a_column_of_integers_counts_as_numeric(tmp_path):
    f = write(tmp_path, "d.csv", "n\n1\n2\n3\n")
    assert open_sources((f,)).numeric_columns(DEFAULT_NA_VALUES) == ["d.csv:n"]


def test_blank_cells_do_not_disqualify_a_numeric_column(tmp_path):
    f = write(tmp_path, "d.csv", "v\n1.0\n\n3.0\n")
    assert open_sources((f,)).numeric_columns(DEFAULT_NA_VALUES) == ["d.csv:v"]


def test_resolve_splits_on_the_last_colon(tmp_path):
    # a column literally named with a colon is unusual, but the file part is
    # matched first, so the remainder is the column.
    f = write(tmp_path, "meas.csv", "id,v\nA1,1.0\n")
    assert open_sources((f,)).resolve("meas.csv:v").name == "v"


def test_basename_resolves_when_unique(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    f = write(sub, "meas.csv", "id,v\nA1,1.0\n")
    src = open_sources((f,))
    assert src.resolve("meas.csv:v").name == "v"          # basename
    assert src.resolve(f"{f}:v").name == "v"               # full path also works


def test_ambiguous_basename_requires_the_full_path(tmp_path):
    a = write(tmp_path / "one", "meas.csv", "id,v\nA,1\n") if (tmp_path / "one").mkdir() or True else None
    b = write(tmp_path / "two", "meas.csv", "id,v\nB,2\n") if (tmp_path / "two").mkdir() or True else None
    src = open_sources((a, b))
    with pytest.raises(DataError, match="ambiguous"):
        src.resolve("meas.csv:v")
    assert src.resolve(f"{a}:v").values == ["1"]           # full path disambiguates


def test_resolve_reports_an_unknown_file(tmp_path):
    f = write(tmp_path, "meas.csv", "id,v\nA1,1.0\n")
    with pytest.raises(DataError, match="no open file"):
        open_sources((f,)).resolve("ghost.csv:v")


def test_resolve_reports_an_unknown_column(tmp_path):
    f = write(tmp_path, "meas.csv", "id,v\nA1,1.0\n")
    with pytest.raises(DataError, match="nope"):
        open_sources((f,)).resolve("meas.csv:nope")


def test_a_missing_file_is_reported_by_name(tmp_path):
    with pytest.raises(DataError, match="not found"):
        open_sources((tmp_path / "ghost.csv",))


def test_length_is_the_row_count(tmp_path):
    f = write(tmp_path, "d.csv", "v\n1\n2\n3\n")
    assert open_sources((f,)).length(f) == 3
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: parity_plot.sources`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest tests/test_sources.py -v` → all pass.
- [ ] **Step 5: Stop. Do not commit.**

---

### Task 2: `config.py` — the new `DataConfig`

**Files:** modify `parity_plot/config.py`; create `tests/test_data_config.py`

**Interfaces produced:**
- `DataConfig(files, ref, test, join, group, na_values)` — `paths/x/y/key/value` gone
- Retired-key `ConfigError` for any of `paths`/`x`/`y`/`key`/`value` in `[data]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_data_config.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ConfigError, DataConfig, ParityConfig


def test_defaults_are_empty():
    d = DataConfig()
    assert d.files == () and d.ref is None and d.test is None
    assert d.join is None and d.group is None


def test_parses_the_new_shape(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[data]\nfiles = ["meas.csv", "sim.csv"]\n'
        'ref = "meas.csv:voltage"\ntest = "sim.csv:voltage"\n'
        'join = "id"\ngroup = "meas.csv:batch"\n',
        encoding="utf-8",
    )
    d = ParityConfig.from_toml(p).data
    assert d.files == (Path("meas.csv"), Path("sim.csv"))
    assert d.ref == "meas.csv:voltage"
    assert d.test == "sim.csv:voltage"
    assert d.join == "id"
    assert d.group == "meas.csv:batch"


def test_join_and_group_are_optional(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text('[data]\nfiles = ["d.csv"]\nref = "d.csv:a"\ntest = "d.csv:b"\n', encoding="utf-8")
    d = ParityConfig.from_toml(p).data
    assert d.join is None and d.group is None


@pytest.mark.parametrize("key, value", [
    ("paths", '["d.csv"]'), ("x", '"reference"'), ("y", '"measured"'),
    ("key", '"id"'), ("value", '"value"'),
])
def test_retired_data_keys_error_with_guidance(tmp_path: Path, key, value):
    p = tmp_path / "c.toml"
    p.write_text(f"[data]\n{key} = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        ParityConfig.from_toml(p)
    assert key in str(exc.value)
    assert "files" in str(exc.value)  # points at the new shape


def test_unknown_data_key_is_rejected(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text('[data]\nfiles = ["d.csv"]\nreff = "d.csv:a"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="reff"):
        ParityConfig.from_toml(p)


def test_merge_overrides_data_fields():
    cfg = ParityConfig.from_dict({"data": {"files": ["a.csv"], "ref": "a.csv:x"}})
    merged = cfg.merge(data={"ref": "a.csv:y"})
    assert merged.data.ref == "a.csv:y"
    assert merged.data.files == (Path("a.csv"),)
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Modify `config.py`**

Replace the `DataConfig` fields:

```python
@dataclass(frozen=True)
class DataConfig:
    """Where the numbers come from.

    An arbitrary set of files; the two plotted series are `file:column` refs.
    A join column aligns rows across files; without one, rows pair by order.
    """
    files: tuple[Path, ...] = ()
    ref: str | None = None       # "file:column", a numeric column
    test: str | None = None      # "file:column", a numeric column
    join: str | None = None      # column name in both files, or None -> pair by order
    group: str | None = None     # "file:column", any column, or None
    na_values: tuple[str, ...] = DEFAULT_NA_VALUES
```

Add coercion: `files` uses the existing `_TUPLE_OF_PATH` set (add `"files"` to it, drop
`"paths"`). `ref`/`test`/`join`/`group` are plain optional strings (no special coercion
needed — they fall through to the default branch). Remove `paths` from `_TUPLE_OF_PATH`.

Add the retired-key guard, mirroring `RETIRED_PLOT_KEYS`:

```python
RETIRED_DATA_KEYS = ("paths", "x", "y", "key", "value")
```

and in `_build`, before the unknown-key check, when `cls is DataConfig`:

```python
    if cls is DataConfig:
        retired = [k for k in RETIRED_DATA_KEYS if k in raw]
        if retired:
            raise ConfigError(
                f"{source}: {', '.join(retired)} were replaced in 0.3.0. Use:\n"
                f"  [data]\n"
                f'  files = ["meas.csv", "sim.csv"]\n'
                f'  ref   = "meas.csv:voltage"    # file:column\n'
                f'  test  = "sim.csv:voltage"\n'
                f'  join  = "id"                  # optional; omit to pair by order\n'
            )
```

Update `EXAMPLE_TOML`'s `[data]` block to the new shape.

- [ ] **Step 4: Run** `tests/test_data_config.py` → pass. The full suite will now have many
  failures (everything using `DataConfig(paths=...)`); those are Task 4's.

- [ ] **Step 5: Stop. Do not commit.**

---

### Task 3: `data.py` — `load` around Sources (detailed in its own prompt)

Rewrites `load(cfg)` to open sources, resolve ref/test/group, align by join or order, and
carry `group` onto `ParityData`. **`sources.py` imports helpers from `data.py`, so `data.py`
must import `open_sources` lazily inside `load()`** — a module-scope import back into
sources would be a circular import. Adds `ParityData.group: list[str] | None`. Removes
`load_wide`/`load_pair`/the path-count dispatch. Depends on Tasks 1 and 2. Its prompt will
carry the full test + implementation once Tasks 1–2 land and their exact signatures are
fixed.

### Task 4: `cli.py`, `__init__.py`, and the test sweep (detailed in its own prompt)

`--ref/--test/--join/--group`, `PATHS` as `files`, single-file default to first two numeric
columns; public `parity_plot(*paths, ref=, test=, join=, group=)`. Then the mechanical
sweep of every test using the old shape, driving the suite back to green. Depends on 1–3.

---

## Self-review

Covers the plan's Phase 1: `sources.py` with numeric filtering (Tasks 1), the config
replacement with clean-break errors (Task 2), the `load` rewrite and `ParityData.group`
(Task 3), and the CLI/API/test sweep (Task 4). The one-file and two-file behaviours fall out
of the general path — verified in Task 3/4's render checks against 0.2.0 output.
