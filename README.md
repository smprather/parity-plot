# parity-plot

45° parity plots from Plotly, usable as a Python package or a CLI.

A parity plot scatters one dataset against another with a `y = x` identity line,
to show how well the two agree. This one handles the case most tools ignore:
records that exist in one dataset but have **no corresponding measurement** in
the other.

## Requirements

- Python `>=3.14`
- [`uv`](https://docs.astral.sh/uv/)

## Install

```bash
uv sync                    # everything, including the interactive designer
```

png/svg/pdf export additionally needs a headless Chrome for kaleido to render
into: `uv run plotly_get_chrome`. HTML output needs none of that.

## Quick start

```bash
uv run parity-plot example      # generate 1000 sample points, plot them, open the browser
```

That writes the CSVs into `data/`, renders `parity.html`, and opens it. Both
commands open the result by default; pass `--no-open-browser` to suppress that,
or `--no-plot` to skip rendering entirely.

```bash
uv run parity-plot plot data/example.csv --theme light --reltol 10pct
uv run parity-plot plot data/example.csv --no-open-browser -o quiet.html
```

## Shaping the example data

The generator is adjustable, so you can watch the plot respond:

```bash
uv run parity-plot example --noise 0.25 --bias 0.10    # sloppy and skewed
uv run parity-plot example --noise 0.01 --outliers 0   # tight and clean
uv run parity-plot example --missing-x 100 --missing-y 100   # lots of unpaired records
uv run parity-plot example --x-min 1 --x-max 1e5 --plot
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

Fractions rather than percentages. The null counts
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

## Data sources

Open any number of files; the two plotted series — **reference** and **test** —
are each picked as `file:column`. They must be numeric.

```bash
# both columns in one file (they pair by row order)
uv run parity-plot plot data.csv --ref 'data.csv:reference' --test 'data.csv:test'

# a column from each of two files, aligned on a join key
uv run parity-plot plot meas.csv sim.csv \
    --ref 'meas.csv:voltage' --test 'sim.csv:voltage' --join id

# a single file with no flags defaults ref/test to its first two numeric columns
uv run parity-plot plot data.csv
```

With `--join`, rows are outer-joined on that key (a key on only one side is
unpaired). **Without a join, rows pair by position**, and the longer column's
tail is left unpaired. A `--group FILE:COL` labels each point for the encoding
below. Unpaired records — a value with no partner — are drawn as rug ticks on
the axis whose value is known, never dropped.

## Encoding

Marker **colour** and **symbol** are driven independently, each by one of
`single | pass-fail | group`:

```bash
uv run parity-plot plot data.csv --group 'data.csv:batch' \
    # via TOML, or the designer: color_by = group, symbol_by = pass-fail
```

```toml
[plot.encoding]
color_by  = "group"       # single | pass-fail | group
symbol_by = "pass-fail"
color     = "blue"        # the token used when color_by = single
symbol    = "circle"      # the symbol used when symbol_by = single
```

- **single** — every point the same colour/symbol.
- **pass-fail** — the overall verdict: pass = green circle, fail = red ✕.
- **group** — by the group column: a colour palette / a symbol cycle.

So "colour by batch, `✕` for failures, `○` for passes" is `color_by = group`,
`symbol_by = pass-fail` — one legend entry per `(batch, verdict)`.

## Python API

```python
from parity_plot import parity_plot

fig = parity_plot("data.csv", ref="data.csv:reference", test="data.csv:test")
fig = parity_plot("meas.csv", "sim.csv", ref="meas.csv:v", test="sim.csv:v", join="id")
fig = parity_plot(ref=[1.0, 2.0, 3.0], test=[1.1, None, 2.9], theme="light")
fig.show()
```

Any iterable of numbers works for `ref`/`test` — lists, pandas Series, numpy
arrays — with `None` or `NaN` marking a missing value.

## Config file

`uv run parity-plot init` writes a documented `parity.toml`. Every key has a
matching CLI flag, and **CLI flags win over the file, which wins over defaults**.

```toml
[data]
files = ["data/example.csv"]   # any number of files
ref   = "example.csv:reference"   # file:column, numeric
test  = "example.csv:test"
# join  = "id"                 # optional; omit to pair by row order
# group = "example.csv:batch"  # optional

[plot]
theme = "dark"                 # dark | light
nulls = "rug"                  # rug | drop
legend = "right"               # right | bottom | none

[plot.encoding]
color_by  = "single"           # single | pass-fail | group
symbol_by = "single"

[[plot.tolerances]]            # a list; repeat the block for more
name = "spec"
reltol = 0.10                  # a ratio; "10pct" also accepted
# abstol = 2.0                 # and/or an absolute bound
kind = "pass"                  # pass | info
color = "red"
style = "lines"                # lines | shaded

[output]
path = "parity.html"
format = "html"                # html | png | svg | pdf
```

```bash
uv run parity-plot plot -c parity.toml
uv run parity-plot plot -c parity.toml --theme light   # flag overrides the file
```

## Tolerances

A plot carries a **list** of named tolerances — a customer limit, a tighter
internal target, a reference band nobody is graded against. Each has:

| Attribute | Meaning |
| --- | --- |
| `name` | stable identifier, freeform |
| `abstol` | absolute tolerance, in the data's units — lines **parallel** to `y = x` |
| `reltol` | relative tolerance, a ratio (`0.1`) or `10pct` — a **wedge** through the origin |
| `kind` | `pass` (a criterion) or `info` (drawn for reference, never judged) |
| `color` | a token (`red`, `blue`, `green`, …) or a hex value |
| `style` | `lines` or `shaded` |
| `label` | legend text; `auto` derives it from the spec |

At least one of `abstol`/`reltol` is required. Given both, the permitted
deviation is the **looser** of the two — `max(abstol, reltol·|x|)` — so the
envelope runs parallel near the origin and flares into a funnel past the
crossover, drawn as real geometry rather than sampled.

The **parity line** (`y = x`) is itself the first, built-in tolerance: a
zero-width `info` entry named `parity`, drawn green, that cannot be deleted.

Each pass/fail tolerance judges every paired point. A point's verdict — `pass`,
or the names of the limits it failed — appears in the hover, the record table,
and the inspector. The statistics box reports the pass rate per criterion
(`within spec: 85.5%`); info tolerances are omitted.

```bash
# repeatable --tol, each a key=value spec
uv run parity-plot plot data.csv \
    --tol 'name=spec,reltol=10pct' \
    --tol 'name=tight,abstol=2,kind=info,color=blue,style=shaded'

# --abstol / --reltol stay as shorthand for a single tolerance
uv run parity-plot plot data.csv --abstol 2 --reltol 10pct
```

`--reltol` is a true ratio: `0.1` is a tenth, `10pct` says the same in percent,
and a bare `10` means ten times the reading — the unit is stated, never guessed.
The whole list also round-trips through `parity.toml` as `[[plot.tolerances]]`
tables, and is editable live in the designer.

## Interactive designer

```bash
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

**Brushing an x-window** is wired but not yet the default gesture: dragging
zooms, as Plotly normally does. Pick **Box Select** from the plot's toolbar and
drag, and the plot, table and statistics all narrow to the records inside the
window, with the axes rescaling to fit. Double-click clears it. Brushing composes
with the switches rather than overriding them.

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
agreement. Unpaired records appear
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
