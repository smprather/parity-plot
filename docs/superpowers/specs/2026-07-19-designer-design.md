# Interactive Designer — Design

**Date:** 2026-07-19
**Branch:** `designer`
**Status:** approved for implementation

## Context

`parity-plot` today is a CLI plus a Python API. Its behaviour is driven by ~24
settings across four config sections, expressed either as CLI flags or as a
`parity.toml`. Finding the right combination — which tolerance, which theme,
which legend position, which columns — currently means editing a file, re-running
the command, and looking at the result. That loop is slow, and it is worst
exactly where the tool is most useful: dialling in a tolerance spec against real
measurement data.

The designer closes that loop. It is a local browser application that renders the
plot live while you edit the settings, and that also lets you interrogate the
data behind the plot — which records failed spec, which are unpaired, which are
the worst offenders.

## Decisions taken during brainstorming

| Question | Decision |
| --- | --- |
| Purpose | **Both** a data explorer and a config builder |
| Explorer scope | All four: load & map columns, inspect points, filter & isolate, sortable table |
| Config flow | **Full round-trip** — open an existing `parity.toml`, edit, save back |
| Framework | **NiceGUI 3.14** (pure Python; Plotly still renders the plot) |
| Sequencing | Three phases, all specified here, built in order |

## The property that governs everything

**The designer is a config editor with a live preview, and the preview is
produced by the same code path as the CLI.**

The designer calls the existing `build_figure(data, cfg.plot, cfg.stats)`. It does
not reimplement any part of plotting, statistics, or tolerance geometry. A
setting that the designer cannot express is a setting the designer does not
offer.

This is not a convenience. Any arrangement where the preview is generated
separately allows the two to drift, and a designer whose output does not match
the CLI is worse than no designer at all — it produces configs you cannot trust.
The golden test below exists solely to pin this.

## Module layout

New package `parity_plot/designer/`. The split puts all logic in pure modules and
keeps the UI layer thin, matching the repo's existing posture — 181 tests, none
requiring a browser.

| Module | Role | Pure? |
| --- | --- | --- |
| `state.py` | `DesignerState`: config, data, filters, selection, dirty flag | yes |
| `filters.py` | Predicates over `ParityData` producing a filtered view | yes |
| `session.py` | Load/save TOML and CSV, dirty tracking, save-as | yes |
| `serialize.py` | `ParityConfig` → TOML text, comment-preserving | yes |
| `app.py` | NiceGUI assembly, routing, wiring | no |
| `panels/controls.py` | The ~24 knobs, bound to config | no |
| `panels/table.py` | Sortable table ↔ plot selection sync | no |
| `panels/inspector.py` | Detail view for the selected record | no |
| `launch.py` | `parity-plot design` subcommand | no |

If a UI panel starts to contain logic worth testing, that logic belongs in a pure
module instead.

## State model

```python
@dataclass
class DesignerState:
    config: ParityConfig          # the thing being edited and saved
    data: ParityData | None       # None until a dataset is loaded
    filters: FilterSet            # exploration only, never saved
    selection: str | None         # record key of the pinned point
    dirty: bool                   # config differs from what is on disk
```

**Filters are exploration state, not configuration.** Narrowing the view to
out-of-tolerance points changes what you see; it must never reach the saved TOML.
A config that silently encoded a temporary view would render differently from
the CLI, breaking the governing property above.

`FilterSet` is frozen and applies as a pure function:

```python
@dataclass(frozen=True)
class FilterSet:
    outside_tolerance_only: bool = False
    show_paired: bool = True
    show_unpaired: bool = True
    x_range: tuple[float, float] | None = None      # brush selection

    def apply(self, data: ParityData, tol: Tolerance) -> ParityData: ...
```

`apply` returns a new `ParityData`. Because everything downstream already
consumes that struct, filtering needs no changes to `plot.py` or `stats.py`, and
the statistics box recomputes against the filtered view for free.

One subtlety to honour: filtering must preserve the paired/unpaired/dropped
distinction. Hiding unpaired records is a filter; silently converting them into
paired records is a bug.

## Data flow

```
CSV ──load()──┐
              ├──► DesignerState ──► filters.apply() ──► build_figure() ──► ui.plotly
TOML ─────────┘         ▲   │                 │
                        │   │                 └──────────► rows ──► ui.table
                        │   │                                          │
                   controls └──────────── selection ◄───────────────────┘
                        │
                   save ▼
                   parity.toml
```

## Phase 1 — Skeleton

The config-builder half, complete and independently useful.

**Launch.** `parity-plot design [PATHS...] [-c CONFIG]`, mirroring `plot`'s
argument shape: zero paths reads from config, one is wide mode, two is join mode.
Starts a local NiceGUI server and opens a browser, honouring the existing
`--open-browser/--no-open-browser` convention and defaulting to open. `--port`
with an automatic fallback when the port is taken.

**Live preview.** `ui.plotly` fed directly from `build_figure`. Every control
change rebuilds the figure. At n=1000 a full rebuild is a few milliseconds, so no
incremental-update machinery is warranted; if a dataset ever makes this slow, the
fix is debouncing the control events, not partial figure mutation.

**Controls.** Every field of `PlotConfig`, `StatsConfig`, and `OutputConfig`,
grouped as the CLI groups them (Appearance / Tolerances / Output). Each control
writes through `ParityConfig.merge`, so the designer gets the same validation and
the same error messages as the TOML and CLI paths.

`DataConfig` is deliberately **not** editable in this phase — the dataset comes
from the launch arguments and stays fixed for the session. In-UI file loading and
column mapping arrive in Phase 2. A `DataConfig` loaded from TOML is preserved
untouched through save, so round-tripping a config never drops its `[data]`
section.

Tolerance inputs accept the same spellings as the CLI: `--reltol` takes a ratio
or an explicit `10pct`, parsed by the existing `tolerance.parse_reltol`. The
designer must not invent a percent-only spinner — the whole point of that
parsing rule is that the unit is stated, not inferred.

**Save.** Save and Save-As to TOML, with a dirty indicator. Saving over a file
that changed on disk since load prompts rather than clobbering.

### TOML writing needs a real serializer

`config.py` currently only *reads* TOML; `tomllib` is read-only by design. Saving
therefore needs new code, and there is a trap in it: a naive writer regenerates
the file and destroys any comments the user wrote. This config is meant to be
hand-edited and committed, so losing comments on every save is not acceptable.

`serialize.py` therefore uses **tomlkit**, which round-trips comments and
formatting, updating values in place in an existing document. When no file exists
yet, it generates a fresh document modelled on `config.EXAMPLE_TOML`, comments
included.

Required test: load a TOML containing comments, change one value through the
designer, save, and assert both that the value changed and that every comment
survived.

## Phase 2 — Explorer

**File loading and column mapping.** Open a CSV from the UI, read its headers,
and choose which column is reference / measured / key, plus wide vs join mode.
Until this exists the tool only works on data already shaped like the example.

Header reading must not load the whole file — a peek at the header row is enough,
and `data.py`'s existing error messages already name the file and line when a
column is missing.

**Point inspection.** Hover comes nearly free: `plot.py` already sets a
`hovertemplate` carrying key, both values, and the signed difference. The work is
click-to-pin plus a detail panel showing the record, its error, and whether it
passes the current tolerance (`Tolerance.contains`).

Plotly click events carry `customdata`, which the paired trace already populates
with `(key, diff)`. The rug traces carry their keys too. So selection maps back
to a record without maintaining a parallel index.

## Phase 3 — Triage

**Sortable table.** `ui.table` beside the plot, one row per record: key, x, y,
signed error, relative error, status (paired / missing x / missing y / outside
tolerance). Sortable by any column — sorting by absolute error is the "which
parts failed worst" question, and is the reason this phase exists.

**Bidirectional selection.** Clicking a plot point selects its table row and vice
versa. Both write to the single `DesignerState.selection`; neither owns it.

**Filters.** Out-of-tolerance only, unpaired only, and brush-to-x-range, as
described in the state model. Filter state shows a clear "showing 14 of 1,000"
indicator, because a filtered plot that looks unfiltered is a trap.

## Error handling

The server must survive every one of these without dying:

| Situation | Behaviour |
| --- | --- |
| Malformed CSV (`DataError`) | Message in the UI naming file and line; keep the previous dataset loaded |
| Invalid setting (`ConfigError`) | Inline error on that field; keep the last good figure on screen |
| Config file changed on disk since load | Prompt before overwriting; offer save-as |
| Port already in use | Try the next free port and report which one was used |
| Static export without kaleido/Chrome | Reuse `plot._export_hint`'s existing message rather than a new one |

The rule throughout: an invalid input never blanks the plot. The last good figure
stays until a valid one replaces it.

## Testing

Pure modules (`state`, `filters`, `session`, `serialize`) get ordinary pytest
coverage and need no browser. UI wiring uses `nicegui.testing`'s headless `User`
fixture.

**The golden test**, worth more than the rest combined:

> Build a config in `DesignerState`, save it to TOML, load that TOML through the
> normal `ParityConfig.from_toml` path, render with the CLI's `build_figure`, and
> assert the resulting figure is identical to the designer's preview figure.

That is the WYSIWYG guarantee stated executably. If it ever fails, the designer
is lying about what the CLI will do.

Specific cases worth naming:

- Filters never alter the saved TOML (save with filters active, reload, compare).
- Filtering preserves paired/unpaired classification.
- Comment preservation across save (above).
- Statistics recompute against the filtered view, not the full dataset.
- A `ConfigError` leaves the previous figure intact.

## Packaging

`nicegui` and `tomlkit` go in as an optional extra so the plotting CLI stays
light:

```toml
[project.optional-dependencies]
designer = ["nicegui>=3.14", "tomlkit>=0.13"]
```

`uv sync --extra designer`. Invoking `parity-plot design` without the extra
installed fails with an actionable message naming that command — the same pattern
`plot._export_hint` already uses for kaleido.

## Out of scope

- Multi-user or hosted deployment. This is a local, single-user tool; no auth,
  no session isolation, no concurrent editors.
- Editing or excluding individual data points. The designer reads data; it does
  not write it.
- Comparing more than two datasets at once.
- Any plotting capability that the CLI does not already have. New plot features
  belong in `plot.py`, reached by both.
