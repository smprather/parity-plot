# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Managed by [uv](https://docs.astral.sh/uv/) — no `pip`, no `requirements.txt`.

```bash
uv sync                          # runtime + dev deps (designer included)
./check-tier-1                   # normal change: fast lint/types/smoke gate
./check-tier-2                   # release or explicit request only
uv run pytest                    # raw full suite, when diagnosing
uv run pytest tests/test_data.py::test_wide_sorts_records_into_paired_and_unpaired
uv run parity-plot example       # regenerate data/ sample CSVs, plot, open browser
uv run parity-plot init          # write a documented parity.toml
uv run parity-plot plot parity.toml --no-open-browser -o out.html   # CONFIG is positional
uv run parity-plot design --config parity.toml --no-open-browser
./run-check                      # designer against data/parts.csv
```

### Shared demo server

Port **8085** is reserved exclusively for the parity-plot demo. Always serve the
working demo at `http://localhost:8085` so the user can reload one stable URL.
Before starting or restarting it, stop the existing 8085 listener; the user has
explicitly authorized killing any unrelated process holding that port, using
`sudo` when required. Do not accept the launcher's fallback to a random port for
demo runs.

### Running uv in a filesystem sandbox

Managed agent sandboxes often expose the home directory as read-only while the
workspace and `/tmp` remain writable. uv normally locks and creates temporary
files under `~/.cache/uv`, so a command may fail before it runs with:

```text
error: Could not acquire lock
Caused by: Could not create temporary file
Caused by: Read-only file system ... /home/.../.cache/uv/.tmp...
```

Do not retry the identical command. Point uv at a writable cache **on every tool
call** (exec calls do not preserve exported environment variables):

```bash
UV_CACHE_DIR=/tmp/parity-plot-uv-cache uv run pytest
UV_CACHE_DIR=/tmp/parity-plot-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/parity-plot-uv-cache uv sync
```

If `.venv` is already synced and no dependency operation is needed, bypass uv
entirely; this is faster and avoids its cache lock:

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ty check parity_plot
.venv/bin/parity-plot --help
```

Cache writability and network access are separate failures. `UV_CACHE_DIR` fixes
the read-only-cache error. If uv then needs to download a missing package and the
sandbox blocks DNS/network, rerun that specific uv command with the environment's
network/escalation mechanism. Never work around either failure with `pip` or by
creating a second environment.

`./check-tier-1` performs the same writable-cache fallback automatically and can
run inside the filesystem sandbox. Tier 2 contains a real-server integration
test which binds a temporary localhost port. Sandboxes that deny socket creation
must run `./check-tier-2` through their escalation/localhost-permission mechanism;
changing `UV_CACHE_DIR` cannot grant socket access.

Executable names are kebab-case (`parity-plot`, `build-report`, `run-check`).
Python modules and import paths stay snake_case.

`plot` and `example` **open the result in a browser by default**
(`--no-open-browser` to suppress), matching the sibling `time-plot` project.
`tests/conftest.py` has an autouse `no_real_browser` fixture that intercepts
`webbrowser.open`; without it the suite would spawn a window per CLI test. Use
that fixture's list to assert on open behaviour rather than patching locally.

Static image export needs a headless Chrome (`uv run plotly_get_chrome`).
kaleido itself is a required dependency, so the browser is the only piece that
actually goes missing — but kaleido's own error reports itself in terms of the
other, which would send people to reinstall what they already have.
`plot.py::_export_hint` untangles that; keep it accurate if the export path
changes.

## Two-tier checks

**Tier 1 is the normal change gate.** Run `./check-tier-1` before every commit.
It runs Ruff lint, Ruff format-check, ty, and eight stable smoke tests spanning
config, data loading, plot geometry, public API, fragments, polynomial overlays,
CLI rendering, and designer state. Keep it quick; do not grow it into the full
suite.

**Tier 2 is the release gate.** Run `./check-tier-2` only for a release or when
the user explicitly requests it. It includes Tier 1, then runs the full test
suite, builds sdist/wheel artifacts, installs and smokes the wheel in an isolated
uv environment, and builds the documented tabbed-report consumer.

GitHub Actions mirrors this policy in `.github/workflows/checks.yml`: Tier 1 on
pull requests and `main`; Tier 2 only on `v*` tag pushes or a manual workflow run
whose `tier` input is `tier-2`. `tests/test_check_tiers.py` pins the executable
scripts and routing conditions.

Raw commands remain useful when diagnosing one layer:

```bash
uv run ruff check .          # lint (E/F/I); must print "All checks passed!"
uv run ruff format .         # formatter; keeps the tree formatted
uv run ty check parity_plot  # type-check the shipped library; must be 0 diagnostics
uv run pytest                # full suite
```

Config is in `pyproject.toml`:
- **ruff lint** selects `E`/`F`/`I`. `E501` (line length) is owned by `ruff
  format`, so it is ignored. **`C408` is deliberately not selected** — the
  plotly-heavy code uses `dict(...)` as a readable idiom; rewriting to `{...}`
  literals would be a regression.
- **ty is scoped to `parity_plot/`** (`[tool.ty.src] exclude = ["tests"]`): the
  shipped library is type-checked strictly, but the tests introspect
  plotly/nicegui objects (`fig.data[i].marker.*`) no checker can resolve, so they
  are held to ruff only.
- Prefer a real fix (Optional narrowing, a proper annotation) over a waiver. When
  a diagnostic is unavoidable third-party / `**kwargs`-into-dataclass noise, waive
  it with **`# ty: ignore[<rule>]`** — ty does *not* honour the mypy `# type:
  ignore`, so use ty's own comment.

**Python floor is `>=3.14`**, matching the sibling `time-plot` project. Nothing in
the code needs 3.14 specifically — `tomllib` only wants 3.11 — so the floor is a
deliberate consistency choice, not a technical constraint. The completed plan
documents under `docs/superpowers/plans/` state `>=3.11`; they are historical
records of what was true when written, and this file is authoritative.

## Architecture

The pipeline is `load → compute → build_figure → save`, with `config.py`
supplying parameters at each stage.

**`data.py` is the seam.** `sources.py` opens N files and resolves a
`file:column` reference against them (`numeric_columns` filters ref/test to the
numeric ones — they are the axes; join/group take any column, compared as raw
strings). `data.py`'s `load` picks ref and test columns, then aligns them: with
a `join` column it outer-joins the two files on the key; without one it pairs by
row position and leaves the longer column's tail unpaired. Both former modes —
one wide file, two joined files — are special cases of this one path; there is no
dispatch on file count. Everything collapses into one `ParityData` struct carrying
the paired axes plus optional aligned group, colour and hover channels, so nothing
downstream knows how it was loaded. `ParityData.select_paired(indices)` is the one
owner of slicing those aligned channels; filters and log-mode cleanup must use it
rather than slicing fields independently. `sources` imports helpers from `data`,
so `data.load` imports
`open_sources` **lazily** to break the cycle.

**Group is file-independent, bare column names — not `file:column` — and a
*tuple* (composite).** `DataConfig.group` is `tuple[str, ...]`, normalised from
`None`/`str`/`list` in `__post_init__`. A group labels the joined *entity* (a
part), not a per-file measurement, so it may live in one file or several.
`data._group_lookup(src, groups, join, na)` composes per-column resolvers
(`_one_group_lookup`, the old single-column body) and joins their values with
`", "` — `"SMD, Acme"`; a blank slot is `"(none)"`, all-blank is `None`. Each
column is resolved via `Sources.files_with_column`, keying by the join value (or
row index when pairing by order); when 2+ files carry a column `_agree` checks the
values match and raises naming the record. A group column needs to exist in only
one file, but with joined data **every file that carries that selected column must
also carry the join column**; otherwise its values cannot vote and `load` raises
instead of silently ignoring the file. `_values_by_key` enforces unique join keys
for axis, group and pinned colour data.

**`color_column` is the colorscale channel's data — a single pinned `file:column`
numeric ref** (`DataConfig.color_column`, unlike `group` it names one file, since
the same column can differ between ref and test files). `data._color_lookup`
resolves it (no cross-file `_agree`) into `ParityData.color_values`
(`list[float|None]|None`, aligned to paired points, `None` if unset or all-blank)
plus `color_label` (the colorbar title). `_drop_non_positive` re-slices
all paired channels through `ParityData.select_paired` in log mode.

**`hover_columns` is the hover box's extra rows — pinned `file:column` refs, and
tri-state.** `DataConfig.hover_columns` is `tuple[str, ...] | None`: `None` (an
absent key) means **auto** — every candidate column — `()` suppresses, a tuple
pins that set in order. Do **not** normalise `None` to `()` in `__post_init__`;
the three states are the feature. Auto is resolved in `load`, never stored, so it
follows a ref/test change instead of going stale — which is also why the designer
writes nothing for it (`serialize` deletes a `None`-valued key) and why
`DesignerState.set_data_source` needs `clear=` (`merge` drops `None` overrides by
design, and here `None` is the meaningful value).

**Candidates** = every column of the *ref file and test file* only, minus ref,
test and join — the hover already shows those three as the x row, the y row and
the bold key line, so they are never offered, not merely off by default. Axis
exclusion is **per file**: a column sharing the other file's axis name is a
different measurement and stays offered. `data.hover_candidates` is public
because the designer's picker must use the same list — deriving it twice is how
picker and renderer drift apart. `hover_labels_for` gives the shortest
unambiguous label (bare name; `file:col` only when a bare name repeats, prefixed
with `Path.name`). `_hover_lookup` mirrors `_color_lookup` — pinned per file, no
`_agree`. Cells are **raw stripped text**, nulls an em dash; per-column float
formatting needs a schema and is deferred (see the spec's Future work).

`customdata` is `(key, diff, verdict, *hover)`, so hover rows start at index 3
and `key_from_customdata` (index 0) is unaffected. `load` checks the join column
in both axis files up front: `_index_by_key` enforced it already, but that runs
after the per-point lookups are built, so an auto-hover column from the same file
would otherwise report a missing join key in the hover channel's language.

**Marker encoding** (`encoding.py`, pure) partitions paired points into traces by
their `(colour-key, symbol-key)`. Channels split: `COLOR_CHANNELS = single |
pass-fail | group | colorscale`, `SYMBOL_CHANNELS = single | pass-fail | group`
(`CHANNELS` is a back-compat alias of the symbol set). Under `colorscale`,
`color_key_of` returns the **constant** `"colorscale"` so colour does **not**
split traces (colour is per-point, shown by a colorbar) — only the symbol channel
partitions; and `_channel_label` returns `None` for it so a trace is named for its
symbol group alone (`BGA`, never `colorscale · BGA`). It is theme-free: keys are
tokens / `pass`/`fail` / group values / symbol names, and `plot._resolve_colours`
turns colour keys into real colours via the theme. The default (single blue
circle) is one trace, keeping the golden test behaviour-preserving.

**Colour and symbol resolution are symmetric.** For the group channel both
`color_key_of` and `symbol_key_of` emit the **group value** (not a resolved
colour/glyph); `plot._resolve_colours` maps group→colour via the theme palette
and `plot._resolve_symbols` maps group→symbol via `Encoding.symbol_sequence`
(or `encoding.DEFAULT_SYMBOLS`), both in first-seen order. Emitting the group
*value* as the symbol key — rather than the glyph — is what lets a trace be named
`pass · inductor` instead of `pass · square` when `color_by=pass-fail,
symbol_by=group`. Symbols live in `encoding.py`, not `themes.py`: a symbol is
theme-independent. `DEFAULT_SYMBOLS` is the fallback cycle, `SYMBOL_CATALOG`
backs the designer pickers, and `Encoding.__post_init__` validates every symbol
(the single one and each `symbol_sequence` entry) against `_BASE_SYMBOLS` after
stripping a `-open`/`-dot`/`-open-dot` variant suffix — a typo raises, it does
not render blank. `symbol_sequence` is normalised list→tuple so the frozen
dataclass stays hashable; the tomlkit encoder writes it only when non-empty.

**Unpaired records are the reason this tool is not fifteen lines.** A record
present in one dataset but not the other has only one coordinate and cannot be
a scatter point. It is kept in `ParityData.missing_x` / `missing_y` and rendered
as a rug mark on the axis whose value is known. Three consequences worth
remembering before changing anything:

- `stats.py` computes over paired records only. Folding unpaired values into a
  metric would be meaningless — there is no difference to measure.
- `ParityData.all_values()` includes unpaired values, because the axis range is
  built from it and a rug mark outside the range would silently vanish.
- Join alignment cannot count records missing from *both* files — they leave no row
  anywhere; pair-by-order reports them as `n_dropped`. This asymmetry is inherent,
  not a bug.

**The 45° invariant** needs three things, not two: both axes sharing one range,
`scaleanchor`/`scaleratio` locking the pixel scales, **and** `constrain="domain"`
on both axes. Without the third, Plotly satisfies the pixel ratio by *widening*
whichever axis has more room, so on any non-square drawing area the two axes
silently stop starting at the same value no matter what range you set.
`constrain="domain"` shrinks the plot area instead. All three are asserted in
`tests/test_plot.py`.

**A plot carries a *list* of named tolerances**, `PlotConfig.tolerances`. Two
layers: `tolerance.Tolerance` (singular) owns all the geometry — `half_width`,
`contains`, `label`, `envelope`, `log_envelope`, the `max(abstol, reltol·|x|)`
rule; `tolerances.NamedTolerance` wraps one with a name, kind, colour, style and
label. **Never reimplement the geometry** — `NamedTolerance.tolerance` delegates.

- `abstol` is in the data's own units (lines parallel to `y = x`); `reltol` is a
  dimensionless **ratio** (a wedge through the origin). `0.1` is a tenth, percent
  is `10pct`, a bare `10` is ten times the reading. `tolerance.parse_reltol` is
  the one parser, used by the CLI, the TOML coercion and the designer.
- `name` is a stable identifier, `label` is display text (may auto-follow the
  spec) — nothing keys off a label, so it is free to change.
- `kind="info"` tolerances are drawn but never judged; only `pass` entries can
  be failed. `failures()` / `verdict_text()` produce the per-record verdict.
- The **parity line is the first, built-in entry** (`tolerances.parity()`): a
  zero-width tolerance whose envelope collapses onto `y = x`. `builtin=True`
  relaxes the "needs a bound" rule for it alone. `with_parity()` guarantees it
  leads the list preserving customisation; `draw_order()` paints it **last** so
  no shaded band buries it. It replaced the old `_add_identity` and
  `identity_line` flag entirely.

**Colour is a per-theme token**, resolved by `Theme.resolve_color`. Tokens are
curated to sit apart from the three reserved shades — `identity` (green markers
the y=x line), `marker` (blue points), `rug` (amber ticks). Hex passes through.
Default: red for pass/fail, yellow for info.

**Legend position is per-plot** (`PlotConfig.legend`: `right` (default) /
`bottom` / `none`), and each position carries its own margins in
`plot._LEGEND_LAYOUTS` — a right-hand legend needs width where a bottom one
needs height. `themes.py` holds only the legend's *styling*; putting position
there is what made the legend collide with the subtitle once already. `top` is
deliberately not an option for the same reason.

**Polynomial reference lines are presentation-only overlays.**
`PlotConfig.polynomial_lines` carries repeatable `PolynomialLine` values whose
coefficients run highest-degree first. `polynomial_lines.py` owns CSV parsing,
finite-value validation, round-trippable coefficient text, Horner evaluation and
equation labels; `plot.py` only samples them over the visible x range. Equation
labels omit zero terms, preserve stored float precision, and use `y = 0` for an
all-zero polynomial. They never affect tolerance verdicts or statistics.
Polynomial lines never alter the viewport. Optional `PlotConfig.x_origin` and
`y_origin` replace the automatic lower bounds. Origins are stored in data units,
and `_viewport_range` converts them to exponents for log layout. Log origins
must be positive. With equal axes enabled, `_equalize_range_spans` extends upper
bounds as needed; never move a requested lower bound to satisfy `scaleanchor`.

**Log mode passes `log` explicitly** through `_add_polynomial_lines`, `_add_rugs`,
and `_add_tolerance`. It cannot be sniffed from the figure: traces are added
before `_apply_layout` sets the axis type. On a log axis the stored range is in
*exponents*, so traces need `10**value` to land in data space.

**The designer must never reimplement plotting.** `parity_plot/designer/` calls
`build_figure` for its preview. `tests/designer/test_golden_wysiwyg.py` asserts
that a config saved from the designer renders an identical figure through the
CLI path — if that test fails, the designer is lying about what the CLI will do,
and the designer is what needs fixing.

**The designer page has two independent scroll regions.** `app.py` anchors
`.nicegui-content` inside Quasar's dynamically sized page, then applies
`SETTINGS_COLUMN_CLASSES` and `RESULTS_COLUMN_CLASSES`. Do not return to one
document scrollbar: a long settings column must not move the plot out of view.
`RESPONSIVE_LAYOUT_CSS` stacks results above settings below 768 px; preserve
that narrow-screen access when changing the workspace layout.

**Viewport-origin UI is one composite control.** `controls.py` maps the
horizontal Method radio (`Auto`, `0,0`, `Custom`) onto the persisted
`x_origin`/`y_origin` pair. Custom X/Y inputs start from the figure's actual
lower bounds; `current_viewport_origins` converts Plotly log exponents back to
data units. Keep both fields together and after the Method selector. Equal-axis
layout anchors x to y; reversing that `scaleanchor` direction makes Plotly
silently move one custom origin when their ranges differ. NiceGUI refreshes
through `Plotly.react`, which can retain old constrained ranges; `refresh`
therefore schedules `axis_range_relayout_script` after each figure update.

Logic lives in `state.py`, `session.py`, `serialize.py`, and `validation.py`, all
browser-free and unit-tested; `app.py` and `panels/` only wire widgets. Anything
worth testing belongs in the pure modules. `build_app` registers the page and
returns state; `launch.run` owns `ui.run`, so they cannot double-serve.

**The designer auto-saves.** `app.refresh()` is the single point that, after every
change, rebuilds the figure, computes `validation.problems(config)`, paints the
status bar, enables/disables **Save As**, marks the offending field, and — when
nothing is wrong and a file is **bound** — writes via `Session.autosave`. So a
*bound* config's file on disk always equals the **most recent valid** config; a
hard-invalid edit is withheld (disk keeps the last good one) until fixed. There is
no plain Save button. Persistence is a **top toolbar**: a config dropdown
(`session.config_choices(dir)` lists parity `.toml`s in the launch dir — touchstone:
parses + non-empty `data.files`), **Save As**, **New Design**. `<unsaved>` in the
dropdown means *unbound* — a New Design or data-only launch with no file yet; Save
As binds it. `session.config_choice_names` also inserts the currently bound config
when it lives outside the launch directory; omitting it makes NiceGUI reject the
select's current value and return HTTP 500. The settings column is a
`@ui.refreshable` rebuilt on a config swap
(`state.load_session_config`), while the plot/selection on the right persist. The
only confirm-dialog left guards leaving an *unbound-with-edits* state. The
**stale-file guard is retired** — the designer owns the open file; concurrent
external edits are overwritten (bidirectional editing is a deferred non-goal).

**`validation.py` is browser-free cross-field validation** (`problems(config) ->
list[Problem]`, each with a dotted `field` id and a `severity`). **`severity`:
`"error"` blocks — withholds auto-save, disables Save As, reddens the field (the
data panel returns a `mark_problems` hook that `app.refresh` calls with the
*error*-severity problems only, today marking `data.join`); `"warning"` is advisory
— an amber status note, nothing blocked.** The only rule so far is a **warning**:
ref and test from the **same file** while a `join` is set. That is redundant, not
wrong — a wide file's ref/test share a row, so a join re-pairs the same rows to the
same result (it only adds duplicate-key checking), so it must not block. (An earlier
version made this a hard error; corrected — don't reintroduce it as blocking.)

**Clearing a text control reverts to the field's default**, via
`state.reset_fields` — *not* `merge`, which drops `None` and so silently keeps the
stale value (the old "blank falls back to default" comment in `controls` was wrong).
`x_label`/`y_label` show the resolved column name as a dimmed placeholder
(`controls._placeholder`).

`serialize.py` uses tomlkit rather than generating TOML, because a config meant to
be hand-edited and committed must not lose its comments on save. It skips writing
a key whose value is unchanged — but **only when the key is literally present**: a
parsed config fills absent keys with defaults, so without that guard a missing key
compares equal to the default and is never written at all.

`launch.run` loads the session **before** importing any UI, so bad input fails with
a plain message instead of after a server is already listening.

`nicegui` is a core dependency now, but is still imported lazily inside
`designer/` functions, never at `parity_plot` module scope — the plotting CLI
does not pull in the UI stack at import time. `designer/launch.py` keeps its
`MissingDependencyError` guard as a safety net.

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
there would blank the status bar before it ever showed. Errors are cleared by
whatever succeeds next (`update` / `set_data_source`).

**Errors surface in a persistent status bar, never a toast.** `app.py` owns a
colour-coded `status_bar` under the plot; `refresh()` paints it red (`⛔`) from
`state.last_error`, or neutral "Ready" when clear. Panels never call
`ui.notify(..., type="negative")` — they set `state.last_error` (via `update` /
`set_data_source`) and call `on_change()`, and `refresh()` does the rest. The
**one** surviving toast is the positive "Saved" confirmation, which is transient
good news; the status bar also shows a green `✅ Saved` and reverts to the live
error/idle state on the next `refresh()`. Do not reintroduce negative toasts.

Plotly click payloads carry `customdata` in **two shapes**: the paired trace carries
`(key, diff, verdict, *hover)`, the rug traces a bare key.
`key_from_customdata` normalises both — never index into it directly.

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
- **Numeric plot data must be finite.** CSV parsing and `from_sequences` both
  reject infinities; only `None` and NaN mean missing.
- **Integer config fields are actual positive integers.** Reject booleans and
  floats rather than relying on `int(...)`, which turns `true` into `1` and
  silently truncates fractions. Direct dataclass construction follows the same
  rule as TOML coercion.
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
- **`[output].format` is tri-state and read through `resolved_format`, never
  directly.** `None` (an absent key) means "take it from the path's extension,
  else html", so `path = "shot.png"` writes a PNG. An explicit format that
  *contradicts* the extension raises in `__post_init__` rather than picking a
  winner — either resolution would silently discard one of the two things the
  user wrote. `cli._infer_format` still exists and is still needed: it makes an
  explicit `-o out.png` **override** a format the TOML set, which the config-level
  inference alone cannot do. The silent-HTML-into-`.png` bug shipped twice — once
  on `example`'s `-o`, once via the TOML path.
- **`embed = true` writes an HTML fragment, not a document** — `plot.to_fragment`
  (public, exported from `parity_plot`) returns a `<div>` + `<script>` with no
  `<html>` wrapper — data only, so a few KB to tens of KB, against the flat
  ~4.9 MB of library an inlined document repeats per file. `save()` routes
  through it so there is
  one implementation. Two things there are load-bearing: `plotlyjs` resolves to
  `"none"` when embedding (via `resolved_plotlyjs` — the point of fragments is
  that the *page* loads plotly.js once), and the embed branch sits **before**
  `fig.update_layout(width=…, height=…)` on purpose. A fragment must stay
  autosizing: bake in pixels the container does not have and Plotly lays the axes
  out for the wrong box, `constrain="domain"` shrinks against stale numbers, and
  **the 45° line silently stops being diagonal**. Consumers must call
  `Plotly.Plots.resize(div)` on container resize. `div_id` exists so cached or
  diffed fragments do not churn on plotly's random UUID.
- **`docs/embedding.md` is the consumer-facing embedding contract** — written for
  whoever builds the app that hosts the fragments, and the place to record
  anything learned about multi-plot pages. Its claims are all measured against the
  real output (fragment structure, the exact 5,000/5,001 `scatter`→`scattergl`
  boundary, compressed library sizes); if the fragment shape or the threshold ever
  changes, that file goes stale silently, so update it in the same commit.
- **`parity_plot(config=<toml path>)` is a supported entry point** — a config is a
  complete instruction, no `ref`/`test`/paths needed (keyword options still win
  over it). It is what an app embedding many plots uses, so one committed TOML
  renders identically through the CLI, the designer, and library code.
- **HTML exports are self-contained by default** (`[output].plotlyjs = "inline"`,
  `PLOTLYJS_MODES`): ~4.8 MB per file, but it opens air-gapped, emailed, or years
  later when the pinned CDN build is gone. `"cdn"` is 84 KB and needs a network;
  `"directory"` writes `plotly.min.js` once per folder. `plot._PLOTLYJS_ARG` maps
  these onto plotly's own `include_plotlyjs` spellings. **The designer needs no
  CDN either** — NiceGUI serves its own assets, a vendored plotly ESM bundle, and
  AG-Grid *community* from the venv. When testing offline-ness, do not assert on
  a bare `cdn.plot.ly`: the inlined bundle contains that host as plotly's
  topojson default for geo maps. Assert on the `src="https://cdn.plot.ly` tag.
- `data/` and rendered plots are gitignored; regenerate with `parity-plot example`.
- **Tolerance band shading is the per-tolerance `style` key** (`"lines"` |
  `"shaded"`), living inside a `[[plot.tolerances]]` table. `band_style` is a
  **retired `[plot]` key** (`RETIRED_PLOT_KEYS`) and setting it raises "moved into
  a tolerance list in 0.2.0". So does `abstol`/`reltol`/`identity_line` at
  `[plot]` scope. `RETIRED_DATA_KEYS` (`paths`/`x`/`y`/`key`/`value`) is the
  `[data]` equivalent from the multi-file rework.
- **The `example` shape knobs are fractions, not counts.** `--outliers`,
  `--noise`, `--bias` are ratios in `[0, 1]` (`--outliers 0.01` = 1%); passing a
  count like `--outliers 6` fails `ExampleSpec.__post_init__`. Only the
  `--missing-*` null knobs accept explicit counts (else a fraction of `n`).
- **The CLI drives no plot or data *setting* — TOML is the single source of truth
  (CLI teardown).** `plot` takes a positional `CONFIG` (default `parity.toml`)
  plus only operational flags: `-o/--output` (where to write) and `--open-browser`.
  A missing config raises a message pointing at `parity-plot init`. `example` keeps
  its generator knobs (`--noise`, `--seed`, `--missing-*`, …) and `-o`/`--plot`, but
  lost every appearance flag. There is no `--ref`/`--test`/`--join`/`--group`/
  `--theme`/`--tol` any more, and `_default_ref_test` is gone. `parity-plot init` +
  the commented `EXAMPLE_TOML` + rich docstrings are the agent-discovery surface;
  shape a plot via TOML or `parity-plot design`.
- **kaleido prints `Resorting to unclean kill browser.` on static export** — it is
  benign noise from the headless-Chrome teardown; the image is written fine. Do not
  chase it as an error.
- **README screenshots are committed under `docs/images/`.** PNG/SVG/PDF are
  gitignored globally, so `.gitignore` carries an explicit `!docs/images/` +
  `!docs/images/*.png` negation. Regenerate them by rendering small TOML configs
  through the CLI (`plot <config>.toml`, with `[output].path =
  docs/images/<name>.png`); use `theme = "light"`, which reads best on GitHub. The
  `colorscale.png` showcase (colour = temperature, shape = package) is rendered from
  the regenerated `data/example.csv`. Static export needs a headless Chrome
  (`uv run plotly_get_chrome`).

## Releases

Versioning is manual in `pyproject.toml`; releases are cut with git tags **and**
GitHub Releases. Current released line: **0.10.0** (`main`). History: 0.1.0 → multi-file
data model & encoding (0.3.0) → file-independent group + persistent designer
status bar + visual README (0.4.0) → `symbol_sequence` & symbol-by-group named by
value (0.5.0) → composite group, colorscale channel, TOML-only CLI, designer
auto-save/config picker, hover-text columns (0.6.0) → offline-by-default HTML,
output-format inference, embeddable fragments (0.7.0) → embedding guide and tabbed
report consumer (0.8.0) → delta histogram (0.9.0) → polynomial reference lines,
viewport-origin controls, and alignment/validation hardening (0.10.0). Tags
`v0.1.0`–`v0.3.0` predate the GitHub Releases; `v0.4.0` onward have them.

The ship flow (only when the user asks): run `./check-tier-2`, branch off `main`, commit, bump the
version on the branch, `git checkout main && git merge --no-ff`, `git tag -a`,
`git push origin main && git push origin <tag>`, then `gh release create <tag>
--verify-tag --title … --notes …`. Bump policy in use: an additive feature is a
**minor** bump, and even a breaking config change (the 0.4.0 group-syntax change)
has been treated as **minor** while pre-1.0.
