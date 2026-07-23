# Design: composite group, colorscale colour mode, CLI→TOML teardown, richer example data

Date: 2026-07-23
Status: approved (pending spec review)

## Summary

Four coordinated changes to parity-plot, all landing together (no user base, so
breaking changes are free):

1. **Composite group** — `group` accepts more than one column; each point's
   legend label joins the values with `, ` (matching today's single-column
   bare-value style).
2. **Colorscale colour mode** — a new `color_by = "colorscale"` drives marker
   colour from a numeric column via a Plotly continuous colour scale (a
   colorbar), with the scale name selectable in TOML and the designer.
3. **CLI → TOML teardown** — the CLI stops carrying flags that drive plot
   settings; all appearance/data settings come from TOML. Only *operational*
   flags survive. `parity-plot init` becomes the discovery surface.
4. **Richer example data** — the example generator emits extra categorical and
   numeric columns so features 1 & 2 are demonstrable out of the box, and so the
   *next* feature (hover-text column selection) has data to show.

The unifying principle: **TOML is the single source of truth for what a plot
looks like; the CLI only decides which config runs and where output goes.**

---

## Feature 1 — Composite group

### What changes

`group` becomes a list of bare column names. Each stays file-independent (may
live in one or several files; when in several, the value must still agree per
column via the existing `_agree` cross-file check). A paired point's group
**label** is the per-column values joined by `, `.

Label rules:
- 1 column → bare value `xxx` (unchanged from today; preserves golden tests).
- 2+ columns → `xxx, yyy` (values in column order, joined by `, `).
- A blank cell in one column → that slot shows `(none)` → `xxx, (none)`.
- **All** group columns blank at a point → the point is ungrouped
  (`group = None`), exactly as today.

### Where it lives

Composition happens in `data.py`, at the seam. Everything downstream
(`ParityData.group`, `encoding.py`, `plot.py`) keeps seeing **one opaque label
per point** and is unchanged.

- `config.DataConfig.group`: `str | None` → `tuple[str, ...]` (empty tuple =
  none). New coercion in `config._coerce` normalises `"batch"` → `("batch",)`
  and `["batch","vendor"]` → tuple, so existing single-string TOML still loads.
- `data._group_lookup(src, groups: tuple[str, ...], join, na)`: resolves each
  column independently (existing `files_with_column` + `_agree` per column) and
  returns the composite label, or `None` if every column is blank.
- `data.load`: passes `cfg.group` (the tuple) through; the `if cfg.group` guard
  (truthy) still works for an empty tuple.
- `parity_plot.__init__` public API: `group` accepts a `str` or a `list[str]` of
  column names (in the `file:column` / columns case), or a per-point sequence
  (in-memory case) — as today, disambiguated by whether it is a string.

---

## Feature 2 — Colorscale colour mode

### What changes

A fourth colour channel, `color_by = "colorscale"`, colours each point by a
numeric column through a Plotly continuous colour scale. It renders as a
**colorbar** (a separate gradient bar), never as legend entries — verified: a
colorbar and a symbol legend coexist as two side-by-side elements, so
`color_by = "colorscale", symbol_by = "group"` yields colorbar + symbol legend.

### The colour column is a single `file:column`

Unlike `group` (file-independent, agreement-checked), the colour column is a
**single pinned `file:column`** resolved like `ref`/`test`. Rationale: the same
column name (e.g. `load`) can legitimately hold *different* values in the
reference and test files for one paired point, so the user must pick exactly
which file's copy drives the colour. There is no `_agree` here.

### Config / data seam

- `config.DataConfig.color_column: str | None` — new `[data]` key, a
  `file:column` numeric ref. Named `color_column` (not `color`) to avoid
  confusion with `Encoding.color` (the single-colour token). Mirrors how the
  `group` *column* lives in `[data]` while the *channel* lives in
  `[plot.encoding]`.
- `data.load`: when set, `src.resolve` + `_require_numeric` (same path as
  ref/test), align exactly like group (join-key or row index), producing
  `ParityData.color_values: list[float | None] | None`. A blank cell → `None`.

### Encoding

- Split `CHANNELS` into:
  - `COLOR_CHANNELS = ("single", "pass-fail", "group", "colorscale")`
  - `SYMBOL_CHANNELS = ("single", "pass-fail", "group")`
  `Encoding.__post_init__` validates `color_by` against `COLOR_CHANNELS` and
  `symbol_by` against `SYMBOL_CHANNELS`, so `colorscale` is colour-only and is
  rejected on `symbol_by`.
- `Encoding.colorscale: str = "viridis"` — the named Plotly scale. Validated
  against `plotly.colors.named_colorscales()`, lowercasing and stripping an
  optional `_r` reverse suffix (mirrors the symbol-variant strip), so
  `"Viridis"`, `"viridis"`, `"viridis_r"` all pass and a typo raises an
  `EncodingError`.
- `encoding.color_key_of`: when `color_by == "colorscale"` return a **constant**
  key (`"colorscale"`), so colour no longer partitions traces — colour is
  per-point. Symbol still partitions. Result: `colorscale + symbol_by=group` →
  one trace per symbol group, each carrying its slice of the numeric array.

### Plot

- `plot._add_paired` gains `color_values`. When `encoding.color_by ==
  "colorscale"`: set `marker.color = [color_values[i] for i in idx]`,
  `marker.colorscale = encoding.colorscale`, shared `cmin`/`cmax` (min/max over
  all non-None values), `showscale=True` on the **first** trace only, and a
  `colorbar` titled by the colour column name. `None` values pass through
  (Plotly renders them as gaps).
- `plot.build_figure`: guard — `color_by == "colorscale"` but
  `data.color_values is None` raises a clear error
  ("color_by=colorscale needs [data].color_column").
- **Layout, colorbar vs. legend:** with `legend = "right"` both the colorbar and
  the legend want the right margin. When colorscale is active, offset the
  colorbar (`x ≈ 1.02`) and push the legend further right, widening the right
  margin. Add a test asserting no overlap (colorbar `x` < legend `x`, margin
  accommodates both). `legend = "bottom"` / `"none"` need no special handling
  (colorbar takes the right, legend the bottom/absent).

---

## Feature 3 — CLI → TOML teardown

**Principle:** TOML drives everything about how a plot looks and what data it
reads. The CLI keeps only *operational* options — which config runs, where
output is written, whether a browser opens.

### `plot` command

Reduced to:
- Positional `[CONFIG]` — the TOML path (default `parity.toml`; a missing file
  raises a clear error pointing at `parity-plot init`). Replaces `--config`.
- `-o` / `--output` — operational override of the output *path* (kept: it does
  not change how the plot looks). Format is inferred from the `-o` suffix via
  `_infer_format`, else `[output].format`.
- `--open-browser` / `--no-open-browser` — operational.

**Dropped** (now TOML-only): the data-file positional args and `--ref --test
--join --group`; every appearance flag `--theme --title --x-label --y-label
--log --tol --abstol --reltol --band-style --nulls --legend --stats`; and
`--format --width --height`. The `parity-plot plot data.csv` zero-config
convenience and `cli._default_ref_test` auto-pick are removed — TOML is explicit.

### `example` command

Keeps its **generator** knobs (`-n/--count`, `--seed`, `--out-dir`, `--x-min`,
`--x-max`, `--bias`, `--noise`, `--noise-floor`, `--outliers`, `--missing-*`) —
these shape *data*, not plot appearance — and its **operational** flags
(`--plot/--no-plot`, `-o`, `--open-browser`).

**Dropped** appearance flags: `--theme --abstol --reltol --tol --no-tolerance
--band-style --legend --width --height`. The example command's built-in auto-plot
constructs its `PlotConfig` internally with sensible defaults (no CLI flags feed
it).

### `init` and `design`

- `init` — unchanged in behaviour, but now the **primary discovery surface**.
  `config.EXAMPLE_TOML` must document every option thoroughly, including the new
  `group` (list), `color_column`, `color_by = "colorscale"`, and `colorscale`.
- `design` — unchanged (its `PATHS` + `--config` are operational bootstrapping).

### Agent discoverability

Because appearance is TOML-only, an agent driving parity-plot into another
application discovers options via, in order:
1. `parity-plot init` → a fully-commented `parity.toml` template.
2. A `plot --help` **epilog** that explicitly routes to `init` and states that
   all plot/appearance settings live in TOML.
3. The Python API: `parity_plot.parity_plot(...)` and the config dataclasses
   carry docstrings rich enough to drive from code.

### Ripple

- `cli.py` — largest edit (mostly deletion); rewrite `HELP_CONFIG.option_groups`
  for the slimmed commands (respect the rich-click "first declaration" gotcha).
- `tests/test_cli.py` — rewrite around the new surface.
- README — drop the flag tables / "every key has a matching CLI flag" claim;
  point at `init` + TOML.
- `CLAUDE.md` — update the "Encoding has no CLI flags" note and the rich-click
  `OPTION_GROUPS` gotcha to match; note the CLI is now TOML-only for settings.

---

## Feature 4 — Richer example data

Extend the generator so the example CSVs carry columns that exercise the new
features and pre-stage the next one (hover-text column selection).

New per-record columns (deterministic under the seed, no new CLI knobs — keeps
`example` lean and consistent with dropping appearance flags):
- `package` — categorical (e.g. `SMD`, `DIP`, `BGA`, `QFN`).
- `vendor` — categorical (e.g. `Acme`, `Beta`, `Ceres`).
- `temperature` — numeric (e.g. −40…125), suitable for the colorscale channel;
  may be lightly correlated with the disparity so the colorbar tells a story.

These give: a composite-group demo (`group = ["package", "vendor"]`), a
colorscale demo (`color_column = "example.csv:temperature"`), and spare columns
for the future hover-text feature.

- `examples.Record` gains the new fields.
- `write_wide` writes all columns. `write_pair`: the group columns
  (file-independent) and the numeric colour column go in `reference.csv` so they
  resolve for paired points; absent rows for unpaired points are fine (group and
  colour are paired-only concerns).
- `tests/test_examples.py` — update column assertions.

> **Out of scope tonight:** the hover-text column-selection feature itself. Only
> the example data that will feed it is added now.

---

## Designer (all features)

- **Data panel** (`panels/data_panel.py`): the `Group by` select becomes a
  **multiselect** (chips) bound to the `group` tuple. A new **`Colour column`**
  select offers numeric `file:column` (`— none —` default) → `data.color_column`.
- **Encoding panel** (`panels/encoding.py`): `Colour by` gains `colorscale`. A
  new **`Colour scale`** dropdown (options from `named_colorscales()`) is visible
  only when `color_by == "colorscale"` (same `bind_visibility_from` pattern the
  `symbol_sequence` picker uses).
- Wiring stays through `state.set_data_source` / `state.update`, inheriting the
  existing validation and persistent status-bar error path. No new error paths,
  no toasts.

### Serialize (`designer/serialize.py`, `config.py`)

- `group` tuple round-trips as a TOML list (existing `_to_toml_value` handles
  tuples).
- `data.color_column` is a plain string — round-trips for free.
- Extend the tomlkit `Encoding` encoder (`config._register_tomlkit_encoding_encoder`)
  to emit `colorscale`, and only when it differs from the default (same
  treatment as `symbol_sequence`).

---

## Testing

Behaviour-preserving default is the invariant: with no group columns and
`color_by != "colorscale"`, every existing golden test must stay green.

- **Composite group** (`test_data_load.py`): `, ` join; `(none)` slot for a
  blank column; all-blank → `None`; per-column `_agree` still raises on
  cross-file disagreement; single-column label unchanged.
- **Colour column** (`test_data_load.py` / `test_sources.py`): resolve + align
  (join and order modes); `_require_numeric` error names file:line; blank → None.
- **Encoding** (`test_encoding.py`): `colorscale` name validation + `_r` strip +
  typo raises; `colorscale` rejected on `symbol_by`; `color_key_of` constant
  under colorscale; `colorscale + symbol_by=group` partitions by symbol only.
- **Plot** (`test_plot.py`): colorbar present; `showscale` true on exactly one
  trace; shared `cmin`/`cmax`; per-group colour arrays; colorbar-vs-legend
  no-overlap margins.
- **Config** (`test_data_config.py`, `test_encoding_config.py`): `group`
  string→tuple and list→tuple coercion; `color_column` key; `colorscale` key;
  unknown-key still raises.
- **Golden WYSIWYG** (`designer/test_golden_wysiwyg.py`): a
  colorscale + multi-group config saved from the designer renders an identical
  figure through the CLI path. Must stay green.
- **Serialize** (`designer/test_serialize.py`): `group` list, `color_column`,
  `colorscale` round-trip; default `colorscale` not emitted.
- **CLI** (`test_cli.py`): the slimmed `plot` (positional config, `-o`,
  open-browser) and `example`; a missing config points at `init`; help epilog
  present.
- **Examples** (`test_examples.py`): new columns present in wide and pair files.

---

## Non-goals

- Hover-text column selection (next feature; data is staged, UI is not).
- polars / parquet caching (deferred; stdlib `csv` stays while the feature set
  is built out — the real driver is future 10M-row datasets, revisit with a
  benchmark then).
- A CLI flag for any plot/appearance setting (deliberately removed).
