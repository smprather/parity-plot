# Bug scan followup — 2026-09-26

Work against `docs/bug-scan-2026-09-26.md`. Every item was done test-first: a
failing test that reproduced the reported behaviour, then the fix, then the
full suite. `./check-tier-1` passes; the suite is **890 passed** (up from 785
at the start, and 849 at the point the P0 work landed).

Two items are not closed, both called out under *Not done* with the reason.

## Summary

| Item | Status |
| --- | --- |
| P0 · non-data panels never refresh or auto-save | **fixed** |
| P0 · Add File fans out into ~6 reads | **fixed** |
| P0 · edits during a slow load are reverted | **fixed** |
| P0 · config swap overwritten by an in-flight load | **fixed** |
| P0 · out-of-order loads: older beats newer | **fixed** |
| P1 · data panel build reads every CSV on the loop | **fixed** |
| P1 · config picker parses every TOML on the loop | **fixed** (offloaded; not mtime-cached) |
| P1 · auto-save: 3–4 round trips per refresh | **fixed** (skip-clean + debounce) |
| P1 · auto-save failure invisible | **fixed** |
| P1 · config writes not atomic | **fixed** |
| P1 · GIL-bound parsing on big files | *not attempted* — see below |
| P1 · HTTP 500 when a value is not among the options | **fixed** |
| P1 · non-UTF-8 / malformed CSVs escape raw | **fixed** |
| P1 · file browser only handles `NotADirectoryError` | **fixed** |
| P1 · symlinked CSVs invisible | **fixed** |
| P1 · `color_column` lets inf/nan through | **fixed** |
| P2 · multiple tabs share state, per-tab lock | **partly fixed** |
| P2 · two quick config picks race | **fixed** |
| P2 · dialogs and CSS leak | **fixed** |
| P2 · preview grids can stack | **fixed** |
| P2 · `offload` treats a legitimate None as shutdown | **fixed** |

## What changed, and why

### The P0 that hid behind a passing suite

The root cause of the first item is worth writing down, because nothing about it
was visible from a test failure. `refresh` became `async` in the uncommitted
NFS work, and the six sync panels were handed the coroutine function directly.
Each panel calls `on_change()` from a *sync* commit and drops the return value,
so the coroutine was created and garbage collected: no redraw, no status bar, no
auto-save, and one `RuntimeWarning` per edit in a log nobody reads.

It type-checked because the same NFS work widened every panel's `on_change` from
`Callable[[], None]` to `Callable[[], Any]`. That widening is what let the async
function through the type checker while the runtime contract ("call it and
forget it") stayed synchronous. `Callable[..., Any]` describes what these
panels *do*; it just does not catch that `refresh` is not a `None`-returning
function any more.

Two fixes, deliberately:

- `io.sync_refresher` adapts a possibly-async `on_change` for a sync commit, and
  `app.settings_column` now passes that to every sync-commit panel. The data
  panel keeps the coroutine function because it genuinely awaits it.
- `filterwarnings = ["error::RuntimeWarning"]` in `pyproject.toml`, so a dropped
  coroutine anywhere in the suite is a failure rather than a log line. This is
  the general guard; the shim is the specific fix.

One test is a source-level pin (`test_every_sync_commit_panel_is_wired_through_the_shim`)
because which callback each panel receives is decided inside `build_app`, and
the assembled page is not driven by any other test. The behaviour it guards is
covered end to end by driving a real panel commit.

### Splitting the data-source change in two

The other three P0s are one mechanism: `set_data_source` ran in a worker thread
and did the whole job there — snapshot the config, read every CSV, then assign
`self.config = candidate`. Snapshot and assignment straddled the read, so
anything done on the loop in between was reverted.

`state.py` now has `begin_data_source()` / `prepare_data_source()` /
`commit_data_source()`. `prepare` is pure: it validates, loads, and returns a
`PreparedData` description without touching state. `commit` runs on the loop,
merges **only the `[data]` section** into whatever the config has become by
then, and drops the result if the generation it was prepared under has moved.
`load_session_config` bumps that generation, which is what stops a pre-swap load
from putting the old design back and then auto-saving it over the new file.

`set_data_source` remains as the synchronous one-call form (begin → prepare →
commit) for the non-UI callers and the existing tests.

Two details that fell out of the split and are worth knowing:

- `merge` drops a `None` override by design, which is right for a CLI and wrong
  for a designer. "No ref selected" and "no colour column" are real states, so
  the panel now routes them through `clear`. **This fixes a bug the scan did not
  list**: before, choosing "— none —" for the colour column left the previous
  column in place, because the `None` was dropped.
- `prepare_data_source` takes no generation. A stale result is caught at commit
  time, where the loop can act on it, and a worker thread cannot usefully cancel
  itself.

### The Add File fan-out: a guard checked too late

`refresh_options` raised the suspension flag, assigned `ref_sel.value` and
`test_sel.value`, and lowered it *before any await* — and NiceGUI calls an event
handler synchronously, only scheduling it if it returns an awaitable. So every
guarded emission re-entered the commit with the guard already down.

`CommitGate` (`panels/data_panel.py`) fixes this by checking the guard from a
**sync** wrapper, while the emitting frame is still on the stack, and it
collapses a burst of edits into one commit plus one catch-up that re-reads the
widgets. So the newest choice lands and the reads are serialised rather than
piled onto the thread pool. The suspension also now covers the `update()` calls,
which can themselves reset a select and re-emit.

`CommitGate` is a standalone class with an injectable `spawn`, so all of it is
tested without a browser.

### NFS: reads off the loop, writes made cheap and safe

- `open_sources` caches parsed files against `(path, mtime_ns, size)`. The stat
  is one cheap round trip against the full read it saves. `mtime_ns` rather than
  seconds because a same-size rewrite within one second is exactly the case a
  size check alone would miss. Bounded (`CACHE_LIMIT = 8`), with `clear_cache()`
  for tests. The first implementation had a real bug — an early `break` could
  return a *partial* `Sources` as if it were complete — so the lookup is
  all-or-nothing per call, and per-file misses are stored so the next call hits.
- `build_data_panel` builds its selects from the current values alone and
  derives the real lists afterwards via `create_or_defer` (not `create`: the
  panel is also built without a running loop).
- Auto-save: skips an unchanged config, debounced 400 ms with the value read at
  fire time, run off the refresh lock and off the event loop. The views refresh
  *before* the write, and `autosave` returns an error message instead of raising
  — a raise there aborted the rest of the refresh, which is how the failure
  became invisible in the first place.
- Writes are atomic: a sibling temp file plus `os.replace`, under a
  process-wide lock, with the temp file removed on every failure path. The
  config is marked clean only *after* the swap, so a failed save stays dirty and
  is retried.

## Not done

**P1 · GIL-bound parsing on large files.** The scan marked this `[plausible]`
and conditioned the fix on measurement ("check with `--debug` timings"). The
fan-out collapse and the parse cache are most of the cure and both are in; what
remains is `run.cpu_bound` for the load, and adding that before measuring would
be guessing. Worth a `--debug` run against a real large CSV.

**P2 · multiple tabs.** I moved the refresh lock to app scope, so two tabs can no
longer interleave half-applied states — that was the cheaper half of the fix and
it is done. The rest is not: an edit in tab A still does not repaint tab B, and
tab B's next data edit re-commits its own stale `files` list over A's. The real
answer is per-client state, which is a redesign of the session ownership, not a
patch. I judged it out of scope for a bug-fix pass and did not want to
half-do it.

## Two bugs found while working, not in the scan

- **Clearing the colour column did nothing.** `merge` drops a `None` override,
  so the panel's `color_column=None` kept the stale column. Fixed via `clear`
  (see above); `test_a_none_override_alone_does_not_clear` pins why.
- **`_row_limit(0)` returned 100.** `int(value or 100)` turns a legitimate `0`
  into the default instead of clamping it to 1. A latent bug inherited from the
  code I was rewriting.

## Two dead things removed

- `open_sources(paths, na_values=...)` never used `na_values`; both callers
  passed it, so it read as though it did something. Removed, and both call sites
  with it.
- `io.offload` treated *any* `None` result as a cancelled call, which is why
  `refresh` had to call `save` instead of `autosave` with a comment explaining
  the workaround. It now tests `core.app.is_stopping` and `cast`s, so a
  callable that genuinely returns `None` is legal.

## Tests added

All new; every one was written before the fix and watched fail.

`tests/designer/` — `test_sync_refresher.py` (the async `on_change` regression),
`test_commit_gate.py` (guard and coalescing), `test_state_prepare_commit.py`
(the three races, modelled deterministically), `test_select_option_gap.py` (the
500), `test_autosave.py` (atomicity, skip-clean, debounce, error reporting),
`test_widgets.py` (`as_float`/`as_int`), `test_filebrowser_symlinks.py`.
`tests/` — `test_finite_values.py` (colour channel + `_clean`),
`test_csv_decode_errors.py` (all three readers),
`test_sources_cache.py` (hit, invalidation, bound, deletion).

`pyproject.toml` gained `filterwarnings = ["error::RuntimeWarning"]`.

## Feedback on the scan

The scan was accurate and unusually well-localised — the line numbers and the
mechanisms held up on essentially every item, and the three P0 races really were
one bug. Things that would have helped:

- **Group the items by mechanism, not by symptom.** Three P0s were one split in
  `set_data_source`, and the fix is a single refactor. Listing them separately
  implied three fixes.
- **Mark which findings are speculative.** The `[plausible]` tag exists but only
  one item used it. "GIL-bound parsing" is the item I skipped, and knowing it
  was unmeasured is what made skipping it a decision rather than a shortcut.
- **Note the type system interaction.** The first P0 passed `ty` *because* the
  same branch widened `on_change` to `Any`. A finding that is invisible to both
  the suite and the checker is worth flagging as such — it is a different kind
  of bug from "the tests do not cover this".
- **The P2 list is where the judgement calls are.** Four of the five are cheap;
  the multi-tab one is a redesign. Flagging that up front would have saved
  deciding mid-pass.

## Tooling note

`pi-lens` reported `unresolved-reference` for
`from parity_plot.designer.widgets import ...` long after the module existed.
Disproven four ways: the file is on disk, it imports under the venv interpreter,
its 26 tests pass, and an active LSP probe (`source: lsp`, `mode: full`) returns
`clean=2, findings=0`. The session-cached analyzer had not invalidated its entry.
Worth knowing if the same false positive turns up again.

Its `unchecked-throwing-call-python` ast-grep rule did point at three genuine
crash paths while I was in the area, though: `int()`/`float()` on a
free-typed `ui.number` value, where an exception inside a sync handler is
invisible. That became `designer/widgets.py`. So the rule is worth its false
positives.
