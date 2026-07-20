# Brush Selection Implementation Plan

> **For agentic workers:** Implement one task only, as fenced in your prompt. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Drag a box on the plot to narrow the plot, table and statistics to that x-window; double-click to clear.

**Architecture:** `FilterSet.x_range` already exists, is tested, and is honoured by `visible_data()`. This connects Plotly's selection events to it. The payload parsing is a pure function; `app.py` only forwards events.

**Tech Stack:** Python ≥3.11, NiceGUI 3.14, Plotly 6.9, pytest 9.

## Global Constraints

- **Python floor `>=3.11`.** Do not change it.
- **Filters never reach the config.** `x_range` lives on `DesignerState.filters`.
- **A default `FilterSet` must stay a no-op**, or the golden tests break.
- **nicegui is imported inside functions only.** Pure modules must not import it.
- **`FilterSet` is frozen.** Build new instances; never `object.__setattr__`.
- Run tests with `.venv/bin/python -m pytest`. **Baseline is 343 passing.**

---

### Task A: `selection.py` — read an x-range out of a Plotly payload

**Files:**
- Create: `parity_plot/designer/selection.py`
- Test: `tests/designer/test_selection_parse.py`

**Interfaces:**
- Produces: `range_from_selection(args: dict | None) -> tuple[float, float] | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_selection_parse.py
from __future__ import annotations

import pytest

from parity_plot.designer.selection import range_from_selection


def test_a_box_selection_uses_its_x_bounds():
    """Box select is the common case; Plotly reports the dragged rectangle."""
    args = {"range": {"x": [10.0, 90.0], "y": [0.0, 100.0]}}
    assert range_from_selection(args) == (10.0, 90.0)


def test_box_bounds_are_normalised_when_dragged_right_to_left():
    """Dragging leftwards gives a reversed pair; a range must be low-to-high."""
    args = {"range": {"x": [90.0, 10.0], "y": [0.0, 100.0]}}
    assert range_from_selection(args) == (10.0, 90.0)


def test_a_lasso_selection_uses_the_extent_of_its_outline():
    args = {"lassoPoints": {"x": [30.0, 55.0, 12.0], "y": [1.0, 2.0, 3.0]}}
    assert range_from_selection(args) == (12.0, 55.0)


def test_falls_back_to_the_selected_points():
    """Some selections report points but neither a range nor a lasso."""
    args = {"points": [{"x": 5.0}, {"x": 25.0}, {"x": 15.0}]}
    assert range_from_selection(args) == (5.0, 25.0)


def test_a_box_range_wins_over_the_points_it_contains():
    """The dragged window is what the user chose, not the points that landed
    in it -- an empty region still means that region."""
    args = {"range": {"x": [0.0, 100.0]}, "points": [{"x": 50.0}]}
    assert range_from_selection(args) == (0.0, 100.0)


@pytest.mark.parametrize("args", [None, {}, {"points": []}, {"range": {}}])
def test_an_empty_selection_is_no_range(args):
    """Clearing the selection must clear the filter, not freeze the last one."""
    assert range_from_selection(args) is None


def test_non_numeric_values_are_ignored():
    assert range_from_selection({"points": [{"x": "abc"}, {"x": 4.0}]}) == (4.0, 4.0)


def test_points_without_an_x_are_ignored():
    """Rug marks on the y axis have no x to contribute."""
    assert range_from_selection({"points": [{"y": 3.0}, {"x": 8.0}]}) == (8.0, 8.0)


def test_a_selection_with_nothing_usable_is_no_range():
    assert range_from_selection({"points": [{"y": 3.0}]}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_selection_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.selection'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/selection.py
"""Reading an x-window out of a Plotly selection event.

Plotly describes a selection three different ways depending on how it was made
-- a dragged rectangle, a lasso outline, or just the points that fell inside --
so this normalises all three into one range. Kept pure so it can be tested
without a browser.
"""

from __future__ import annotations

from typing import Any


def range_from_selection(args: dict[str, Any] | None) -> tuple[float, float] | None:
    """The x-range a selection covers, or None if it covers nothing.

    Returning None for an empty selection is what lets a cleared brush clear
    the filter rather than leaving the previous window stuck in place.
    """
    if not args:
        return None

    # A dragged box is the user's stated intent, even if no points fell inside.
    box = _numbers((args.get("range") or {}).get("x"))
    if box:
        return min(box), max(box)

    lasso = _numbers((args.get("lassoPoints") or {}).get("x"))
    if lasso:
        return min(lasso), max(lasso)

    points = _numbers(p.get("x") for p in (args.get("points") or []))
    if points:
        return min(points), max(points)

    return None


def _numbers(values: Any) -> list[float]:
    """Every value that is genuinely a number, booleans excluded."""
    if values is None:
        return []
    found = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        found.append(float(value))
    return found
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_selection_parse.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Stop. Do not commit.**

---

### Task B: Wire the events into `app.py`

**Files:**
- Modify: `parity_plot/designer/app.py` (additively)
- Test: `tests/designer/test_brush_wiring.py`

**Interfaces:**
- Consumes: `range_from_selection` (Task A)
- Produces: `app.apply_brush(state, args, *refreshers) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_brush_wiring.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.app import apply_brush
from parity_plot.designer.filters import FilterSet
from parity_plot.designer.state import DesignerState

WIDE = (
    "id,reference,measured\n"
    "A1,10.0,11.0\n"
    "A2,50.0,51.0\n"
    "A3,90.0,95.0\n"
    "A4,200.0,201.0\n"
)


@pytest.fixture
def state(tmp_path: Path) -> DesignerState:
    csv = tmp_path / "wide.csv"
    csv.write_text(WIDE, encoding="utf-8")
    config = ParityConfig().merge(data={"paths": (csv,)})
    return DesignerState(config=config, data=load(config.data))


def test_brushing_sets_the_x_range_and_narrows_the_view(state):
    apply_brush(state, {"range": {"x": [40.0, 100.0]}})

    assert state.filters.x_range == (40.0, 100.0)
    assert [k for k in state.visible_data().keys] == ["A2", "A3"]
    assert state.counts() == (2, 4)


def test_brushing_refreshes_every_panel(state):
    calls = []
    apply_brush(state, {"range": {"x": [0.0, 1000.0]}},
                lambda: calls.append("a"), lambda: calls.append("b"))
    assert calls == ["a", "b"]


def test_a_none_refresher_is_skipped(state):
    ran = []
    apply_brush(state, {"range": {"x": [0.0, 1.0]}}, None, lambda: ran.append(1))
    assert ran == [1]


def test_an_empty_selection_clears_the_brush(state):
    """Double-clicking to deselect must restore the full view, not freeze it."""
    apply_brush(state, {"range": {"x": [40.0, 100.0]}})
    assert state.filters.x_range is not None

    apply_brush(state, None)

    assert state.filters.x_range is None
    assert state.counts() == (4, 4)


def test_brushing_leaves_the_other_filters_alone(state):
    state.filters = FilterSet(show_unpaired=False, outside_tolerance_only=True)

    apply_brush(state, {"range": {"x": [0.0, 100.0]}})

    assert state.filters.show_unpaired is False
    assert state.filters.outside_tolerance_only is True
    assert state.filters.x_range == (0.0, 100.0)


def test_brushing_never_touches_the_config(state):
    before = state.config
    apply_brush(state, {"range": {"x": [0.0, 100.0]}})
    assert state.config == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_brush_wiring.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_brush'`

- [ ] **Step 3: Modify `parity_plot/designer/app.py`**

Add the import beside the others:

```python
from .selection import range_from_selection
```

Add this module-level function, next to `select_record`:

```python
def apply_brush(state: DesignerState, args: dict | None, *refreshers) -> None:
    """Narrow the view to the brushed x-window, or clear it when empty.

    Only `x_range` is replaced; the other switches are carried across, so
    brushing does not silently undo a "failures only" filter the user set.
    """
    state.filters = replace(state.filters, x_range=range_from_selection(args))
    for refresh in refreshers:
        if refresh is not None:
            refresh()
```

Add `replace` to the dataclasses import at the top of `app.py`:

```python
from dataclasses import replace
```

Inside `page()`, after the existing `plot_view.on("plotly_click", on_point_click)` line,
attach the two selection events:

```python
                def on_brush(event) -> None:
                    apply_brush(state, event.args, refresh)

                plot_view.on("plotly_selected", on_brush)
                plot_view.on("plotly_deselect", lambda _: apply_brush(state, None, refresh))
```

Then make box-select the default drag action so the brush is discoverable, by
adding a `dragmode` to the figure right where it is handed to the plot. In
`refresh`, change the update line to:

```python
        def refresh() -> None:
            figure = state.figure()
            figure.update_layout(dragmode="select")
            plot_view.update_figure(figure)
```

and set the same on the initial figure:

```python
                initial = state.figure()
                initial.update_layout(dragmode="select")
                plot_view = ui.plotly(initial).classes("w-full h-[55vh]")
```

Leave the rest of `refresh` (the error banner, status, inspector and table calls)
exactly as it is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_brush_wiring.py -v`
Expected: PASS, 6 tests

Then the whole suite, including
`tests/designer/test_app.py::test_the_server_actually_serves_the_page`, which boots
the real server and will catch a broken page build.

**The golden tests must still pass.** `dragmode` is set on the figure handed to the
widget, not inside `build_figure`, so the CLI's output is untouched. If a golden test
fails, you have set it in the wrong place.

- [ ] **Step 5: Stop. Do not commit.**
