# Designer Phase 3 (Triage) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A sortable table beside the plot, linked to it in both directions, with filters that narrow both to the records you care about — "which parts failed spec" answered in one look.

**Architecture:** Two new pure modules (`filters.py` for the predicates, `table_rows.py` for the row shape) plus a `filters` field on `DesignerState`. The one structural change: `figure()` and the statistics now read the *filtered* view rather than the raw dataset, so the plot, the table and the metrics can never disagree about what is being shown.

**Tech Stack:** Python ≥3.11, NiceGUI 3.14, Plotly 6.9, pytest 9.

## Global Constraints

- **Python floor `>=3.11`.** Do not change it.
- **Never reimplement plotting, statistics, or tolerance geometry.** Call `build_figure`, `stats.compute`, `Tolerance`.
- **Filters are exploration state and must never reach the saved TOML.** `FilterSet` lives on `DesignerState`, never on `ParityConfig`. A config that encoded a temporary view would render differently from what the CLI produces, which breaks the guarantee `tests/designer/test_golden_wysiwyg.py` exists to protect.
- **A default `FilterSet` must be a no-op**, returning data equal to its input. The golden tests compare the designer's figure against the CLI's; if an unfiltered designer altered the data at all, they would fail — and they *should* fail, because the designer would be lying.
- **All config edits go through `ParityConfig.merge`.** Never construct config objects from widget values.
- **`ParityConfig` and its sections are frozen dataclasses.** Never `object.__setattr__` on one.
- **No numpy or pandas.** Standard library only.
- **nicegui is an optional extra.** Import it inside functions; pure modules must not import it at all.
- **`figure()` does not clear `last_error` on success.** Do not "tidy" that back in — a failed load leaves old data loaded, so the next redraw succeeds and would wipe the message before it displayed.
- Run tests with `.venv/bin/python -m pytest`. **Baseline is 296 passing.**

---

### Task 1: `filters.py` — narrowing the view

**Files:**
- Create: `parity_plot/designer/filters.py`
- Test: `tests/designer/test_filters.py`

**Interfaces:**
- Consumes: `parity_plot.data.ParityData`, `parity_plot.data.Unpaired`, `parity_plot.tolerance.Tolerance`
- Produces:
  - `FilterSet(outside_tolerance_only=False, show_paired=True, show_unpaired=True, x_range=None)`
  - `FilterSet.apply(data: ParityData, tol: Tolerance | None = None) -> ParityData`
  - `FilterSet.is_active: bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_filters.py
from __future__ import annotations

import pytest

from parity_plot.data import from_sequences
from parity_plot.designer.filters import FilterSet
from parity_plot.tolerance import Tolerance


@pytest.fixture
def data():
    # a,b,c paired (a and c are 10% off, b is 1% off); d missing y; e missing x
    return from_sequences(
        x=[10.0, 100.0, 50.0, 70.0, None],
        y=[11.0, 101.0, 55.0, None, 33.0],
        keys=["a", "b", "c", "d", "e"],
    )


def test_the_default_filter_changes_nothing(data):
    """The golden tests compare an unfiltered designer against the CLI; if the
    default filter altered anything they would fail, and rightly so."""
    result = FilterSet().apply(data)

    assert result.keys == data.keys
    assert result.x == data.x
    assert result.y == data.y
    assert result.missing_y.keys == data.missing_y.keys
    assert result.missing_x.keys == data.missing_x.keys
    assert result.n_dropped == data.n_dropped


def test_the_default_filter_is_not_active():
    assert not FilterSet().is_active
    assert FilterSet(show_paired=False).is_active
    assert FilterSet(outside_tolerance_only=True).is_active
    assert FilterSet(x_range=(0.0, 1.0)).is_active


def test_hiding_paired_records_leaves_only_the_unpaired(data):
    result = FilterSet(show_paired=False).apply(data)

    assert result.keys == []
    assert result.missing_y.keys == ["d"]
    assert result.missing_x.keys == ["e"]


def test_hiding_unpaired_records_leaves_only_the_paired(data):
    result = FilterSet(show_unpaired=False).apply(data)

    assert result.keys == ["a", "b", "c"]
    assert len(result.missing_y) == 0
    assert len(result.missing_x) == 0


def test_outside_tolerance_keeps_only_the_failures(data):
    result = FilterSet(outside_tolerance_only=True).apply(data, Tolerance(reltol=0.05))

    assert result.keys == ["a", "c"]  # 10% off; b is 1% off and passes


def test_outside_tolerance_does_nothing_without_a_tolerance(data):
    """With no spec to fail, nothing can be outside it."""
    result = FilterSet(outside_tolerance_only=True).apply(data, None)
    assert result.keys == ["a", "b", "c"]


def test_outside_tolerance_leaves_unpaired_records_to_the_other_switch(data):
    """An unpaired record was never judged, so 'outside tolerance' has no
    opinion about it -- show_unpaired governs it instead."""
    result = FilterSet(outside_tolerance_only=True).apply(data, Tolerance(reltol=0.05))
    assert result.missing_y.keys == ["d"]
    assert result.missing_x.keys == ["e"]

    both = FilterSet(outside_tolerance_only=True, show_unpaired=False).apply(
        data, Tolerance(reltol=0.05)
    )
    assert len(both.missing_y) == 0


def test_x_range_keeps_records_inside_the_window(data):
    result = FilterSet(x_range=(40.0, 80.0)).apply(data)

    assert result.keys == ["c"]          # x = 50
    assert result.missing_y.keys == ["d"]  # x = 70, known
    assert result.missing_x.keys == []     # no x at all, so not in any window


def test_x_range_bounds_are_inclusive(data):
    assert FilterSet(x_range=(10.0, 10.0)).apply(data).keys == ["a"]


def test_filters_combine(data):
    result = FilterSet(outside_tolerance_only=True, show_unpaired=False).apply(
        data, Tolerance(reltol=0.05)
    )
    assert result.keys == ["a", "c"]
    assert len(result.missing_y) == 0
    assert len(result.missing_x) == 0


def test_labels_and_dropped_count_survive_filtering(data):
    result = FilterSet(show_paired=False).apply(data)
    assert result.x_label == data.x_label
    assert result.y_label == data.y_label
    assert result.n_dropped == data.n_dropped


def test_filtering_never_reclassifies_a_record(data):
    """Hiding a record is a filter; turning an unpaired one into a paired one
    would be a bug that silently invents a measurement."""
    result = FilterSet(x_range=(0.0, 1000.0)).apply(data)
    for key, x, y in zip(result.keys, result.x, result.y):
        assert x is not None and y is not None
    assert "d" not in result.keys
    assert "e" not in result.keys
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_filters.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.filters'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/filters.py
"""Narrowing what the plot and the table show.

Filters are exploration state. They never reach the saved config: a TOML that
encoded "only the failures" would render a different plot from the one the CLI
produces, and the designer's whole claim is that those two agree.

Each switch is independent and answers one question, so combinations behave the
way reading them aloud suggests.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..data import ParityData, Unpaired
from ..tolerance import Tolerance


@dataclass(frozen=True)
class FilterSet:
    """Which records are currently worth looking at."""

    outside_tolerance_only: bool = False
    show_paired: bool = True
    show_unpaired: bool = True
    x_range: tuple[float, float] | None = None

    @property
    def is_active(self) -> bool:
        """Whether this differs from showing everything."""
        return (
            self.outside_tolerance_only
            or not self.show_paired
            or not self.show_unpaired
            or self.x_range is not None
        )

    def apply(self, data: ParityData, tol: Tolerance | None = None) -> ParityData:
        """Return the subset of ``data`` that passes every active filter.

        A default FilterSet returns an equal dataset, which the golden tests
        depend on: an unfiltered designer must render exactly what the CLI does.
        """
        paired = list(zip(data.keys, data.x, data.y))

        if not self.show_paired:
            paired = []
        else:
            if self.outside_tolerance_only and tol:
                # An unpaired record has no verdict, so this switch says nothing
                # about it; show_unpaired governs those.
                paired = [(k, x, y) for k, x, y in paired if not tol.contains(x, y)]
            if self.x_range is not None:
                paired = [(k, x, y) for k, x, y in paired if self._in_range(x)]

        missing_y = self._filter_unpaired(data.missing_y)
        missing_x = self._filter_unpaired(data.missing_x, has_x=False)

        return replace(
            data,
            keys=[k for k, _, _ in paired],
            x=[x for _, x, _ in paired],
            y=[y for _, _, y in paired],
            missing_y=missing_y,
            missing_x=missing_x,
        )

    def _filter_unpaired(self, unpaired: Unpaired, has_x: bool = True) -> Unpaired:
        if not self.show_unpaired:
            return Unpaired([], [])
        if self.x_range is None:
            return unpaired
        if not has_x:
            # These records have no x value, so no x window contains them.
            return Unpaired([], [])
        kept = [
            (k, v) for k, v in zip(unpaired.keys, unpaired.values) if self._in_range(v)
        ]
        return Unpaired([k for k, _ in kept], [v for _, v in kept])

    def _in_range(self, value: float) -> bool:
        assert self.x_range is not None
        low, high = self.x_range
        return low <= value <= high
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_filters.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/filters.py tests/designer/test_filters.py
git commit -m "feat(designer): filters for narrowing the plot and table"
```

---

### Task 2: `table_rows.py` — the row shape

**Files:**
- Create: `parity_plot/designer/table_rows.py`
- Test: `tests/designer/test_table_rows.py`

**Interfaces:**
- Consumes: `parity_plot.designer.records.RecordView`
- Produces:
  - `COLUMNS: list[dict]` — Quasar column definitions, every one sortable
  - `to_rows(views: list[RecordView]) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_table_rows.py
from __future__ import annotations

import pytest

from parity_plot.designer.records import RecordView
from parity_plot.designer.table_rows import COLUMNS, to_rows


@pytest.fixture
def views():
    return [
        RecordView("a", 10.0, 11.0, 1.0, 0.1, "paired", False),
        RecordView("b", 100.0, 101.0, 1.0, 0.01, "paired", True),
        RecordView("d", 70.0, None, None, None, "missing y", None),
    ]


def test_every_column_is_sortable():
    """Sorting by absolute error is the question this table exists to answer."""
    assert COLUMNS
    assert all(column["sortable"] for column in COLUMNS)


def test_column_fields_match_the_row_keys(views):
    row = to_rows(views)[0]
    for column in COLUMNS:
        assert column["field"] in row


def test_row_key_column_comes_first():
    assert COLUMNS[0]["field"] == "key"


def test_numbers_stay_numbers_so_sorting_is_numeric(views):
    """Formatted strings would sort lexically: 9 after 100."""
    row = to_rows(views)[0]
    assert isinstance(row["x"], float)
    assert isinstance(row["error"], float)


def test_numbers_are_rounded_for_display(views):
    rows = to_rows([RecordView("z", 1 / 3, 2 / 3, 1 / 3, 1 / 3, "paired", None)])
    assert rows[0]["x"] == pytest.approx(0.333333, abs=1e-6)
    assert len(str(rows[0]["x"])) < 12


def test_relative_error_is_shown_as_a_percentage(views):
    assert to_rows(views)[0]["rel_error"] == pytest.approx(10.0)
    assert to_rows(views)[1]["rel_error"] == pytest.approx(1.0)


def test_missing_values_are_none_not_zero(views):
    row = next(r for r in to_rows(views) if r["key"] == "d")
    assert row["y"] is None
    assert row["error"] is None
    assert row["rel_error"] is None


def test_verdict_reads_as_words(views):
    rows = {r["key"]: r for r in to_rows(views)}
    assert rows["a"]["verdict"] == "OUT"
    assert rows["b"]["verdict"] == "within"
    assert rows["d"]["verdict"] == ""  # never judged, so no verdict claimed


def test_status_is_carried_through(views):
    rows = {r["key"]: r for r in to_rows(views)}
    assert rows["d"]["status"] == "missing y"


def test_empty_input_gives_no_rows():
    assert to_rows([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_table_rows.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.table_rows'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/table_rows.py
"""Turning records into table rows.

Values stay numeric rather than becoming formatted strings, because the table's
reason for existing is sorting by error magnitude and strings sort lexically --
"9" would land after "100". Rounding at build time keeps the display readable
without giving up numeric ordering.
"""

from __future__ import annotations

from typing import Any, Sequence

from .records import RecordView

# Quasar column definitions. Every column sorts; the point of the table is to
# put the worst offenders at the top on demand.
COLUMNS: list[dict[str, Any]] = [
    {"name": "key", "label": "Record", "field": "key", "required": True,
     "align": "left", "sortable": True},
    {"name": "x", "label": "Reference", "field": "x", "sortable": True},
    {"name": "y", "label": "Measured", "field": "y", "sortable": True},
    {"name": "error", "label": "Error", "field": "error", "sortable": True},
    {"name": "rel_error", "label": "Error %", "field": "rel_error", "sortable": True},
    {"name": "status", "label": "Status", "field": "status", "align": "left",
     "sortable": True},
    {"name": "verdict", "label": "Tolerance", "field": "verdict", "align": "left",
     "sortable": True},
]

_DIGITS = 6


def to_rows(views: Sequence[RecordView]) -> list[dict[str, Any]]:
    """One row per record, numbers kept as numbers."""
    return [
        {
            "key": view.key,
            "x": _round(view.x),
            "y": _round(view.y),
            "error": _round(view.error),
            "rel_error": _round(None if view.rel_error is None else view.rel_error * 100),
            "status": view.status,
            "verdict": _verdict(view.within),
        }
        for view in views
    ]


def _round(value: float | None) -> float | None:
    """Readable in the cell, still numeric for sorting."""
    if value is None:
        return None
    return float(f"{value:.{_DIGITS}g}")


def _verdict(within: bool | None) -> str:
    """Blank when the record was never judged.

    `within` is None for unpaired records and when no tolerance is set; printing
    a verdict there would claim a result that was never assessed.
    """
    if within is None:
        return ""
    return "within" if within else "OUT"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_table_rows.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/table_rows.py tests/designer/test_table_rows.py
git commit -m "feat(designer): numeric table rows that sort correctly"
```

---

### Task 3: Wiring filters into `DesignerState`

This is the one structural change of the phase: the plot and the statistics start reading the filtered view.

**Files:**
- Modify: `parity_plot/designer/state.py`
- Test: `tests/designer/test_state_filters.py`

**Interfaces:**
- Consumes: `FilterSet` (Task 1)
- Produces:
  - `DesignerState.filters: FilterSet`
  - `DesignerState.tolerance() -> Tolerance`
  - `DesignerState.visible_data() -> ParityData`
  - `DesignerState.visible_records() -> list[RecordView]`
  - `DesignerState.counts() -> tuple[int, int]` — `(showing, total)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_state_filters.py
from __future__ import annotations

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import from_sequences
from parity_plot.designer.filters import FilterSet
from parity_plot.designer.state import DesignerState


@pytest.fixture
def state():
    data = from_sequences(
        x=[10.0, 100.0, 50.0, 70.0, None],
        y=[11.0, 101.0, 55.0, None, 33.0],
        keys=["a", "b", "c", "d", "e"],
    )
    return DesignerState(config=ParityConfig(), data=data)


def test_by_default_everything_is_visible(state):
    assert not state.filters.is_active
    assert state.visible_data().keys == state.data.keys
    assert state.counts() == (5, 5)


def test_tolerance_comes_from_the_config(state):
    assert state.tolerance().reltol is None

    state.update("plot", reltol=0.05)
    assert state.tolerance().reltol == pytest.approx(0.05)

    state.update("plot", abstol=2.0)
    assert state.tolerance().abstol == pytest.approx(2.0)


def test_filtering_narrows_the_visible_data(state):
    state.update("plot", reltol=0.05)
    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)

    assert state.visible_data().keys == ["a", "c"]
    assert state.counts() == (2, 5)


def test_the_figure_shows_the_filtered_view(state):
    """A filtered table beside an unfiltered plot would be two answers to one
    question."""
    before = state.figure().to_dict()
    state.filters = FilterSet(show_unpaired=False)
    after = state.figure().to_dict()

    assert before != after


def test_the_statistics_follow_the_filter(state):
    state.update("plot", reltol=0.05)
    unfiltered = state.figure()

    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)
    filtered = state.figure()

    assert "3 paired" in unfiltered.layout.title.subtitle.text
    assert "2 paired" in filtered.layout.title.subtitle.text


def test_visible_records_are_judged_against_the_current_tolerance(state):
    state.update("plot", reltol=0.05)
    verdicts = {v.key: v.within for v in state.visible_records()}

    assert verdicts["a"] is False
    assert verdicts["b"] is True
    assert verdicts["d"] is None  # unpaired, never judged


def test_filters_do_not_touch_the_config(state):
    """A saved config must never encode a temporary view."""
    before = state.config
    state.filters = FilterSet(outside_tolerance_only=True, show_paired=False)
    assert state.config == before


def test_the_underlying_dataset_is_never_modified(state):
    original = list(state.data.keys)
    state.filters = FilterSet(show_paired=False)
    state.visible_data()
    assert state.data.keys == original


def test_selected_record_still_reads_the_full_dataset(state):
    """Filtering out the selected record must not make it unreadable -- the
    inspector should still describe what you clicked."""
    state.selection = "a"
    state.filters = FilterSet(show_paired=False)
    assert state.selected_record() is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_state_filters.py -v`
Expected: FAIL — `AttributeError: 'DesignerState' object has no attribute 'filters'`

- [ ] **Step 3: Modify `parity_plot/designer/state.py`**

Add the import beside the existing ones:

```python
from .filters import FilterSet
```

Add the field to the dataclass, after `selection`:

```python
    filters: FilterSet = field(default_factory=FilterSet)
```

Add these methods after `selected_record`:

```python
    def tolerance(self) -> Tolerance:
        """The tolerance the current config specifies."""
        return Tolerance(abstol=self.config.plot.abstol, reltol=self.config.plot.reltol)

    def visible_data(self) -> ParityData:
        """The dataset after filtering. The plot and the table both read this."""
        return self.filters.apply(self.data, self.tolerance())

    def visible_records(self) -> list[RecordView]:
        """One row per visible record, judged against the current tolerance."""
        return record_views(self.visible_data(), self.tolerance())

    def counts(self) -> tuple[int, int]:
        """``(showing, total)`` records -- a filtered view that looks unfiltered
        is a trap, so the UI always states both."""
        visible = self.visible_data()
        showing = visible.n_paired + visible.n_unpaired
        total = self.data.n_paired + self.data.n_unpaired
        return showing, total
```

Change **one line** in `figure()` — the `build_figure` call — so the plot and the
statistics read the filtered view:

```python
            figure = build_figure(self.visible_data(), self.config.plot, self.config.stats)
```

Everything else in `figure()` stays exactly as it is, including the comment about
not clearing `last_error`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_state_filters.py -v`
Expected: PASS, 9 tests

Then the whole suite: `.venv/bin/python -m pytest -q`.

**The golden tests must still pass.** They compare the designer's figure against the
CLI's; they pass only because a default `FilterSet` is a no-op. If they fail here, the
default filter is altering data and the fault is in `filters.py`, not in the golden tests.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/state.py tests/designer/test_state_filters.py
git commit -m "feat(designer): plot and stats read the filtered view"
```

---

### Task 4: The table panel

**Files:**
- Create: `parity_plot/designer/panels/table.py`
- Test: `tests/designer/test_table_panel.py`

**Interfaces:**
- Consumes: `COLUMNS`, `to_rows` (Task 2), `DesignerState.visible_records`, `.counts`, `.filters` (Task 3)
- Produces:
  - `table.summary_text(showing: int, total: int) -> str`
  - `table.build_table(state: DesignerState, on_select: Callable[[str | None], None], on_filter_change: Callable[[], None]) -> Callable[[], None]` — returns a refresh function

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_table_panel.py
from __future__ import annotations

from parity_plot.designer.panels.table import summary_text


def test_summary_states_both_numbers_when_filtered():
    """A filtered view that looks unfiltered is a trap."""
    assert summary_text(14, 1000) == "showing 14 of 1,000"


def test_summary_is_plain_when_nothing_is_hidden():
    assert summary_text(1000, 1000) == "1,000 records"


def test_summary_handles_an_empty_result():
    assert summary_text(0, 1000) == "showing 0 of 1,000"


def test_summary_handles_an_empty_dataset():
    assert summary_text(0, 0) == "0 records"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_table_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.panels.table'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/panels/table.py
"""The record table and the filter switches that narrow it."""

from __future__ import annotations

from typing import Callable

from ..filters import FilterSet
from ..state import DesignerState
from ..table_rows import COLUMNS, to_rows


def summary_text(showing: int, total: int) -> str:
    """How much of the data is on screen.

    Always states both numbers when anything is hidden: a filtered view that
    looks unfiltered invites the wrong conclusion about the data.
    """
    if showing == total:
        return f"{total:,} records"
    return f"showing {showing:,} of {total:,}"


def build_table(
    state: DesignerState,
    on_select: Callable[[str | None], None],
    on_filter_change: Callable[[], None],
) -> Callable[[], None]:
    """Render the filters and the table. Returns a function that refreshes them."""
    from nicegui import ui

    with ui.column().classes("w-full gap-2"):
        with ui.row().classes("items-center gap-4"):
            failures = ui.switch("Failures only")
            unpaired = ui.switch("Include unpaired", value=True)
            summary = ui.label("").classes("text-sm opacity-70")

        table = ui.table(
            columns=COLUMNS,
            rows=[],
            row_key="key",
            selection="single",
            pagination=15,
        ).classes("w-full")

    def apply_filters() -> None:
        state.filters = FilterSet(
            outside_tolerance_only=bool(failures.value),
            show_unpaired=bool(unpaired.value),
            show_paired=state.filters.show_paired,
            x_range=state.filters.x_range,
        )
        on_filter_change()

    failures.on_value_change(lambda _: apply_filters())
    unpaired.on_value_change(lambda _: apply_filters())

    def handle_selection(event) -> None:
        rows = event.selection or []
        on_select(rows[0]["key"] if rows else None)

    table.on_select(handle_selection)

    def refresh() -> None:
        table.rows = to_rows(state.visible_records())
        showing, total = state.counts()
        summary.text = summary_text(showing, total)
        # Keep the table's highlight in step with the pinned record, so a click
        # on the plot lands here too.
        table.selected = [r for r in table.rows if r["key"] == state.selection]
        table.update()

    refresh()
    return refresh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_table_panel.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/panels/table.py tests/designer/test_table_panel.py
git commit -m "feat(designer): record table with filter switches"
```

---

### Task 5: Linking the table and the plot

**Files:**
- Modify: `parity_plot/designer/app.py` (additively)
- Test: `tests/designer/test_selection_link.py`

**Interfaces:**
- Consumes: `build_table` (Task 4), `key_from_customdata`, `DesignerState.selection`
- Produces: `app.select_record(state, key, *panels) -> None` — the single place selection is set

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_selection_link.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.app import select_record
from parity_plot.designer.state import DesignerState

WIDE = "id,reference,measured\nA1,10.0,11.0\nA2,20.0,21.0\nA3,30.0,\n"


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    csv = tmp_path / "wide.csv"
    csv.write_text(WIDE, encoding="utf-8")
    config = ParityConfig().merge(data={"paths": (csv,)})
    return DesignerState(config=config, data=load(config.data))


def test_selecting_sets_the_one_shared_selection(state):
    """Plot and table both route through here, so they cannot disagree."""
    calls = []
    select_record(state, "A2", lambda: calls.append("a"), lambda: calls.append("b"))

    assert state.selection == "A2"
    assert calls == ["a", "b"]


def test_selecting_none_clears_it(state):
    state.selection = "A1"
    select_record(state, None)
    assert state.selection is None


def test_reselecting_the_same_record_is_harmless(state):
    select_record(state, "A1")
    select_record(state, "A1")
    assert state.selection == "A1"


def test_every_refresh_callback_runs_even_if_one_is_none(state):
    ran = []
    select_record(state, "A1", None, lambda: ran.append(1))
    assert ran == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_selection_link.py -v`
Expected: FAIL — `ImportError: cannot import name 'select_record'`

- [ ] **Step 3: Modify `parity_plot/designer/app.py`**

Add this module-level function, above `build_app`:

```python
def select_record(state: DesignerState, key: str | None, *refreshers) -> None:
    """Pin a record and tell every panel to catch up.

    Both the plot and the table route through here rather than each setting
    `state.selection` themselves, so neither can end up showing a different
    record from the other.
    """
    state.selection = key
    for refresh in refreshers:
        if refresh is not None:
            refresh()
```

Add the import beside the others:

```python
from .panels.table import build_table
```

Inside `page()`, replace the existing `on_point_click` body so it routes through
`select_record`, and mount the table below the plot. The right-hand column becomes:

```python
            with ui.column().classes("grow"):
                plot_view = ui.plotly(state.figure()).classes("w-full h-[55vh]")
                error_banner = ui.label("").classes("text-red-400 text-sm")
                refresh_inspector = build_inspector(state, state.tolerance)

                refresh_table = build_table(
                    state,
                    on_select=lambda key: select_record(state, key, refresh_inspector),
                    on_filter_change=lambda: refresh(),
                )

                def on_point_click(event) -> None:
                    points = (event.args or {}).get("points") or []
                    if not points:
                        return
                    key = key_from_customdata(points[0].get("customdata"))
                    select_record(state, key, refresh_inspector, refresh_table)

                plot_view.on("plotly_click", on_point_click)
```

Note `build_inspector(state, state.tolerance)` — `DesignerState.tolerance` is now a
method, so it can be passed directly as the callable the inspector needs. The old
inline `lambda: Tolerance(...)` is no longer required, and the `Tolerance` import in
`app.py` can go if nothing else uses it.

Extend `refresh` so the table follows too:

```python
        def refresh() -> None:
            plot_view.update_figure(state.figure())
            error_banner.text = state.last_error or ""
            status.text = "unsaved changes" if session.is_dirty(state.config) else "saved"
            refresh_inspector()
            refresh_table()
```

`refresh_table` is defined after `refresh` in the source but only *called* at
runtime, so the ordering is fine — Python resolves the name when `refresh` runs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_selection_link.py -v`
Expected: PASS, 4 tests

Then the whole suite, including the real-server test in `test_app.py`, which will
catch a broken page build.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/app.py tests/designer/test_selection_link.py
git commit -m "feat(designer): link table and plot through one selection"
```

---

### Task 6: Integration and docs

**Files:**
- Test: `tests/designer/test_phase3_integration.py`
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Write the tests**

```python
# tests/designer/test_phase3_integration.py
"""Phase 3 end to end: filter to the failures and find the worst offender."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.filters import FilterSet
from parity_plot.designer.panels.table import summary_text
from parity_plot.designer.state import DesignerState
from parity_plot.designer.table_rows import to_rows

# A1 +10%, A2 +0.5%, A3 +25%, A4 unpaired
WIDE = (
    "id,reference,measured\n"
    "A1,10.0,11.0\n"
    "A2,100.0,100.5\n"
    "A3,40.0,50.0\n"
    "A4,70.0,\n"
)


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    csv = tmp_path / "wide.csv"
    csv.write_text(WIDE, encoding="utf-8")
    config = ParityConfig().merge(data={"paths": (csv,)})
    return DesignerState(config=config, data=load(config.data))


def test_filter_to_failures_then_sort_by_error(state):
    state.update("plot", reltol=0.05)
    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)

    rows = to_rows(state.visible_records())
    worst = max(rows, key=lambda r: abs(r["error"]))

    assert {r["key"] for r in rows} == {"A1", "A3"}
    assert worst["key"] == "A3"
    assert state.counts() == (2, 4)
    assert summary_text(*state.counts()) == "showing 2 of 4"


def test_the_plot_shows_exactly_what_the_table_lists(state):
    state.update("plot", reltol=0.05)
    state.filters = FilterSet(outside_tolerance_only=True, show_unpaired=False)

    figure = state.figure()
    paired = next(t for t in figure.data if t.name and t.name.startswith("paired"))
    table_keys = {r["key"] for r in to_rows(state.visible_records())}

    assert len(paired.x) == len(table_keys)
    assert set(paired.customdata[i][0] for i in range(len(paired.x))) == table_keys


def test_unfiltered_designer_still_matches_the_cli(state, tmp_path: Path):
    """The Phase 1 guarantee must survive filters existing at all."""
    from parity_plot.designer.session import Session
    from parity_plot.plot import build_figure

    session, config, data = Session.start((state.config.data.paths[0],), None)
    fresh = DesignerState(config=config, data=data)
    fresh.update("plot", reltol=0.05)

    out = tmp_path / "parity.toml"
    session.save(fresh.config, out)
    from_disk = ParityConfig.from_toml(out)
    rendered = build_figure(load(from_disk.data), from_disk.plot, from_disk.stats)

    assert rendered.to_dict() == fresh.figure().to_dict()


def test_a_saved_config_carries_no_filter_state(state, tmp_path: Path):
    from parity_plot.designer.session import Session

    session, config, data = Session.start((state.config.data.paths[0],), None)
    live = DesignerState(config=config, data=data)
    live.filters = FilterSet(outside_tolerance_only=True, show_paired=False)

    out = tmp_path / "parity.toml"
    session.save(live.config, out)
    text = out.read_text(encoding="utf-8")

    for word in ("filter", "outside_tolerance", "show_paired", "x_range"):
        assert word not in text


def test_brushing_an_x_window_narrows_both(state):
    state.filters = FilterSet(x_range=(35.0, 75.0))

    rows = to_rows(state.visible_records())
    assert {r["key"] for r in rows} == {"A3", "A4"}  # A4's x is known
    assert state.counts() == (2, 4)


def test_clearing_the_filters_restores_everything(state):
    state.filters = FilterSet(show_paired=False)
    assert state.counts() == (1, 4)

    state.filters = FilterSet()
    assert state.counts() == (4, 4)
    assert state.visible_data().keys == state.data.keys
```

- [ ] **Step 2: Run them, then the whole suite**

Run: `.venv/bin/python -m pytest tests/designer/test_phase3_integration.py -v` → 6 passed
Run: `.venv/bin/python -m pytest -q` → everything green

- [ ] **Step 3: Verify the server still starts**

```bash
.venv/bin/parity-plot design data/example.csv --port 8097 --no-open-browser &
sleep 4 && curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8097/
```
Expected: `200`. Kill it afterwards.

- [ ] **Step 4: Update the docs**

Add to the README's designer section:

```markdown
The **table** below the plot lists every visible record — reference, measured,
signed error, error percent, status and tolerance verdict — and sorts by any
column, so "which parts are furthest out of spec" is one click. Selecting a row
highlights the point, and clicking a point highlights the row.

Two switches narrow both at once: **Failures only** keeps the paired records
outside the current tolerance, and **Include unpaired** governs records missing a
measurement. The count beside them always reads `showing 14 of 1,000` when
anything is hidden — a filtered view that looked unfiltered would invite the
wrong conclusion.

Filters are exploration state and are never written to the config. A saved
`parity.toml` describes the plot, not whatever you were looking at.
```

Add to `CLAUDE.md`:

```markdown
**Filters never reach the config.** `FilterSet` lives on `DesignerState`, not on
`ParityConfig`. A config encoding a temporary view would render differently from
what the CLI produces, breaking the guarantee `test_golden_wysiwyg.py` protects —
and a test asserts no filter vocabulary appears in a saved TOML.

**A default `FilterSet` must be a no-op.** `figure()` renders `visible_data()`, so
if an unfiltered designer altered the data at all, the golden tests would fail. If
they ever do, suspect `filters.py`, not the golden tests.

`table_rows.to_rows` keeps values numeric and rounds them, rather than formatting
to strings: the table exists to sort by error magnitude, and strings sort lexically
so "9" lands after "100".

Selection has exactly one owner. Both the plot click and the table row route
through `app.select_record`, so the two views cannot end up highlighting different
records.
```

- [ ] **Step 5: Commit**

```bash
git add tests/designer/test_phase3_integration.py README.md CLAUDE.md
git commit -m "test(designer): phase 3 integration, plus docs"
```

---

## Self-Review

**Spec coverage.** The spec's Phase 3 asks for: a sortable table of key/x/y/error/relative error/status beside the plot (Tasks 2, 4), sorting by absolute error to find the worst offenders (Task 2's numeric rows, asserted in Task 6), bidirectional plot↔table selection with neither owning it (Task 5's `select_record`), filters for out-of-tolerance and unpaired plus brush-to-x-range (Task 1), and a "showing 14 of 1,000" indicator (Task 4's `summary_text`).

**Type consistency.** `FilterSet(...)` keyword names match across Tasks 1, 3, 4 and 6. `state.counts() -> (showing, total)` feeds `summary_text(showing, total)` in the same order. `to_rows(views)` takes `RecordView`s from `state.visible_records()` in Tasks 4 and 6. `build_table(state, on_select, on_filter_change) -> Callable` matches its call in Task 5.

**Deliberate deviations.** (1) `DesignerState.tolerance()` is added as a method in Task 3, which lets Task 5 pass `state.tolerance` directly to `build_inspector` in place of Phase 2's inline lambda — a simplification the phase enables rather than a change in behaviour. (2) The brush UI is not built: `FilterSet.x_range` is implemented and tested, and the plot's own box-select would drive it, but wiring Plotly's `plotly_selected` event is deferred rather than half-built. The filter works today via the API and the two switches cover the triage cases the spec names.

**Known risk.** Task 3 changes `figure()` to render `visible_data()`. That is the only edit in this phase that can break existing behaviour, and the golden tests are the tripwire — they pass only if a default `FilterSet` is genuinely inert.
