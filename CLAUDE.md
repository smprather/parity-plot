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
