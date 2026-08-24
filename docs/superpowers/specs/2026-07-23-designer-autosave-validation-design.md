# Designer: auto-save session model, config picker, live validation — Design

> **Status:** Implemented. Historical design; use [README.md](../../../README.md) and [CLAUDE.md](../../../CLAUDE.md) for current behavior and contributor rules.

**Date:** 2026-07-23
**Area:** `parity_plot/designer/` only. The CLI, plotting, and config-loading paths are untouched.

## Problem

The designer's persistence is a bottom-of-column **Save** / **Save As** pair over a
`Session` that may have no bound file. Four things are wrong or missing:

1. **Save is meaningless with no file** — clicking it just errors "no config path".
2. **No way to open a different config** without relaunching the process.
3. **The save controls are buried** at the bottom of the settings column.
4. **Bad configs render but aren't flagged** — e.g. ref and test drawn from the *same*
   file while a `join` column is set (a self-join is meaningless; a single wide file must
   pair by order). Nothing tells the user.

Plus a latent bug surfaced during design: **clearing a text field does not revert to its
default.** `controls._clean` returns `None` for a blanked field, but `ParityConfig.merge`
*drops* `None` overrides, so the edit is a silent no-op and the stale value persists. The
`X label` field never falls back to the column name.

## The model: auto-save, bound vs. unbound

The keystone decision (approved): **the designer auto-saves.** Every edit is validated and,
if valid, written straight to the bound config file. This inverts what "unsaved" means.

- **Bound** — a real `.toml` is selected (from the picker, or established via *Save As*).
  Every valid edit is written to that file immediately. A hard-**invalid** edit is
  *withheld*: the file on disk keeps the last valid version, the error is shown, and fixing
  it re-syncs. **Invariant: the bound file on disk always equals the most recent valid
  config.**
- **Unbound** (`<unsaved>`) — from **New Design** or a data-only launch
  (`design data.csv`, no `-c`). Edits drive the live preview, but there is no file to write
  to. **Save As** binds the working config to a name; from then on it auto-saves.

Consequences that *remove* ceremony:

- No plain **Save** button. Auto-save replaces it; problem (1) disappears entirely.
- Because bound state is always in sync, switching configs or starting a New Design while
  bound is **always safe — no confirmation dialog, ever, in bound state.**
- A confirmation survives for exactly **one** transition: **leaving an *unbound* state that
  has unsaved edits** (New Design again, or picking a file from the dropdown). Those edits
  were never written. No edits → no dialog.
- **The stale-file guard is retired.** With continuous auto-save the designer *is* the
  writer; a `StaleFileError` on every keystroke makes no sense. While a config is open in
  the designer, **the designer owns that file**; concurrent external edits are not merged.
  (See Non-goals — bidirectional editing is explicitly deferred.)

## Top toolbar

Move persistence to the **header** (problem 3), as three controls:

| Control | Behaviour |
| --- | --- |
| **Config** dropdown | The parity configs discoverable in the launch directory, plus a `<unsaved>` sentinel shown only while unbound. Selecting a real file **binds + loads** it (confirm first only if leaving an unbound-with-edits state). The selection *is* the current-file indicator. |
| **Save As…** | Type/confirm a path (defaults to the current name). Writes, rescans the directory, and selects the new file (binding future auto-saves to it). Disabled while a hard validation error stands. |
| **New Design** | Blank default config, empty canvas, unbound. Confirms "discard unsaved changes?" only if currently unbound-with-edits. |

The old "saved / unsaved changes" header label is subsumed by the dropdown's selection
(`foo.toml` vs `<unsaved>`).

### Config discovery

A new pure helper in `session.py` (it owns "where configs come from and go") lists candidate
configs in the launch directory:

```
config_choices(dir: Path) -> list[Path]
```

A `.toml` is a candidate iff it **parses as a `ParityConfig`** *and* has a **non-empty
`data.files`** (the touchstone the user specified — a parity-plot config always names input
files). Unparseable or unrelated `.toml`s are omitted. Directory is the process CWD at
launch (where `parity-plot design` was invoked). Rescanned after each *Save As*.

## Validation framework (approved level: blocking)

A new **browser-free, unit-tested** module — `parity_plot/designer/validation.py`:

```python
@dataclass(frozen=True)
class Problem:
    message: str  # human-readable, names the offending setting
    field: str  # a stable id, e.g. "data.join", for inline marking


def problems(config: ParityConfig) -> list[Problem]: ...
```

Rules are cross-field config constraints that `ParityConfig` cannot express on its own
(each section validates in isolation). **First rule:**

> **Same-file join.** If `ref` and `test` resolve to the *same* file and `join` is set →
> a `Problem("ref and test are the same file; a join is meaningless there — clear the join
> to pair by row order, or point ref/test at different files", field="data.join")`.

The module is designed to grow: `problems()` is a list, more rules append. Rules operate on
the resolved config; they do not open files.

### How problems surface (level b)

- **Status bar** (the existing persistent, colour-coded bar) shows the first problem in red,
  the same channel `state.last_error` already uses. `state.last_error` (load/build failures)
  and validation problems are unified: the bar shows whichever is present.
- **Writes are blocked.** Auto-save is *withheld* and *Save As* is *disabled* while any hard
  problem (or `last_error`) stands. This is the same "never persist a knowingly-broken
  config" rule, applied to both the automatic and manual write paths.
- **The offending field is marked.** For v1 this is done where the owning panel can reach
  its own widget: the **data panel marks the `join` select** (red `error` prop) when a
  `field == "data.join"` problem is present. `Problem.field` is defined for every rule so
  further inline marks are a mechanical addition, not a redesign.

## Panel re-sync

Opening a config or New Design swaps the whole `config` (and `data`), but the panel widgets
captured their values at **build time**. The left **settings column is wrapped in a
`@ui.refreshable`** function; a config swap mutates `state` in place (new method
`state.load_session_config(...)`) and calls `.refresh()` on the column, rebuilding the panels
from the new config. The plot, selection, inspector, and table on the right are untouched, so
a config swap does not blow away what the user was looking at.

## The clear-to-default fix

Two parts, both in the controls/state path:

1. **Clearing actually reverts.** `ParityConfig.merge` must not be asked to set `None` (it
   drops it). Add `DesignerState.reset_fields(section, *keys)` that rebuilds the section via
   `dataclasses.replace(section_obj, **{key: <dataclass default>})` and revalidates. When
   `controls._clean` yields `None` (a blanked field), the control calls `reset_fields`
   instead of `update(key=None)`. `merge` stays unchanged, so the CLI's "omitted flag =
   skip" semantics are preserved. This also fixes clearing `join` / `color_column` in the
   data panel by the same route.
2. **A dimmed default is shown.** Text controls whose effective default is meaningful get a
   **placeholder**:
   - `x_label` / `y_label` → the resolved column name (`state.data.x_label` /
     `data.y_label`) when data is loaded, else `"column name"`.
   - other text fields with a non-empty dataclass default (e.g. `title` → `"Parity Plot"`) →
     that default, shown dimmed.

   `ControlSpec` gains an optional placeholder resolver; `x_label`/`y_label` are the only
   data-derived cases and are computed in `build_controls` from `state.data`.

## Architecture / where things live

Following the project's rule — logic in browser-free, tested modules; `app.py`/panels only
wire widgets:

| Concern | Home | Tested by |
| --- | --- | --- |
| Candidate config discovery | `session.py`: `config_choices(dir)` | unit test on a temp dir of good/bad `.toml` |
| Cross-field validation | `designer/validation.py`: `problems(config)` | unit test per rule |
| Bind / swap config | `session.py` (`config_path` already there) + `state.load_session_config` | unit test on Session |
| Auto-save trigger | `session.autosave(config)` — writes iff bound; app calls it from `refresh()` when no problem stands | unit test on Session (bound writes, unbound no-ops, invalid withheld) |
| Clear-to-default | `state.reset_fields` + `controls._clean` routing | unit test on State + a controls test |
| Toolbar, refreshable column, field marking | `app.py`, `panels/` | golden-WYSIWYG + app-boot subprocess test |

`app.refresh()` becomes the single place that, after every change: rebuilds the figure,
computes `problems(config)`, paints the status bar, enables/disables *Save As*, marks the
join field, and — when nothing is wrong and a file is bound — **auto-saves**.

## Error handling

- A hard validation problem or a load/build error → withhold auto-save, disable *Save As*,
  red status bar, mark field. The last valid config stays on disk.
- *Save As* to a path whose directory is missing → `mkdir -p` (as today).
- Auto-save write failure (`OSError`, e.g. permissions) → red status bar, no crash; the
  in-memory config is unaffected and the next successful edit retries.
- Selecting a config that fails to load (race: deleted/edited to invalid between scan and
  click) → status bar error, selection reverts to the previous entry; no data lost.

## Testing

- **`validation.problems`** — same-file + join → one problem; different files + join → none;
  same file, no join → none; no ref/test yet → none.
- **`config_choices`** — a dir with a valid config, a `.toml` lacking `data.files`, a
  malformed `.toml`, and a non-`.toml` → only the valid config returned.
- **`Session.autosave`** — bound + valid writes and updates `disk_text`; unbound is a no-op;
  called with a config carrying a problem is never reached (app gates it) — tested at the app
  seam via the predicate.
- **`state.reset_fields`** — clearing `x_label` returns `PlotConfig.x_label` to `None`;
  clearing `join` returns it to `None`; the rest of the section survives.
- **Golden WYSIWYG stays green** — auto-save must serialize exactly what the preview renders;
  the existing `test_golden_wysiwyg.py` equality guards it. A config written by auto-save,
  reloaded, must render identically.
- **App-boot subprocess test** stays green (the toolbar/refreshable wiring must not crash the
  page).

## Non-goals (deferred)

- **Bidirectional live editing** (GUI ⇄ external text editor, both open, changes merged
  live). The user wants it but accepts the complexity — especially reconciling it with
  keystroke-granular auto-save — is out of scope here. The designer owns the file while open.
- **Inline red marking of every field.** v1 marks `join` (the worked example); the framework
  returns `field`-tagged problems so the rest is incremental.
- **Debounce policy tuning.** Selects/switches/numbers auto-save on change; text inputs
  auto-save on blur / short debounce so half-typed labels are not written mid-word. Exact
  timing is an implementation detail, not a design decision.

## Open risks

- **Auto-save write frequency** on text fields — mitigated by committing text on blur/debounce
  rather than per-keystroke. Small TOML, local disk; not a real performance concern.
- **Retiring the stale guard** means an external edit made while the designer is open is
  overwritten on the next auto-save. Accepted (bidirectional editing is the deferred proper
  fix).
