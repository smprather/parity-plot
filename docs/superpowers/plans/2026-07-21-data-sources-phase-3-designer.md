# Data Sources Phase 3 (Designer GUI) Implementation Plan

**Goal:** The designer starts with no files, opens them from a server-side browser, maps
ref/test/join/group from dropdowns across the open files, and sets the colour/symbol
encoding — all live.

## Pieces

1. **`filebrowser.py`** (pure) — list a directory into (parent, subdirs, csv files with
   sizes); safe path navigation. Delegated.
2. **Empty-start** — `DesignerState.data` becomes optional; the plot shows an empty
   placeholder until files + ref + test are set. `design` launches with zero files.
3. **File browser panel** — a dialog: current dir, up/into navigation, click a CSV to add
   it to the open set.
4. **Data panel rebuilt** — the open-file list (with remove), then `ref`/`test` dropdowns
   from `Sources.numeric_columns()`, `join`/`group` from `Sources.columns()`.
5. **Encoding panel** — two rows (Colour, Symbol), each a `single|pass-fail|group` select
   with a contextual control (token picker / nothing / palette note; symbol picker /
   nothing / cycle note).

## Global Constraints

- Pure `filebrowser.py` imports no nicegui. Panels import it inside functions.
- Empty state must not crash: `figure()` with no data returns a valid empty figure; the
  table/inspector show nothing; `counts()` is `(0, 0)`.
- The golden test still holds — the encoding and data round-trip through TOML.
- Everything routes through `state.set_data_source` / `state.update("plot", ...)`.

---

### Task 1: `filebrowser.py` — directory listing (delegated, pure)

**Files:** create `parity_plot/designer/filebrowser.py`, `tests/designer/test_filebrowser.py`

**Interfaces:**
- `Entry(name: str, path: Path, is_dir: bool, size: int)`
- `Listing(cwd: Path, parent: Path | None, entries: list[Entry])`
- `list_dir(path: str | Path, pattern: str = "*.csv") -> Listing`
  - entries = subdirectories first (alphabetical), then files matching `pattern`
    (alphabetical); each with size (0 for dirs)
  - `parent` is `path.parent`, or None at the filesystem root
  - a nonexistent or non-directory path raises `NotADirectoryError`
  - hidden entries (dotfiles) are omitted

- [ ] Test: listing a temp dir returns its subdirs then its csvs, sorted; non-csv files
  excluded; dotfiles excluded; parent is set (None at root); a file path (not dir) raises;
  sizes are reported for files. Then implement with `os.scandir`, sorting dirs-then-files.
- [ ] Stop. Do not commit.

---

### Task 2: empty-start + panels (inline, orchestrator)

`DesignerState`:
- `data: ParityData | None` (was required). Add `has_data -> bool`.
- `figure()`: when `data is None`, return an empty themed figure (a titled blank with "open
  a file to begin" — reuse `build_figure` with an empty `from_sequences([], [])`, or a bare
  `go.Figure` with the theme template). `visible_data`/`visible_records`/`counts` guard None.
- `set_data_source` already returns False + keeps state on load failure; when there is no
  data yet and the new source is incomplete (no ref/test), it simply stays empty (returns
  False, no error banner, since "not yet configured" is not an error).

`Session.start`: allow zero files — construct a state with `data=None` rather than calling
`load` on an empty config.

`launch.run` / the `design` command: `PATHS` optional; with none, open empty.

**File browser panel**: a button opening a dialog that shows `list_dir(cwd)`; clicking a
dir navigates, clicking a CSV calls `set_data_source(files=current_files + (path,))` and
re-derives ref/test if unset (first two numeric columns of the newly complete set).

**Data panel** (rebuild `panels/data_panel.py`): the open-file list with a remove ✕ each;
`ref`/`test` selects fed by `Sources.numeric_columns()` over the open files (values are
`file:column`); `join` select from every file's columns (bare column names common to the
ref+test files) plus a blank "— none (pair by order) —"; `group` select from all columns
plus blank. Apply routes through `set_data_source(files=, ref=, test=, join=, group=)`.

**Encoding panel** (`panels/encoding.py`, new): Colour row = `single|pass-fail|group` select
+ (when single) a colour-token picker; Symbol row = same + (when single) a symbol picker.
Applies `state.update("plot", encoding=Encoding(...))`.

Wire both into `app.py` between Data and the tolerance panel. Screenshot-verify: empty
start, opening a file, colour-by-group + symbol-by-pass/fail.

---

### Task 3: integration + docs + 0.3.0 release (orchestrator)

- Integration test: start empty (data=None → empty figure), open a file via
  `set_data_source`, set encoding, save, reload, golden-compare.
- README + CLAUDE updates for the multi-file model and encoding.
- Bump to 0.3.0, merge `data-sources` → main, tag.

## Verification

```bash
uv run pytest
uv run parity-plot design            # starts empty
uv run parity-plot design data/example.csv   # or with a file
```
Screenshot: empty start; file opened; colour-by-group/symbol-by-verdict.
