# Review of the bug-scan follow-up — 2026-09-27

Checks `e4eab91` ("Fix designer races, silent failures and NFS stalls") against
`docs/bug-scan-followup-2026-09-26.md`. On `main` @ `d293662`: **896 passed**,
`./check-tier-1` passes.

Evidence tags as before: **[repro]** reproduced with a script (session
scratchpad), **[code]** confirmed by reading the path end to end.

## Verdict

Most fixes are sound. These check out:
- `sync_refresher`, and `filterwarnings = error::RuntimeWarning`.
- The prepare/commit split for lost updates and out-of-order loads.
- Atomic write and process-wide lock.
- `DataError` for non-UTF-8 and malformed CSVs.
- The select option gap.
- File-browser `OSError` handling and symlinks.
- Preview generation, dialog cleanup, and CSS added once.
- `offload`'s None handling.

But one P0 was never fixed: it predates the follow-up and was missed by the
original scan too. Several of the new mechanisms also have gaps that matter
most on NFS. Details below, in priority order.

## P0

- [ ] **Save As, New Design and opening a config all crash; the picker is never
  populated.** [repro] `app.py:563-573`: `_spawn(corofn)` calls
  `corofn()`, but four of the five call sites pass a coroutine *object*:
  `_spawn(_open_named_now(name))` (545, 548), `_spawn(do_new())` (559, 561),
  `_spawn(_save_from_input(target))` (622) and `_spawn(refresh_picker())` (499).
  Each raises `TypeError: 'coroutine' object is not callable` inside a button
  handler, so the error goes to the server log only. Consequences:
  - An unbound design (data-only launch, New Design) **can never be saved**.
    Save As is the only way to bind it, and it closes the dialog and does
    nothing.
  - The picker is seeded with only the current config (`app.py:419`), and its
    only refresh path is `_sync_picker` → `_spawn(refresh_picker())`, which
    raises. So no other config is ever listed.
  - The "two quick config picks race — fixed" item is therefore unreachable
    code.

  This came from the original uncommitted NFS diff (`v0.10.0` had no `_spawn`).
  The first scan missed it; the background code-review tracer caught it as C1,
  but that report came in after the list was written.
  - Fix: `_spawn(coro)` → `background_tasks.create(coro, ...)`, change the one
    function-passing site to `_spawn(refresh())` (633), and spawn
    `refresh_picker()` once at page build so the picker lists configs.
  - Test: nothing drives the assembled page's toolbar. Add a test that
    builds the handlers (or extracts them to a testable module) and runs Save
    As and open. `filterwarnings=error` only guards code the suite executes.

## P1 — the new concurrency code

- [ ] **`Debouncer` drops a request made while a save is in flight.** [repro]
  `session.py:211-237`. `_fire` takes `_pending` *before* the (slow, offloaded)
  write. A `schedule()` that arrives during the write sees the task not done
  and returns, and `_fire` never looks at `_pending` again. Repro: schedule A,
  wait out the delay, schedule B during A's write, and only A is ever written.
  On NFS the write window is exactly when the user keeps typing. The bound
  file then lags the last valid config until some later edit happens.
  - Fix: loop in `_fire` (`while self._pending is not None: sleep; take; work`).

- [ ] **A pending auto-save is discarded on config swap and on shutdown.**
  [code] `_swap` calls `autosave.cancel()` (`app.py:508`), so the last ≤400 ms
  of edits never reach the old file. Cancel was needed only because
  `_autosave_now` resolves `sess["session"]` at *fire* time (`app.py:377`), so
  an un-cancelled save would land in the *new* file. Nothing flushes on
  shutdown either.
  - Fix: bind the session when scheduling (`schedule(session, config)`),
    `await autosave.flush()` in `_swap` instead of cancelling, and flush from
    `app.on_shutdown`.

- [ ] **`CommitGate` catch-up re-runs the *first* work item and drops the
  rest.** [repro] `data_panel.py:125-151`. `submit` while running only sets
  `_queued`, and `_drain` loops on its original `work`:
  - A second Add File during the first one's load is lost. Repro: `b.csv` is
    never added, rendered or loaded.
  - A Reference change queued behind a group-change `apply` runs as `apply`,
    not `_reapply`. Group and hover options are then not re-derived, and a
    pinned hover column from the old ref file fails `_validate_hover`
    ("backs neither ref nor test").
  - `_remove` (`on_click=lambda _, p=f: _remove(p)`) bypasses the gate
    entirely. It runs concurrently with a drain, and a double-click raises
    `ValueError` from `files.remove`.
  - Fix: mutate `files` synchronously in `_pick_file`/`_remove`, then submit
    an idempotent resync that reads the current widgets. Have the queued slot
    keep the *strongest* pending work (resync > `_reapply` > `apply`) rather
    than a bool. Route `_remove` through the gate.

- [ ] **A config swap can still be overwritten by the old panel.** [code]
  The generation is claimed in `apply()` (`data_panel.py:528`), *after*
  `_reapply`'s `await refresh_dependent()` and `_add`/`_remove`'s
  `await refresh_options()`. If the swap lands during that `column_options`
  read, the old drain resumes, claims a *post-swap* generation, and commits the
  old widgets' `[data]` (old `files` closure, deleted selects) into the new
  config. The auto-save then writes it to the new file. The follow-up closes
  this for a swap during the *load*, but not during the option read before it.
  - Fix: capture a config epoch when the panel is built (bumped by
    `load_session_config`). `apply` bails if it moved, and
    `commit_data_source` checks it too.

- [ ] **Parse cache can serve a stale file indefinitely.** [repro]
  `sources.py` `_store` stats *after* `_read_rows`. If a writer lands between
  the read and the stat, the old rows are cached under the new stamp and every
  later call hits. Repro: 2 rows on disk, 1 row served. This is common when a
  simulation on another host writes the CSV while the designer reads it.
  - Fix: stat before the read, re-stat after, and store only if both stamps
    match.
  - Also, on NFS, `stat()` is served from the attribute cache (up to
    `acregmax`, typically 60 s) without close-to-open revalidation. Before the
    cache, `open()` forced revalidation, so a file regenerated elsewhere can now
    show old data for up to a minute. Consider `open()`+`os.fstat()` for the
    stamp, which revalidates, and/or a "Reload data" action calling
    `clear_cache()`.

- [ ] **Any cache miss re-reads every file.** [code] `open_sources` falls
  back to reading *all* of `order` when `_lookup` misses on any one file. So
  Add File with N files open still reads N+1 in full: the exact NFS hang path.
  The docstring says misses are re-read "individually", which is not what the
  loop does.
  - Fix: per-file lookup inside the read loop.

- [ ] **Initial option load guesses ref/test without committing them.** [code]
  The data panel now spawns `refresh_options()` at build (`data_panel.py:581`).
  Its ref/test guess runs under `gate.suspend()` (425-430), and nothing applies
  afterwards. So with `parity-plot design a.csv b.csv` (two files →
  `Session.start` derives no ref/test), or any config with files but no
  ref/test, the selects show columns while `state.config` has none. The plot
  stays blank and the status says "Ready". The comment at 574 also claims
  this call is "Gated like any other commit"; it is not submitted through the
  gate.
  - Fix: skip guessing on the build-time derivation, or `gate.submit(apply)`
    after a guess, outside the suspension.

- [ ] **`_options()` doesn't pass group/colour/hover to `column_options`.**
  [code] `data_panel.py:450-456` passes only ref/test/join, so `_offer` cannot
  keep the configured colour, group and hover values:
  - `color_sel.update()` resets an un-derivable colour column (path form,
    repeated basename) to `None` in the UI.
  - On a transient read failure, the hover candidates come back empty and
    `_refresh_hover` **prunes the pinned hover columns**. The next successful
    data edit commits `hover_columns=()` and auto-saves it, so a momentary NFS
    glitch erases the user's pins from the TOML.
  - Fix: pass `group=`, `color_column=`, `hover_columns=` from the widgets;
    don't prune on the fallback path (have `column_options` say it fell back).

- [ ] **Atomic save breaks symlinked configs and drops file mode.** [repro]
  `os.replace` onto `link.toml` replaced the *symlink* with a regular file, and
  the real target was not updated (repro). The temp file is also created
  with the process umask, so a group-writable 0664 TOML in a shared NFS project
  dir comes back 0644.
  - Fix: `target = target.resolve()` before writing, and copy the existing
    mode onto the temp file (`os.chmod(temp, st.st_mode)`) before
    `os.replace`.

- [ ] **Auto-save raises on a hand-broken TOML.** [repro] `autosave` catches
  only `OSError`. `config_to_toml(existing=...)` on a file the user left
  mid-edit raises `tomlkit…ParseError` (a `ValueError`), which kills the
  debouncer task with nothing in the status bar.
  - Fix: catch `ValueError` too and report it ("could not merge into
    parity.toml: …").

## P2

- [ ] **NaN regression with custom `na_values`.** [repro] `_require_numeric`
  and `sources._is_numeric` now use `math.isfinite`, which rejects NaN as well
  as infinities. With `na_values` lacking `"nan"`, a `NaN` cell errors as
  `test column 'b' is infinite ('NaN')`. v0.10.0 (and CLAUDE.md: "only `None`
  and NaN mean missing") treat it as missing, and `_color_value` still does.
  - Fix: test `math.isinf`, not `not math.isfinite`, in both places.
- [ ] **Table filter switches go stale on swap.** [code] `load_session_config`
  resets `state.filters`, but `build_table`'s "Failures only"/"Include unpaired"
  switches are never re-synced (`table.py:34-35`). The next toggle silently
  re-applies the old filter.
  - Fix: set the switch values from `state.filters` in `refresh()` under a
    guard.
- [ ] **`offload` returns `None` on cancellation.** [code] NiceGUI's `_run`
  swallows `CancelledError` and returns `None`. Now that `offload` only raises
  when `is_stopping`, a cancelled caller gets `None` cast as its result, and
  `new_session, cfg, new_data = await offload(Session.start, …)` would raise
  `TypeError`. Rare (no current caller is cancelled except the debouncer),
  but the cast hides it.
  - Fix: raise `CancelledError` when the result is `None` and the current task
    is cancelling.
- [ ] **Doc and comment drift.** The follow-up doc marks "two quick config
  picks race" as fixed (unreachable, see P0), and says a cache miss re-reads
  only the misses (it re-reads everything). The comment at
  `data_panel.py:574-575` ("Gated like any other commit") is wrong. The
  `offload` docstring (`io.py:75-77`) has a stray extra indent.
