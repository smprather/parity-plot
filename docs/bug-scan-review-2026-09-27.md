# Review of the bug-scan follow-up — 2026-09-27

Review of commit `e4eab91` ("Fix designer races, silent failures and NFS
stalls") against `docs/bug-scan-2026-09-26.md` and the claims in
`docs/bug-scan-followup-2026-09-26.md`. Every finding below was reproduced
before it was fixed: in a real browser (Playwright driving `parity-plot design`
on port 8085), in-process (the real panel inside a NiceGUI `Client`), or with a
script against the library. Each fix landed with a test that fails on `e4eab91`
and passes after.

Suite: **896 → 917 passed**; `./check-tier-1` clean.

## Summary

| # | Finding | Severity | Status |
| --- | --- | --- | --- |
| 1 | Save As, New Design and opening a config all raise on click | **P0** | fixed |
| 2 | The config picker never lists anything but the open config | **P0** | fixed |
| 3 | A config swap during the data panel's pre-commit read is overwritten | **P0** (scan item only partly fixed) | fixed |
| 4 | An edit made while an auto-save is in flight is never written | P1 | fixed |
| 5 | A config swap drops the last edit instead of saving it | P1 | fixed |
| 6 | Page load shows a guessed ref/test the state never received | P1 (new regression) | fixed |
| 7 | A literal `NaN` cell errors as "infinite" under custom `na_values` | P1 (new regression, CLI too) | fixed |
| 8 | Option refresh resets the configured colour column; a failed read wipes pinned hover columns | P2 | fixed |
| 9 | Picker value set before its options can reset to None and "pick" None | P2 | fixed |
| 10 | A queued auto-save can undo a concurrent Save As | P2 | fixed |
| 11 | The sources cache stamps after the read, so a concurrent rewrite pins stale data | P2 | fixed |
| 12 | Atomic save replaces a symlinked config with a private copy and drops its mode | P2 | fixed |
| 13 | File remove bypasses the `CommitGate` | P3 | fixed |
| 14 | A sync `on_change` is documented as legal but `await None` raises | P3 | fixed |
| 15 | "App-level refresh lock" guards nothing | note | documented |

## The P0s

### 1. `_spawn` called its argument; every caller passed a coroutine

`app._spawn(corofn)` did `background_tasks.create(corofn(), …)`, and five of its
six call sites were `_spawn(refresh_picker())`, `_spawn(do_new())`,
`_spawn(_open_named_now(name))`, `_spawn(_save_from_input(target))`. Each raised
`TypeError: 'coroutine' object is not callable` inside a click handler, where
NiceGUI logs and swallows it. In the browser: **Save As wrote nothing and the
status bar still said "Ready"**; New Design did nothing; picking a config did
nothing. Only the initial paint (`_spawn(refresh)`) worked.

This is the same class as the scan's first P0 — a dropped coroutine — and the
`error::RuntimeWarning` filter added for that one could not catch it, because no
test drove the assembled page. The follow-up doc says as much ("the assembled
page is not driven by any other test"); that gap is the finding.

Fix: `_spawn` takes the coroutine. New `tests/designer/test_app_toolbar.py`
builds the real page in-process (captures `build_app`'s page function, builds it
in a `Client` with `core.loop` set) and clicks through NiceGUI's own event
dispatch — the harness that was missing.

### 2. The picker was seeded with the current config and never re-listed

To keep `config_choices` off the loop, the picker is now built with
`[current_choice()]` and "`refresh_picker` fills it in once the page is up" —
but nothing spawned `refresh_picker` at page load. It ran only from
`_sync_picker`, i.e. after an open/Save As/New Design, all of which were dead
(#1). Net effect: there was no way to open another config.

Fix: spawn `refresh_picker()` with the initial paint.

### 3. The swap guard was claimed too late

The generation that protects a commit is claimed in `apply()`. But `_add`,
`_remove` and `_reapply` each await an option read (`refresh_options` /
`refresh_dependent`) *before* calling `apply()`. A config opened during that
read bumps the generation, and then the old panel claims a fresh one — current
by construction — and commits its `[data]` into the new config, then refreshes,
which auto-saves it into the new file. Reproduced in-process: design B kept its
title but ended with design A's files and columns.

The scan's own words for this P0 were "a pre-swap load … auto-saving it over the
newly opened file"; the fix preserved B's `[plot]` but not its `[data]`.

Fix: `DesignerState.config_epoch`, bumped only by `load_session_config`. A panel
records it at build and `apply()` refuses to commit once it has moved — checked
synchronously right before the generation is claimed, so there is no window.

## Auto-save

**4.** `Debouncer._fire` ran once: a `schedule()` arriving while the (offloaded)
save was in flight found a live task, parked in `_pending`, and was never picked
up. On NFS the save outlasts the 400 ms delay, so this is the common case, and
it breaks the headline guarantee that the bound file holds the latest valid
config. Fix: the task loops until nothing is pending.

**5.** `_swap` called `autosave.cancel()`, because the save looked the session up
when it fired and would otherwise have written the old design into the new file.
But cancelling drops the user's last edit (and, with #4, possibly several).
Fix: bind the session when the save is *scheduled*, and `await autosave.flush()`
on swap — the old design's last edit goes to the old file. The flush drains
anything scheduled while it ran, and because it awaits, `_swap` re-checks the
open generation after it; without that re-check two quick picks could land in
either order (a test pins the last pick winning while the first one's flush is
still writing).

**10.** Saves now run in worker threads. `autosave` read `self.config_path`
before waiting on `_SAVE_LOCK`, so one queued behind a Save As wrote the old
file and re-bound the session back to it. Fix: path and dirty check are read
under the lock.

**12.** `os.replace` over a symlink replaces the link. A `parity.toml` linked into
a shared area became a private copy and the shared file stopped changing; the
temp file's umask mode also replaced the original's. Fix: resolve the target,
copy its mode to the temp file.

## Data panel

**6.** The page-load `refresh_options()` (new in `e4eab91`) also guesses ref/test,
under suspension, with no commit after it. Launch with files but no axes
(`parity-plot design a.csv b.csv`): the selects show `a.csv:r` / `a.csv:t`, the
state has neither, the plot is empty, and re-picking the same value emits
nothing. Fix: guess only in `_add`/`_remove`, which commit.

**8.** `_options()` never passed `group`/`color_column` to `column_options`, so the
`_offer` fallback added for exactly this case was dead on the panel's path. A
single select whose value leaves its options resets to None — so a path-form
colour column, or any file briefly unreadable at page load, blanked the colour
select. The same failed read returned no hover candidates and `_refresh_hover`
pruned every pin against that empty list; the next data edit saved the loss.
Fix: pass the current values; `read_column_options` returns a `readable` flag
and pruning happens only after a successful read.

**9.** `_sync_picker` set the picker's value before its options held it (after
Save As to a new name, or New Design's `‹unsaved›`); `ChoiceElement.update()`
then resets it to None, which is reported as a change, i.e. `open_named(None)`.
Fix: `set_options(options, value=…)` in one call, options built on the loop from
the session as it is now; `open_named` ignores a falsy name.

**13.** The remove button called `_remove` directly — the one commit path outside
the `CommitGate` — so it could run beside a gated commit, and the older of two
option refreshes could land last.

**14.** `build_data_panel` documents `on_change` as "sync or async" and
`test_build_data_panel_accepts_a_sync_callback` exists for it, but the commit did
`await on_change()`; a sync callback raised `'NoneType' object can't be awaited`
in a background task. The existing test only built the panel.

## Library

**7.** `_require_numeric` screened with `math.isfinite`, which rejects NaN as well
as infinity. The default `na_values` include `nan`, so this was hidden; with a
trimmed list (`na_values = ["", "NA"]`) a `NaN` cell — a null by the project's
own convention, and to `_parse` — failed the CLI with "ref column 'ref' is
infinite ('NaN')". Fix: `isinf`.

**11.** `open_sources` stat'ed each file *after* reading it, so a file rewritten
mid-read was cached with its old rows under its new `(mtime_ns, size)` and
served until it changed again. Fix: stamp before the read.

## Notes, not changed

- **15.** The follow-up says moving `_refresh_lock` to app scope means "two tabs
  can no longer interleave half-applied states". `refresh()`'s body has no
  `await`, so it could never interleave; the lock is inert either way. Harmless,
  but the multi-tab item is less "partly fixed" than the doc suggests.
- NFS attribute caching: the cache key is a `stat()`, which does not force the
  close-to-open revalidation an `open()` does, so on NFS a file rewritten on
  another host can look unchanged for up to `acregmax` (60 s by default).
  Acceptable for a designer, but worth knowing when a regenerated CSV "doesn't
  show up".
- After Save As the status bar shows "Ready", not "✅ Saved": `save_as` paints
  the message and then immediately `refresh()`es. Pre-existing (the pre-`e4eab91`
  code did the same); the toast still shows.
- The follow-up's other claims held up: the prepare/commit split, `CommitGate`,
  atomic writes, decode-error handling, symlinks in the file browser, and the
  finite colour channel all behave as described.
