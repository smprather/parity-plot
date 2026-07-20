# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Managed by [uv](https://docs.astral.sh/uv/) — no `pip`, no `requirements.txt`.

```bash
uv sync                          # runtime + dev deps
uv sync --extra static           # adds kaleido for png/svg/pdf export
uv run pytest                    # full suite
uv run pytest tests/test_data.py::test_wide_sorts_records_into_paired_and_unpaired
uv run parity-plot example       # regenerate data/ sample CSVs, plot, open browser
uv run parity-plot plot data/example.csv --no-open-browser -o out.html
```

`plot` and `example` **open the result in a browser by default**
(`--no-open-browser` to suppress), matching the sibling `time-plot` project.
`tests/conftest.py` has an autouse `no_real_browser` fixture that intercepts
`webbrowser.open`; without it the suite would spawn a window per CLI test. Use
that fixture's list to assert on open behaviour rather than patching locally.

Static image export additionally needs a headless Chrome (`uv run
plotly_get_chrome`); kaleido and the browser are separate installs and each
failure reports itself in terms of the other. `plot.py::_export_hint` exists to
untangle that — keep it accurate if the export path changes.

**Python floor is `>=3.14`**, matching the sibling `time-plot` project. Nothing in
the code needs 3.14 specifically — `tomllib` only wants 3.11 — so the floor is a
deliberate consistency choice, not a technical constraint. The completed plan
documents under `docs/superpowers/plans/` state `>=3.11`; they are historical
records of what was true when written, and this file is authoritative.

## Architecture

The pipeline is `load → compute → build_figure → save`, with `config.py`
supplying parameters at each stage.

**`data.py` is the seam.** Both input shapes — one wide CSV, or two CSVs
outer-joined on a key — collapse into a single `ParityData` struct, so nothing
downstream knows which mode was used. If you add an input format, add a loader
here and leave the rest of the pipeline alone.

**Unpaired records are the reason this tool is not fifteen lines.** A record
present in one dataset but not the other has only one coordinate and cannot be
a scatter point. It is kept in `ParityData.missing_x` / `missing_y` and rendered
as a rug mark on the axis whose value is known. Three consequences worth
remembering before changing anything:

- `stats.py` computes over paired records only. Folding unpaired values into a
  metric would be meaningless — there is no difference to measure.
- `ParityData.all_values()` includes unpaired values, because the axis range is
  built from it and a rug mark outside the range would silently vanish.
- Join mode cannot count records missing from *both* files — they leave no row
  anywhere. Wide mode reports them as `n_dropped`. This asymmetry is inherent,
  not a bug.

**The 45° invariant** needs three things, not two: both axes sharing one range,
`scaleanchor`/`scaleratio` locking the pixel scales, **and** `constrain="domain"`
on both axes. Without the third, Plotly satisfies the pixel ratio by *widening*
whichever axis has more room, so on any non-square drawing area the two axes
silently stop starting at the same value no matter what range you set.
`constrain="domain"` shrinks the plot area instead. All three are asserted in
`tests/test_plot.py`.

**Tolerances carry units and must not be conflated.** `abstol` is in the data's
own units (lines parallel to `y = x`); `reltol` is a dimensionless **ratio**
(a wedge through the origin) — `0.1` is a tenth, and percent must be written
explicitly as `10pct`, parsed by `tolerance.parse_reltol` which both the CLI
param type and the TOML coercion call. A bare `10` means ten times the reading,
never 10%. With both, the half-width is `max(abstol, reltol·|x|)` —
the *looser* spec governs, so the envelope is parallel near the origin and
flares past the crossover at `abstol/reltol`. `tolerance.py` owns all of this;
`Tolerance.vertices()` deliberately emits a point at the crossover and at the
origin so the kinks are exact rather than sampled. On a log axis the straight
segments become curves, so `log_envelope()` samples densely instead.

**Colour carries meaning here:** green is the zero-error identity line, red is
the tolerance limit, both solid. Don't swap them for palette reasons.

**Legend position is per-plot** (`PlotConfig.legend`: `right` (default) /
`bottom` / `none`), and each position carries its own margins in
`plot._LEGEND_LAYOUTS` — a right-hand legend needs width where a bottom one
needs height. `themes.py` holds only the legend's *styling*; putting position
there is what made the legend collide with the subtitle once already. `top` is
deliberately not an option for the same reason.

**Log mode passes `log` explicitly** through `_add_identity`, `_add_rugs`, and
`_add_tolerance`. It cannot be sniffed from the figure: traces are added
before `_apply_layout` sets the axis type. On a log axis the stored range is in
*exponents*, so traces need `10**value` to land in data space.

**The designer must never reimplement plotting.** `parity_plot/designer/` calls
`build_figure` for its preview. `tests/designer/test_golden_wysiwyg.py` asserts
that a config saved from the designer renders an identical figure through the
CLI path — if that test fails, the designer is lying about what the CLI will do,
and the designer is what needs fixing.

Logic lives in `state.py`, `session.py`, and `serialize.py`, all browser-free and
unit-tested; `app.py` and `panels/` only wire widgets. Anything worth testing
belongs in the pure modules. `build_app` registers the page and returns state;
`launch.run` owns `ui.run`, so they cannot double-serve.

`serialize.py` uses tomlkit rather than generating TOML, because a config meant to
be hand-edited and committed must not lose its comments on save. It skips writing
a key whose value is unchanged — but **only when the key is literally present**: a
parsed config fills absent keys with defaults, so without that guard a missing key
compares equal to the default and is never written at all.

`launch.run` loads the session **before** importing any UI, so bad input fails with
a plain message instead of after a server is already listening.

`nicegui` is an optional extra. Never import it at `parity_plot` module scope —
`designer/launch.py` imports it lazily and raises `MissingDependencyError` naming
`uv sync --extra designer`.

**Phase 2 pure modules:** `datasets.py` reads only a CSV's header and first row —
loading a large file just to list its columns makes opening one feel broken, and a
test on a 200k-row file guards that. `records.py` turns a `ParityData` into one row
per record and is shared by the inspector and (Phase 3) the table, so keep it free
of formatting and display strings.

`DesignerState.set_data_source` keeps the previously loaded dataset **and config**
when a load fails, for the same reason `figure()` keeps the last good figure. Build
the candidate and load from it first; assign only on success — assigning then
rolling back is not equivalent. It also clears a selection absent from the new data.

**`figure()` deliberately does not clear `last_error` on success.** A failed
`set_data_source` leaves the old data loaded, so the next redraw succeeds; clearing
there would blank the error banner before it ever showed. Errors are cleared by
whatever succeeds next (`update` / `set_data_source`).

Plotly click payloads carry `customdata` in **two shapes**: the paired trace carries
`(key, diff)`, the rug traces a bare key. `key_from_customdata` normalises both —
never index into it directly.

`build_inspector` takes the tolerance as a **callable**, since the user can change it
after the panel is built and the verdict must follow.

**Filters never reach the config.** `FilterSet` lives on `DesignerState`, not on
`ParityConfig`. A config encoding a temporary view would render differently from
what the CLI produces, breaking the guarantee `test_golden_wysiwyg.py` protects;
a test asserts no filter vocabulary appears in a saved TOML.

**A default `FilterSet` must be a no-op.** `figure()` renders `visible_data()`, so
an unfiltered designer that altered the data at all would fail the golden tests.
If they ever go red, suspect `filters.py` — not the golden tests.

`outside_tolerance_only` says nothing about unpaired records, which were never
judged and so cannot be outside a spec; `show_unpaired` governs those separately.
`selected_record` reads the **full** dataset, not the filtered one, so filtering
out a pinned record does not blank the inspector on what you clicked.

`table_rows.to_rows` keeps values numeric and rounds them rather than formatting
to strings: the table exists to sort by error magnitude, and strings sort
lexically so "9" lands above "100".

**Selection has exactly one owner.** Both the plot click and the table row route
through `app.select_record`; two writers would drift and leave the views
highlighting different records.

**Brushing** feeds `plotly_selected` into `FilterSet.x_range` via
`selection.range_from_selection`, which normalises Plotly's three descriptions of
a selection (box `range.x`, `lassoPoints.x`, or bare `points`) into one range. A
dragged box wins over the points inside it — an empty region still means that
region. An empty selection returns None, which is what lets `plotly_deselect`
clear the brush; do not add a guard that skips a None range.

`apply_brush` uses `dataclasses.replace` so only `x_range` changes and the other
switches survive.

**Drag is left as Plotly's default (zoom).** `dragmode="select"` was tried and
reverted — making drag brush instead of zoom felt flaky in use. The selection
handlers stay wired and brushing works from the modebar's box-select tool. If
`dragmode` is reinstated, set it on the figure handed to the widget and **never**
inside `build_figure`, which is shared with the CLI and compared against it by the
golden tests.

`selection._numbers` excludes booleans explicitly: `isinstance(True, int)` is True
in Python, so a naive numeric check reads True as 1.0 and corrupts the range.

**Testing the UI:** `nicegui.testing.plugin` imports selenium at module scope and
breaks collection for the whole suite; don't register it. The headless `user`
fixture also expects a module-level app (`nicegui_main_file`), which `build_app`
is not. `tests/designer/test_app.py` instead boots `parity-plot design` as a
subprocess and fetches the page — strip `PYTEST*` from that subprocess's env or
NiceGUI switches into screen-test mode and demands `NICEGUI_SCREEN_TEST_PORT`.

## Conventions

- **No numpy or pandas.** Workloads are small enough for stdlib `csv`, `math`,
  and `random`, and staying dependency-light means the API accepts pandas Series
  or numpy arrays anyway — they are just iterables of numbers.
- **A non-numeric, non-null cell is an error**, never a silent null. Coercing it
  would corrupt every statistic downstream. Errors name the file and line.
- **Unknown TOML keys raise.** A misspelled key that was ignored would render
  the default and look like a plotting bug.
- **R² is about the identity line**, not a least-squares fit (see README).
  Pearson *r* is reported separately. Do not "fix" this to the conventional
  formula — the distinction is the point of a parity plot.

**`examples.ExampleSpec` owns every generator knob**, validated in
`__post_init__`. Two things there are load-bearing:

- Null counts default to `None` and resolve to a *fraction of n*, so
  `generate(n=10)` works instead of failing on counts sized for n=1000.
- `_resolve` builds a spec from scratch rather than `replace`-ing a default
  one, because a default spec has already resolved its null counts against
  n=1000 and replacing `n` alone would carry them onto a tiny dataset.

## Gotchas

- rich-click ≥1.9 dropped module-level `OPTION_GROUPS`/`COMMAND_GROUPS`; this
  code uses `RichHelpConfiguration(option_groups=...)`. In those groups, flag
  pairs are matched by their **first** declaration (`--log`, not
  `--log/--no-log`) or they fall into a leftover "Options" panel.
- Both `plot` and `example` write images, so both must route their output path
  through `cli._infer_format`. Without it `-o out.png` silently writes HTML into
  a `.png` file — that bug shipped once already on `example`.
- `data/` and rendered plots are gitignored; regenerate with `parity-plot example`.
