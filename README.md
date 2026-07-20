# parity-plot

45° parity plots from Plotly, usable as a Python package or a CLI.

A parity plot scatters one dataset against another with a `y = x` identity line,
to show how well the two agree. This one handles the case most tools ignore:
records that exist in one dataset but have **no corresponding measurement** in
the other.

## Install

```bash
uv sync                    # runtime + dev
uv sync --extra static     # adds kaleido, for png/svg/pdf export
```

Static export also needs a headless Chrome for kaleido to render into:
`uv run plotly_get_chrome`. HTML output needs none of that.

## Quick start

```bash
uv run parity-plot example      # generate 1000 sample points, plot them, open the browser
```

That writes the CSVs into `data/`, renders `parity.html`, and opens it. Both
commands open the result by default; pass `--no-open-browser` to suppress that,
or `--no-plot` to skip rendering entirely.

```bash
uv run parity-plot plot data/example.csv --theme light --tolerance 0.1
uv run parity-plot plot data/example.csv --no-open-browser -o quiet.html
```

## Shaping the example data

The generator is adjustable, so you can watch the plot respond:

```bash
uv run parity-plot example --noise 0.25 --bias 0.10    # sloppy and skewed
uv run parity-plot example --noise 0.01 --outliers 0   # tight and clean
uv run parity-plot example --missing-x 100 --missing-y 100   # lots of unpaired records
uv run parity-plot example --x-min 1 --x-max 1e5 --plot --tolerance 0.1
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `-n/--count` | Number of records | 1000 |
| `--seed` | Same seed → same data | 17 |
| `--x-min` / `--x-max` | Reference range (central 95% of draws) | 10 – 100 |
| `--bias` | Systematic slope error, as a fraction | 0.015 |
| `--noise` | Gaussian scatter proportional to the value | 0.06 |
| `--noise-floor` | Gaussian scatter in absolute units | 0.4 |
| `--outliers` | Fraction thrown far off the line | 0.01 |
| `--missing-y` / `--missing-x` / `--both-null` | Unpaired record counts | 1.5% / 1.2% / 0.2% of `-n` |

Fractions rather than percentages, matching `--tolerance`. The null counts
scale with `-n` so a small `-n` still works; pass explicit counts to override.

## Unpaired records

An unpaired record has only one coordinate, so it cannot be a point on the plot.
Dropping it silently would hide a real data-quality signal, so instead it is
drawn as a **rug mark on the axis of the value that is known**:

- a record with a reference but no measurement → tick along the x-axis
- a record with a measurement but no reference → tick along the y-axis

Counts appear in the subtitle. Unpaired records are excluded from the
statistics, since there is no difference to measure. Use `--nulls drop` to hide
the rug marks while still reporting the counts.

## Two input shapes

Both are auto-detected from how many paths you pass.

**One path — wide mode.** An empty cell is a null.

```csv
id,reference,measured
A1,10.2,10.9
A2,15.7,          <- no measurement
A3,,8.1           <- no reference
```

**Two paths — join mode.** Outer-joined on the key column; a row absent from one
file is the null case.

```bash
uv run parity-plot plot data/reference.csv data/measured.csv --key-col id
```

## Python API

```python
from parity_plot import parity_plot

fig = parity_plot("data/example.csv", x="reference", y="measured")
fig = parity_plot("data/reference.csv", "data/measured.csv", key="id")
fig = parity_plot(x=[1.0, 2.0, 3.0], y=[1.1, None, 2.9], theme="light")
fig.show()
```

The generator is importable too, with the same knobs as the CLI:

```python
from parity_plot import ExampleSpec, generate_example, write_example_data

records = generate_example(n=500, noise=0.2, bias=0.0, outlier_rate=0)
write_example_data("data", ExampleSpec(n=5000, x_min=1, x_max=1e4))
```

Any iterable of numbers works for `x`/`y` — lists, pandas Series, numpy arrays —
with `None` or `NaN` marking a missing value. The pieces are importable
separately too:

```python
from parity_plot import load_wide, compute_stats, build_figure, save
from parity_plot.config import PlotConfig, OutputConfig

data = load_wide("data/example.csv", "reference", "measured", "id")
stats = compute_stats(data, tolerance=[0.1])
save(build_figure(data, PlotConfig(theme="light")), OutputConfig(path="out.html"))
```

## Config file

`uv run parity-plot init` writes a documented `parity.toml`. Every key has a
matching CLI flag, and **CLI flags win over the file, which wins over defaults**.

```toml
[data]
paths = ["data/example.csv"]   # one path = wide, two = join
x = "reference"
y = "measured"
key = "id"

[plot]
theme = "dark"                 # dark | light
reltol = 0.10                  # a ratio; "10pct" also accepted
# abstol = 2.0                 # absolute tolerance, in the data's units
band_style = "lines"           # lines | shaded
nulls = "rug"                  # rug | drop
legend = "right"               # right | bottom | none

[output]
path = "parity.html"
format = "html"                # html | png | svg | pdf
```

```bash
uv run parity-plot plot -c parity.toml
uv run parity-plot plot -c parity.toml --theme light   # flag overrides the file
```

## Tolerances

Tolerances carry units, and the two kinds behave differently on purpose:

| Flag | Units | Shape |
| --- | --- | --- |
| `--abstol` | the data's own units | lines **parallel** to `y = x`, a fixed offset |
| `--reltol` | dimensionless ratio | a **wedge** through the origin, widening with magnitude |

`--reltol` is a true ratio: `0.1` means a tenth. Percent must be stated, never
assumed — `10pct` (or `10%`) also means a tenth, while a bare `10` means ten
times the reading. Guessing the unit is the mistake a tolerance spec exists to
prevent.

Given both, the permitted deviation at any point is the **looser** of the two:

```
half-width(x) = max(abstol, reltol · |x|)
```

so the envelope runs parallel near the origin, where the absolute floor
dominates, then flares into a funnel past the crossover at
`|x| = abstol / reltol`. That kink is drawn as real geometry, not
approximated by sampling.

```bash
uv run parity-plot plot data.csv --abstol 2                    # parallel limits
uv run parity-plot plot data.csv --reltol 0.1                  # wedge
uv run parity-plot plot data.csv --reltol 10pct                # the same thing
uv run parity-plot plot data.csv --abstol 2 --reltol 10pct     # funnel
uv run parity-plot plot data.csv --reltol 10pct --band-style shaded
```

The statistics box reports the fraction of paired points inside the envelope,
labelled with the spec it scored against (`within ±max(2, 10%): 98.0%`).

## Interactive designer

```bash
uv sync --extra designer
uv run parity-plot design data/example.csv -c parity.toml
```

Opens a local browser app: edit any setting and the plot updates live, then save
back to the TOML. Comments in an existing config survive the round trip, and a
key you have not changed keeps its original spelling (`reltol = "10pct"` is not
rewritten as `0.1`).

The preview is produced by the same `build_figure` the CLI uses, so what you see
is exactly what `parity-plot plot -c parity.toml` will render. That equivalence
is pinned by a test rather than assumed — `tests/designer/test_golden_wysiwyg.py`
saves from the designer, reloads through the normal config path, renders via the
CLI, and asserts the figures are identical.

Saving refuses to overwrite a config that changed on disk since it was opened,
so an edit made in another window is not silently discarded.

The **Data** panel opens any CSV and maps its columns: give one path for a wide
file or two to outer-join, and the designer reads just the header to offer the
column choices, guessing the mapping from names seen in the wild
(`reference`/`measured`, `expected`/`actual`, `golden`/`dut`). A mapping that
fails to load leaves the previous dataset in place rather than emptying the plot.

Click any point — including a rug tick for an unpaired record — to inspect it in
the **Inspector**: both values, the signed and relative error, and whether it
passes the tolerance currently set. Change the tolerance and the verdict follows.

The **table** below the plot lists every visible record — reference, measured,
signed error, error percent, status and verdict — and sorts by any column, so
"which parts are furthest out of spec" is one click. Selecting a row highlights
the point, and clicking a point highlights the row; both routes write through one
selection so they cannot disagree.

Two switches narrow the plot and the table together: **Failures only** keeps the
paired records outside the current tolerance, and **Include unpaired** governs
records missing a measurement. The count beside them reads `showing 14 of 1,000`
whenever anything is hidden — a filtered view that looked unfiltered would invite
the wrong conclusion about the data.

**Drag a box on the plot** to brush an x-window: the plot, the table and the
statistics all narrow to the records inside it, and the axes rescale to fit.
Double-click to clear. Brushing composes with the switches rather than
overriding them, so "failures only, between 40 and 90" is two gestures.

Narrowing to a slice usually *lowers* the identity R², which is the point — a
wide range flatters the fit, and a slice shows how well the two datasets agree
where you actually care.

Filters are exploration state and are never written to the config. A saved
`parity.toml` describes the plot, not whatever you were looking at.

| Flag | Meaning |
| --- | --- |
| `-c/--config` | TOML to open and save back to |
| `--port` | Port to serve on; falls back to a free one if taken |
| `--open-browser` / `--no-open-browser` | Open a browser on start (default: open) |

## Layout

Both axes always share one range and are pinned to a 1:1 pixel scale, so
`y = x` runs at a true 45°. It is drawn as a **solid green** line — exact
agreement — while tolerance limits are **solid red**. Unpaired records appear
as rug ticks straddling the zero line.

The legend sits on the right by default; `--legend bottom` or `--legend none`
move or remove it.

## Statistics

`R²` is measured **about the identity line**, not about a least-squares fit:

```
R² = 1 - Σ(y - x)² / Σ(y - ȳ)²
```

This matters. Data on a tight line parallel to `y = x` has a best-fit R² of
1.0 while agreeing with nothing; only the identity form exposes that. Pearson
*r* is reported separately for the correlation question. Also computed: RMSE,
MAE, bias (mean signed error), max absolute error, and the fraction of points
inside each tolerance band.

## Tests

```bash
uv run pytest
```
