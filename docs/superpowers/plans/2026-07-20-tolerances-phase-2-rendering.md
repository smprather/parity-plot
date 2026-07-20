# Tolerances Phase 2 (Rendering & Verdicts) Implementation Plan

> **For agentic workers:** Implement one task only, as fenced in your prompt.

**Goal:** Teach every consumer to read the tolerance list, add the built-in parity entry, and clear all 103 xfails.

**Definition of done:** `docs/superpowers/plans/xfail-inventory-phase1.txt` is empty and `parity-plot design` serves a page again.

## Global Constraints

- **Never reimplement geometry.** `NamedTolerance.tolerance` → `Tolerance`; all math stays in `tolerance.py`.
- **`name` is an identifier, `label` is display text.** Nothing keys off a label.
- **Informational tolerances are never judged.** Only `kind="pass"` entries can be failed.
- **Un-xfail as you go.** Every test you make pass must have its `@_DESIGNER_READS_THE_LIST` / `xfail` / `skip` marker removed in the same task. A test that passes while still marked xfail reports as `XPASS` and is worse than useless.
- **No numpy or pandas.** Frozen dataclasses; never `object.__setattr__`.
- Python 3.14 floor. Pure modules import neither nicegui nor plotly.

---

### Task 1: Parity entry, `enabled`, `show_in_legend`

Implement **Task 4 of the Phase 1 plan** (`2026-07-20-tolerances-phase-1-model.md`), verbatim — it contains the complete test file and all edits. It adds three fields, the `parity()` / `with_parity()` / `draw_order()` helpers, retires `identity_line`, and makes the parity entry the default first element.

Files: `parity_plot/tolerances.py`, `parity_plot/config.py`, `tests/test_parity_entry.py`.

Nothing else in this phase can start until this lands.

---

### Task 2: `plot.py` renders the list

**Files:** `parity_plot/plot.py`; un-xfail in `tests/test_plot.py`

**Key simplification:** delete `_add_identity` entirely. The parity entry is a tolerance
with no bounds, so `Tolerance().half_width()` is zero everywhere and its envelope collapses
onto `y = x`. One rendering path serves everything.

- [ ] **Step 1: Rewrite `_add_tolerance` as a loop**

```python
def _add_tolerances(
    fig: go.Figure,
    tolerances: Sequence[NamedTolerance],
    lo: float,
    hi: float,
    log: bool,
    theme: themes.Theme,
) -> None:
    """Draw every enabled tolerance, parity last so nothing buries it."""
    for tol in draw_order(tolerances):
        _add_one_tolerance(fig, tol, lo, hi, log, theme)


def _add_one_tolerance(fig, tol, lo, hi, log, theme) -> None:
    geometry = tol.tolerance
    if log:
        xs, upper, lower = geometry.log_envelope(lo, hi)
    else:
        xs, upper, lower = geometry.envelope(lo, hi)
    if not xs:
        return

    colour = theme.resolve_color(tol.color_token)
    shaded = tol.style == "shaded"
    line = dict(color=colour, width=2 if tol.builtin else 1.6)

    # A zero-width tolerance (the parity line) has upper == lower, so drawing
    # both would stack two identical traces and double the legend entry.
    if upper == lower:
        fig.add_trace(go.Scatter(
            x=xs, y=upper, mode="lines", name=tol.display_label,
            line=line, showlegend=tol.show_in_legend, hoverinfo="skip",
        ))
        return

    fig.add_trace(go.Scatter(
        x=xs, y=lower, mode="lines", name=tol.display_label,
        legendgroup=tol.name,
        line=dict(width=0) if shaded else line,
        showlegend=tol.show_in_legend and not shaded,
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=xs, y=upper, mode="lines", name=tol.display_label,
        legendgroup=tol.name,
        line=dict(width=0) if shaded else line,
        fill="tonexty" if shaded else None,
        fillcolor=theme.band_fill_for(tol.color_token) if shaded else None,
        showlegend=tol.show_in_legend and shaded,
        hoverinfo="skip",
    ))
```

- [ ] **Step 2: Update `build_figure`**

Replace the `tol = Tolerance(...)` / `if tol:` / `_add_identity` block with:

```python
    summary = stats_mod.compute(data, plot.tolerances)
    lo, hi = _axis_range(data, log=plot.log)

    fig = go.Figure()
    _add_tolerances(fig, plot.tolerances, lo, hi, plot.log, theme)
    _add_paired(fig, data, plot.tolerances, theme)
```

Delete `_add_identity` and its `_line_endpoints` helper if nothing else uses it. Remove
`plot.identity_line` handling — the parity entry's `enabled` replaces it.

- [ ] **Step 3: Hover carries the verdict**

In `_add_paired`, take `tolerances` and extend `customdata`:

```python
    verdicts = [verdict_text(failures(tolerances, xi, yi)) for xi, yi in zip(data.x, data.y)]
    ...
        customdata=list(zip(data.keys, diffs, verdicts)),
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            f"{data.x_label}: %{{x:.4g}}<br>"
            f"{data.y_label}: %{{y:.4g}}<br>"
            "difference: %{customdata[1]:+.4g}<br>"
            "%{customdata[2]}<extra></extra>"
        ),
```

`key_from_customdata` takes index 0, so click handling is unaffected — verify that test
still passes.

- [ ] **Step 4: Un-xfail `tests/test_plot.py`**

Remove every xfail marker there, rewriting assertions to the list shape. Trace counts
change: each tolerance contributes one trace (zero-width) or two (banded), and the identity
line is now the parity entry named by its label.

- [ ] **Step 5: Report** which tests you un-xfailed and any you could not.

---

### Task 3: `stats.py` reports per tolerance

**Files:** `parity_plot/stats.py`; un-xfail in `tests/test_stats.py`

- [ ] **Step 1: Change the shape**

```python
    within: dict[str, float] = field(default_factory=dict)   # name -> fraction
```

Delete `tolerance_label`. `compute(data, tolerances)` takes the list and fills `within` for
**pass/fail entries only** — info entries are references, not criteria.

```python
        within={
            tol.name: _within(x, y, tol) for tol in pass_fail(tolerances)
        } if len(x) >= 2 else {},
```

with `_within` taking a `NamedTolerance` and using `tol.contains`.

- [ ] **Step 2: `format_lines` emits one row per criterion**

```python
    for name, share in stats.within.items():
        lines.append(f"within {name}: {share:.1%}")
```

- [ ] **Step 3: Un-xfail `tests/test_stats.py`** and report.

---

### Task 4: Designer verdicts

**Files:** `parity_plot/designer/records.py`, `table_rows.py`, `filters.py`, `state.py`,
`inspector_helpers.py`, `panels/controls.py`; un-xfail across `tests/designer/`

- [ ] **Step 1: `RecordView.within` becomes `failed`**

```python
    failed: tuple[str, ...] | None = None   # None when unpaired or no criteria
```

`record_views(data, tolerances)` computes `failures(tolerances, x, y)` for paired records,
`None` for unpaired. Add `verdict` as a property returning `verdict_text(self.failed)` or
`""` when `failed is None`.

- [ ] **Step 2: `table_rows`** — the verdict column shows `row["verdict"]`, blank for unpaired.

- [ ] **Step 3: `filters`** — `outside_tolerance_only` keeps paired records where
`failures(tolerances, x, y)` is non-empty. `FilterSet.apply(data, tolerances)` now takes the
list. **A default `FilterSet` must remain inert** — the golden tests depend on it.

- [ ] **Step 4: `state`** — `tolerance()` becomes `tolerances()` returning
`self.config.plot.tolerances`. Update `visible_data`, `visible_records`, `selected_record`.

- [ ] **Step 5: `inspector_helpers.describe`** — replace the single `Tolerance` row with one
row per pass/fail entry, or a single `Verdict: pass`.

- [ ] **Step 6: `panels/controls.py`** — remove the `abstol`, `reltol` and `band_style`
specs from `CONTROL_SPECS`, and the `identity_line` spec. This is what currently makes the
designer return 500. The list UI replacing them is Phase 3; leaving the specs pointing at
deleted fields is not an option.

- [ ] **Step 7: Un-xfail everything under `tests/designer/`** and report anything left.

---

### Task 5: `serialize.py` writes the tolerance list

Missed in the original plan and surfaced by Task 1: `config_to_toml` iterates dataclass
fields and writes scalars, but `tolerances` is a tuple of `NamedTolerance` objects that
must become a `[[plot.tolerances]]` array-of-tables. The parity default means *every* save
now hits this, which is why four `designer/test_serialize.py` tests and the golden suite
are xfailed on it.

**Files:** `parity_plot/designer/serialize.py`; un-xfail `tests/designer/test_serialize.py`
and any golden test parked with `_SERIALIZER_READS_THE_LIST`.

- [ ] **Step 1** — In `config_to_toml`, special-case the `tolerances` field. For each
`NamedTolerance`, emit a `[[plot.tolerances]]` table via `tomlkit.aot()` / `tomlkit.table()`,
writing only the fields that differ from the `NamedTolerance` defaults (so a plain entry
stays terse), and always writing `name`. The parity entry, when it is the default
unmodified one, may be omitted entirely — `with_parity` re-adds it on load, so a config
need not carry it unless the user customised it. Round-tripping must still satisfy the
existing "comment preservation" and "unchanged values keep their spelling" tests.

- [ ] **Step 2** — Un-xfail the serializer and golden tests, rewrite expectations to the
list shape, and report.

- [ ] **Step 3** — The golden guarantee (`test_golden_wysiwyg`) is the real check here:
save a multi-tolerance config from the designer, reload through `from_toml`, render through
the CLI, assert identical. It can only pass once both `plot.py` (Task 2) and this are done.

---

## Verification (orchestrator)

```bash
uv run pytest -q                     # zero xfailed, zero xpassed
wc -l docs/superpowers/plans/xfail-inventory-phase1.txt   # must be 0
uv run parity-plot plot data/example.csv -o out/p2.png --width 850 --height 850
uv run parity-plot design data/example.csv --port 8111 --no-open-browser   # 200, not 500
```
