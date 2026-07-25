# Hover-text column selection — design

**Date:** 2026-07-25
**Status:** approved, ready to plan
**Version target:** 0.6.0 (additive feature → minor bump)

## Problem

The hover box is hardcoded. Every paired point shows exactly five things — the
key, the two axis values, their difference, and the tolerance verdict — built
from a fixed `customdata=(key, diff, verdict)` triple in `plot._add_paired`.

Real datasets carry context that decides what a point *means*: which package a
part is in, which vendor supplied it, what temperature it was measured at. That
context is sitting in the same CSV, one column over, and there is no way to put
it on screen. The 2026-07-23 work pre-staged the example data for exactly this
feature (`package`, `vendor`, `temperature`) and deferred the feature itself.

## Solution

A new `[data]` key naming extra columns to show in the hover box, defaulting to
everything available.

### Config surface

`DataConfig` gains one field:

```python
# Extra per-point rows in the hover box, as pinned `file:column` refs.
# None = auto: every candidate column of the ref/test files.
# () = suppress; an explicit tuple pins that set, in that order.
hover_columns: tuple[str, ...] | None = None
```

**A `file:column` ref, pinned to one file** — like `color_column`, not like
`group`. The same bare column name can hold different values in the reference
and the test file, and for a hover that difference is information, not a
conflict. Pinning also means the auto default can never fail: a file-independent
bare name would resolve through `_agree`, which *raises* on disagreement, so
defaulting to all columns would break plots whose two files legitimately differ
in a shared column.

**The tri-state is load-bearing:**

| value | meaning |
|---|---|
| `None` (key absent) | auto — every candidate column of the ref/test files |
| `()` (`hover_columns = []`) | suppress; hover keeps only its structural rows |
| a tuple | pin exactly these, in this order |

`None` tracks a ref/test change instead of going stale, which is why the default
stays implicit rather than being materialised into the file on save. TOML cannot
write null, so absence *is* `None` — no sentinel needed. `_coerce` gets a
`hover_columns` branch (list → tuple of `str`, via `_as_sequence` so a bare
string errors the way `na_values` does).

### The candidate set

Candidates are every column of **ref's file and test's file**, minus:

- the **ref** column — already the `x:` hover row,
- the **test** column — already the `y:` hover row,
- the **join** column — already the bold key line.

Those three are structural hover rows. They are not merely off by default: they
are never offered, because a config that could duplicate them is a config that
can only look wrong.

A single file backing both ref and test contributes its columns once. A third
open file is **not** offered — without a join into it there is no way to align
its rows to a point. Auto order is ref-file columns in header order, then
test-file columns in header order.

### Data layer (`data.py`)

`ParityData` gains two fields, aligned to the paired points exactly as `group`
and `color_values` are:

```python
hover_labels: tuple[str, ...] = ()                   # display text, one per column
hover_values: list[tuple[str, ...]] | None = None    # one tuple per paired point
```

Row-major (a tuple per point, not per column) because that is the shape
`customdata` wants.

Three helpers, mirroring the shapes already in the module:

- **`hover_candidates(src, ref, test, join) -> list[str]`** — the auto set.
  **Public**, because the designer's picker needs precisely this list; deriving
  it twice is how the picker and the renderer drift apart.
- **`hover_labels_for(refs) -> tuple[str, ...]`** — the bare column name, file
  name prefixed **only** when that bare name appears in more than one selected
  ref. So `package`, but `reference.csv:temperature` and
  `measured.csv:temperature` when both files carry it. Shortest unambiguous
  label. The prefix is the file's `Path.name`, not whatever the ref happened to
  spell — a ref given as a full path still labels as `reference.csv:temperature`.
- **`_hover_lookup(src, refs, join, na)`** — per column, pinned to its own file,
  structurally identical to `_color_lookup`: a dict keyed by the join value, or
  an index lookup when pairing by order. No `_agree`, no cross-file voting —
  pinned refs have nothing to reconcile.

**Values pass through as raw stripped cell text.** No float coercion, no
formatting. Lossless, no numeric/categorical branch to get wrong, and it shows
what the file actually says. A blank or NA cell renders `—` so "present but
empty" is legible rather than looking like a missing row.

`load` validates each ref: `src.resolve` already raises on an unknown file or
column, and a ref naming an **open but non-candidate** file raises a new
`DataError` naming the candidate files. Rendering nothing for a key the user
typed is the silent-default failure this project already rejects for unknown
TOML keys.

### Plot layer (`plot.py`)

`customdata` widens from `(key, diff, verdict)` to `(key, diff, verdict,
*hover)`. `designer/records.key_from_customdata` reads index 0, so the click and
selection path is untouched.

Extra rows land **between `difference` and the verdict** — metadata belongs with
the record's identity, and the verdict reads as the conclusion:

```
R42
reference: 10.2
measured: 10.5
difference: +0.30
package: SMD
temperature: 25
outside spec
```

`_drop_non_positive` re-slices `hover_values` alongside `color_values`. (It
still does not re-slice `group`; that pre-existing gap is not this feature's to
close.)

### Designer

- `panels/data_panel.column_options` gains `"hover_columns":
  hover_candidates(...)`.
- An **Auto** switch (default on, "all columns from the ref/test files") above a
  chipped multi-select that is disabled while Auto is on. Auto off with nothing
  selected is `()` — suppressed.
- Changing ref/test prunes pinned refs that are no longer candidates, the way
  `refresh_group` already re-derives the group options.
- **`DesignerState.set_data_source` gains `clear: Sequence[str] = ()`**, which
  resets those `data` fields to their dataclass default on the candidate config
  before loading. Necessary because `ParityConfig.merge` drops `None` overrides
  by design, and here `None` is the meaningful value; `reset_fields` cannot serve
  because it does not reload the data. Auto-on passes
  `clear=("hover_columns",)`.
- `designer/serialize.py` needs no change: it already deletes a key whose value
  is `None` and renders a tuple as a list. Auto therefore writes nothing to the
  file.

## Non-goals

- **Unpaired (rug) hover is unchanged.** Per-point extras are a paired-point
  concern in this codebase already — `group` and `color_values` both are — and
  threading them through `Unpaired` is a separate change.
- **`from_sequences` gains no hover parameter.** The in-memory API has no files
  to resolve refs against.
- **No float formatting.** See Future work.

## Future work

**Auto/manual schema detection for configurable float formatting.** Raw
pass-through shows a CSV's own text, which means a column written as
`25.400000000000002` hovers exactly that way, and there is no way to ask for
`%.3f` or a unit suffix. Doing it properly needs a per-column schema — detected
automatically (numeric / integer / categorical, as `datasets.preview` already
does for the peek grid's AG-Grid column types) with a manual override, plus a
per-column format string in the config. That is its own feature; raw text is the
correct interim behaviour because it is lossless and never lies about the data.

## Testing

- **`tests/test_config.py`** — tri-state coercion (absent → `None`, `[]` → `()`,
  list → tuple); a bare string raises; round-trip through `from_dict`.
- **`tests/test_data.py`** — the auto set and all three exclusions; ref and test
  in one file (columns offered once); a pinned subset in its given order; `()`
  suppressing; alignment correct under a join **and** under pair-by-order; a
  third-file ref raises `DataError`; label disambiguation when both files share a
  column name; blank cell renders `—`.
- **`tests/test_plot.py`** — the labels and `customdata[3]`… appear in the
  `hovertemplate`; `customdata` tuple width matches; no extra rows when
  suppressed; log mode re-slices `hover_values` in step with `x`/`y`.
- **`tests/designer/`** — `column_options` carries the new key; Auto ↔ pinned
  round trip through `set_data_source(clear=...)`; a stale pinned ref is pruned
  when ref/test change.
- **`tests/designer/test_golden_wysiwyg.py`** — must stay green. The auto default
  changes the hover of every existing plot, so if this test compares hover
  content it needs updating in step; whatever it asserts, designer and CLI must
  still agree.

## Documentation

- `config.EXAMPLE_TOML` — a commented `hover_columns` block explaining the
  tri-state.
- `README.md` — a hover section.
- `CLAUDE.md` — a paragraph beside the `color_column` one: pinned like colour,
  candidate-restricted, tri-state, raw text with the formatting TODO noted.
