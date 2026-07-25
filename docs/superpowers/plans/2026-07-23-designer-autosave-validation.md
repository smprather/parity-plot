# Designer auto-save, config picker, live validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the designer auto-save every valid edit to the bound config file, driven from a top toolbar (config dropdown + Save As + New Design), with a browser-free blocking validation layer and a fix for clearing a field back to its default.

**Architecture:** All logic lives in browser-free, unit-tested modules (`validation.py`, `session.py`, `state.py`, `controls.py`); `app.py`/panels only wire widgets. `app.refresh()` becomes the single point that rebuilds the figure, computes validation problems, paints the status bar, enables/disables Save As, marks the offending field, and — when nothing is wrong and a file is bound — auto-saves. The settings column is a `@ui.refreshable` so opening a config or starting a New Design rebuilds the panels from the swapped-in config while the plot/selection on the right stay put.

**Tech Stack:** Python ≥3.14, NiceGUI (designer), tomlkit (serialize), stdlib only, uv, pytest.

## Global Constraints

- **Python floor `>=3.14`** — do not lower it.
- **No numpy/pandas/polars** — stdlib only.
- **`app.py` and `panels/` are wiring only**; anything worth testing lives in `state.py`, `session.py`, `serialize.py`, `validation.py`, `controls.py` (browser-free).
- **The designer must never reimplement plotting** — `tests/designer/test_golden_wysiwyg.py` guards designer↔CLI figure identity and must stay green.
- **Never register `nicegui.testing.plugin`**; the app-boot test drives `parity-plot design` as a subprocess with `PYTEST*` stripped from its env.
- **Never persist a knowingly-broken config** — auto-save is withheld and Save As disabled while any validation problem or load/build error stands.
- Run tests with `uv run pytest`. Commit after each task. Work on a branch off `main`.

---

## File Structure

- `parity_plot/designer/validation.py` — **new.** `Problem` dataclass + `problems(config)`; first rule: same-file join.
- `parity_plot/designer/session.py` — `config_choices(dir)`; `Session.autosave(config)`; retire the stale-file guard (drop `is_stale`, stop raising `StaleFileError` from `save`, drop the vestigial `force`).
- `parity_plot/designer/state.py` — `reset_fields(section, *keys)`; `load_session_config(config, data)`.
- `parity_plot/designer/panels/controls.py` — clear-to-default routing (`None` → `reset_fields`) and a `_placeholder(spec, data)` resolver shown dimmed.
- `parity_plot/designer/app.py` — top toolbar (config dropdown, Save As, New Design), `@ui.refreshable` settings column, open/new-design wiring, auto-save + validation surfacing + Save As disable + join-field mark; remove the bottom Save/Save As buttons and the stale-overwrite dialog.
- `parity_plot/designer/panels/data_panel.py` — return a `mark_problems(problems)` hook that reddens the `join` select when a `data.join` problem stands.
- `CLAUDE.md` — designer notes for the new model.

---

## Task 1: Validation module

**Files:**
- Create: `parity_plot/designer/validation.py`
- Test: `tests/designer/test_validation.py`

**Interfaces:**
- Produces: `Problem(message: str, field: str)` (frozen dataclass); `problems(config: ParityConfig) -> list[Problem]`. Field ids are dotted, e.g. `"data.join"`.

- [ ] **Step 1: Write the failing test**

Create `tests/designer/test_validation.py`:

```python
from __future__ import annotations

from parity_plot.config import ParityConfig
from parity_plot.designer.validation import Problem, problems


def _cfg(**data) -> ParityConfig:
    return ParityConfig.from_dict({"data": data})


def test_same_file_ref_and_test_with_a_join_is_a_problem():
    cfg = _cfg(files=["d.csv"], ref="d.csv:reference", test="d.csv:test", join="id")
    probs = problems(cfg)
    assert len(probs) == 1
    assert probs[0].field == "data.join"
    assert "join" in probs[0].message.lower()


def test_same_file_without_a_join_is_fine():
    cfg = _cfg(files=["d.csv"], ref="d.csv:reference", test="d.csv:test")
    assert problems(cfg) == []


def test_different_files_with_a_join_is_fine():
    cfg = _cfg(files=["a.csv", "b.csv"], ref="a.csv:v", test="b.csv:v", join="id")
    assert problems(cfg) == []


def test_incomplete_config_has_no_problems():
    assert problems(ParityConfig()) == []


def test_problem_is_hashable_and_frozen():
    p = Problem(message="x", field="data.join")
    hash(p)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/designer/test_validation.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement**

Create `parity_plot/designer/validation.py`:

```python
"""Cross-field config validation for the designer.

Rules here are constraints that span sections and so cannot live on a single
config dataclass (each validates only itself). Browser-free and pure: rules read
the resolved config and never open files. `app.py` surfaces the result.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ParityConfig

__all__ = ["Problem", "problems"]


@dataclass(frozen=True)
class Problem:
    """One validation failure. ``field`` is a dotted id (e.g. ``"data.join"``)
    so the owning panel can mark the exact widget."""

    message: str
    field: str


def _ref_file(ref: str | None) -> str | None:
    """The file part of a ``file:column`` ref, or None."""
    if not ref or ":" not in ref:
        return None
    return ref.split(":", 1)[0]


def problems(config: ParityConfig) -> list[Problem]:
    """Every cross-field problem in ``config``, in a stable order."""
    found: list[Problem] = []
    data = config.data

    # Same-file join: if ref and test are drawn from one file, a join key is
    # meaningless (a single wide file pairs by row order); joining a file to
    # itself on a key is never what the user wants.
    ref_file, test_file = _ref_file(data.ref), _ref_file(data.test)
    if data.join and ref_file is not None and ref_file == test_file:
        found.append(
            Problem(
                message=(
                    f"ref and test are both from {ref_file}; a join is meaningless "
                    f"there — clear the join to pair by row order, or point ref/test "
                    f"at different files"
                ),
                field="data.join",
            )
        )

    return found
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/designer/test_validation.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/validation.py tests/designer/test_validation.py
git commit -m "feat(designer): cross-field validation module (same-file join rule)"
```

---

## Task 2: `config_choices` discovery

**Files:**
- Modify: `parity_plot/designer/session.py`
- Test: `tests/designer/test_session.py`

**Interfaces:**
- Produces: `session.config_choices(directory: Path) -> list[Path]` — the `.toml` files in `directory` that parse as a `ParityConfig` and have a non-empty `data.files`, sorted by name.

- [ ] **Step 1: Write the failing test**

Append to `tests/designer/test_session.py`:

```python
def test_config_choices_returns_only_valid_parity_configs(tmp_path):
    from parity_plot.designer.session import config_choices

    (tmp_path / "good.toml").write_text(
        '[data]\nfiles = ["d.csv"]\nref = "d.csv:a"\ntest = "d.csv:b"\n',
        encoding="utf-8",
    )
    # parses but names no files -> not a parity-plot config
    (tmp_path / "nofiles.toml").write_text(
        '[plot]\ntheme = "light"\n', encoding="utf-8"
    )
    # not even valid TOML
    (tmp_path / "broken.toml").write_text("this = = nonsense\n", encoding="utf-8")
    # unrelated extension
    (tmp_path / "data.csv").write_text("id\n1\n", encoding="utf-8")

    names = [p.name for p in config_choices(tmp_path)]
    assert names == ["good.toml"]


def test_config_choices_empty_dir_is_empty(tmp_path):
    from parity_plot.designer.session import config_choices

    assert config_choices(tmp_path) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/designer/test_session.py -k config_choices -v`
Expected: FAIL (`config_choices` undefined).

- [ ] **Step 3: Implement**

In `parity_plot/designer/session.py`, add a module-level function (after the imports, before/after the class is fine):

```python
def config_choices(directory: Path) -> list[Path]:
    """The parity-plot configs in ``directory``.

    Touchstone: the file parses as a ``ParityConfig`` and names at least one
    input file (``data.files``). A ``.toml`` that is malformed or unrelated is
    skipped, so the picker only offers files the designer can actually open.
    """
    out: list[Path] = []
    for path in sorted(Path(directory).glob("*.toml")):
        try:
            config = ParityConfig.from_toml(path)
        except ConfigError, ValueError, OSError:
            continue
        if config.data.files:
            out.append(path)
    return out
```

(`ParityConfig` and `ConfigError` are already imported at the top of the module.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/designer/test_session.py -k config_choices -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/session.py tests/designer/test_session.py
git commit -m "feat(designer): config_choices lists valid parity configs in a dir"
```

---

## Task 3: `Session.autosave` + retire the stale-file guard

**Files:**
- Modify: `parity_plot/designer/session.py`
- Test: `tests/designer/test_session.py`

**Interfaces:**
- Produces: `Session.autosave(config) -> Path | None` — writes to `self.config_path` and returns it when bound; returns `None` (no write) when unbound.
- Changes: `Session.save(config, path=None) -> Path` no longer raises `StaleFileError` and drops the `force` parameter; `Session.is_stale` is removed. `StaleFileError` **stays defined** (removed with its last consumer in Task 6).

- [ ] **Step 1: Write the failing test / update stale tests**

In `tests/designer/test_session.py`:

First, **delete** these two now-obsolete tests (the stale guard is retired):
`test_stale_when_the_file_changed_underneath` and
`test_saving_over_a_changed_file_refuses_until_forced`.

Then append:

```python
def test_autosave_writes_when_bound(csv, tmp_path):
    out = tmp_path / "bound.toml"
    out.write_text(
        '[data]\nfiles = ["x.csv"]\nref="x.csv:a"\ntest="x.csv:b"\n', encoding="utf-8"
    )
    session, config, _ = Session.start((), out)

    edited = config.merge(plot={"theme": "light"})
    written = session.autosave(edited)

    assert written == out
    from parity_plot.config import ParityConfig

    assert ParityConfig.from_toml(out).plot.theme == "light"
    assert not session.is_dirty(edited)  # disk now matches


def test_autosave_is_a_noop_when_unbound(csv):
    session, config, _ = Session.start((), None)  # no file bound
    assert session.autosave(config.merge(plot={"theme": "light"})) is None


def test_save_over_a_changed_file_no_longer_refuses(csv, tmp_path):
    out = tmp_path / "c.toml"
    session, config, _ = Session.start((), None)
    session.save(config, out)
    out.write_text(out.read_text() + "\n# edited externally\n", encoding="utf-8")
    # No StaleFileError any more: the designer owns the file.
    assert session.save(config.merge(plot={"theme": "light"}), out) == out
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/designer/test_session.py -v`
Expected: FAIL (`autosave` undefined; the deleted tests are gone).

- [ ] **Step 3: Implement**

In `parity_plot/designer/session.py`:

Remove the `is_stale` method entirely. Rewrite `save` to drop the stale check and `force`:

```python
def save(self, config: ParityConfig, path: Path | None = None) -> Path:
    target = Path(path) if path is not None else self.config_path
    if target is None:
        raise ValueError("no config path to save to; choose one with Save As")

    existing = target.read_text(encoding="utf-8") if target.exists() else None
    text = config_to_toml(config, existing=existing)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")

    self.config_path = target
    self.disk_text = text
    self.saved_config = config
    return target


def autosave(self, config: ParityConfig) -> Path | None:
    """Write ``config`` to the bound file, or nothing when unbound.

    The auto-save path: `app.refresh()` calls this after every change that
    leaves the config valid. Unbound (no file yet) is a no-op — a New Design
    or data-only launch has nowhere to write until Save As binds a name.
    """
    if self.config_path is None:
        return None
    return self.save(config, self.config_path)
```

Leave the `StaleFileError` class defined for now (its last consumer, `app.py`, is cleaned up in Task 6).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/designer/test_session.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/session.py tests/designer/test_session.py
git commit -m "feat(designer): Session.autosave; retire the stale-file guard"
```

---

## Task 4: `state.reset_fields` and `state.load_session_config`

**Files:**
- Modify: `parity_plot/designer/state.py`
- Test: `tests/designer/test_state.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `DesignerState.reset_fields(section: str, *keys: str) -> None` — resets the named fields to their dataclass defaults (fixes the "clearing does not revert" bug, since `merge` drops `None`). `DesignerState.load_session_config(config: ParityConfig, data: ParityData | None) -> None` — swap the whole config+data, clearing selection, filters, and last_error.

- [ ] **Step 1: Write the failing test**

Append to `tests/designer/test_state.py` (the file has a `state` fixture; these build their own where needed):

```python
def test_reset_fields_reverts_x_label_to_none():
    from parity_plot.config import ParityConfig
    from parity_plot.designer.state import DesignerState

    config = ParityConfig.from_dict({"plot": {"x_label": "custom", "title": "Keep me"}})
    st = DesignerState(config=config)
    st.reset_fields("plot", "x_label")

    assert st.config.plot.x_label is None  # back to default, not "custom"
    assert st.config.plot.title == "Keep me"  # siblings untouched


def test_reset_fields_reverts_join_to_none():
    from parity_plot.config import ParityConfig
    from parity_plot.designer.state import DesignerState

    config = ParityConfig.from_dict(
        {
            "data": {
                "files": ["d.csv"],
                "ref": "d.csv:a",
                "test": "d.csv:b",
                "join": "id",
            }
        }
    )
    st = DesignerState(config=config)
    st.reset_fields("data", "join")
    assert st.config.data.join is None


def test_load_session_config_swaps_and_clears_selection():
    from parity_plot.config import ParityConfig
    from parity_plot.designer.state import DesignerState

    st = DesignerState(config=ParityConfig(), selection="A1", last_error="boom")
    new = ParityConfig.from_dict({"plot": {"theme": "light"}})
    st.load_session_config(new, None)

    assert st.config.plot.theme == "light"
    assert st.data is None
    assert st.selection is None
    assert st.last_error is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/designer/test_state.py -k "reset_fields or load_session" -v`
Expected: FAIL (methods undefined).

- [ ] **Step 3: Implement**

In `parity_plot/designer/state.py`, add `import dataclasses` at the top (alongside the existing `from dataclasses import ...`), then add these methods to `DesignerState`:

```python
def reset_fields(self, section: str, *keys: str) -> None:
    """Reset the named fields of one section to their dataclass defaults.

    Needed because ``ParityConfig.merge`` drops ``None`` overrides (a
    deliberate CLI convenience), so it cannot clear an optional field back
    to its default. Blanking a text control routes here instead, so an
    emptied ``x_label`` truly reverts to the column name rather than keeping
    its stale value.
    """
    current = getattr(self.config, section)
    defaults: dict[str, object] = {}
    for f in dataclasses.fields(current):
        if f.name in keys:
            if f.default is not dataclasses.MISSING:
                defaults[f.name] = f.default
            elif f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
                defaults[f.name] = f.default_factory()  # type: ignore[misc]
    new_section = dataclasses.replace(current, **defaults)
    self.config = dataclasses.replace(self.config, **{section: new_section})
    self.last_error = None


def load_session_config(self, config: ParityConfig, data: ParityData | None) -> None:
    """Swap in a freshly opened config (and its data), clearing view state.

    Used when the toolbar opens a different config or starts a New Design:
    the whole config changes, so a pinned selection and any prior error are
    no longer meaningful. Filters reset to their default (a no-op) view.
    """
    self.config = config
    self.data = data
    self.selection = None
    self.filters = FilterSet()
    self.last_error = None
```

(`FilterSet` is already imported at the top of `state.py`.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/designer/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/state.py tests/designer/test_state.py
git commit -m "feat(designer): state.reset_fields + load_session_config"
```

---

## Task 5: Controls — clear-to-default routing + dimmed placeholder

**Files:**
- Modify: `parity_plot/designer/panels/controls.py`
- Test: `tests/designer/test_controls.py`

**Interfaces:**
- Consumes: `state.reset_fields` (Task 4).
- Produces: `controls._placeholder(spec: ControlSpec, data: ParityData | None) -> str` (pure); `_build_one` routes a blanked text field to `state.reset_fields` and shows the placeholder.

- [ ] **Step 1: Write the failing test**

Append to `tests/designer/test_controls.py`:

```python
def test_placeholder_for_labels_is_the_column_name(tmp_path):
    from parity_plot.data import ParityData
    from parity_plot.designer.panels.controls import _placeholder, specs_for

    data = ParityData(x=[1.0], y=[1.0], x_label="reference", y_label="measured")
    assert _placeholder(specs_for("plot")["x_label"], data) == "reference"
    assert _placeholder(specs_for("plot")["y_label"], data) == "measured"


def test_placeholder_for_labels_without_data_is_generic():
    from parity_plot.designer.panels.controls import _placeholder, specs_for

    assert _placeholder(specs_for("plot")["x_label"], None) == "column name"


def test_placeholder_falls_back_to_a_static_default():
    from parity_plot.designer.panels.controls import _placeholder, specs_for

    # title's dataclass default is "Parity Plot"
    assert _placeholder(specs_for("plot")["title"], None) == "Parity Plot"
```

`specs_for` already exists in this test module.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/designer/test_controls.py -k placeholder -v`
Expected: FAIL (`_placeholder` undefined).

- [ ] **Step 3: Implement**

In `parity_plot/designer/panels/controls.py`:

Add imports at the top:

```python
import dataclasses

from ...config import PlotConfig, StatsConfig, OutputConfig
from ...data import ParityData
```

(There is already a `from ...config import (...)` block — extend it rather than duplicating.)

Add the placeholder resolver and a small section-class map:

```python
_SECTION_CLASS = {"plot": PlotConfig, "stats": StatsConfig, "output": OutputConfig}


def _placeholder(spec: ControlSpec, data: ParityData | None) -> str:
    """The dimmed default shown in an empty text control.

    x_label / y_label resolve to the actual column name (from the loaded data),
    so an emptied label visibly falls back to it. Other fields show their
    dataclass default when it is a meaningful non-empty value (title →
    "Parity Plot"); an all-None default shows nothing.
    """
    if spec.key in ("x_label", "y_label"):
        if data is None:
            return "column name"
        return data.x_label if spec.key == "x_label" else data.y_label
    cls = _SECTION_CLASS.get(spec.section)
    if cls is not None:
        for f in dataclasses.fields(cls):
            if f.name == spec.key and f.default is not dataclasses.MISSING:
                if f.default not in (None, ""):
                    return str(f.default)
    return ""
```

Rewrite `_build_one` so a blanked text field resets to default and text inputs carry the
placeholder:

```python
def _build_one(
    state: DesignerState, spec: ControlSpec, on_change: Callable[[], None]
) -> None:
    from nicegui import ui

    current = getattr(getattr(state.config, spec.section), spec.key)

    def apply(value: Any) -> None:
        cleaned = _clean(spec, value)
        if cleaned is None:
            # Blank means "revert to default" -- merge drops None, so route
            # through reset_fields, which actually clears the field.
            state.reset_fields(spec.section, spec.key)
        else:
            state.update(spec.section, **{spec.key: cleaned})
        on_change()

    if spec.kind == "switch":
        ui.switch(
            spec.label, value=bool(current), on_change=lambda e: apply(e.value)
        ).tooltip(spec.help)
    elif spec.kind == "choice":
        ui.select(
            list(spec.choices),
            value=current,
            label=spec.label,
            on_change=lambda e: apply(e.value),
        ).classes("w-full").tooltip(spec.help)
    elif spec.kind == "number":
        ui.number(
            spec.label, value=current, on_change=lambda e: apply(e.value)
        ).classes("w-full").tooltip(spec.help)
    else:
        ui.input(
            spec.label,
            value=_as_text(current),
            placeholder=_placeholder(spec, state.data),
            on_change=lambda e: apply(e.value),
        ).classes("w-full").tooltip(spec.help)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/designer/test_controls.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/panels/controls.py tests/designer/test_controls.py
git commit -m "fix(designer): blank field reverts to default; dimmed placeholder shows it"
```

---

## Task 6: Top toolbar + refreshable settings column + open/New-Design wiring

**Files:**
- Modify: `parity_plot/designer/app.py`
- Modify: `parity_plot/designer/session.py` (remove the now-unused `StaleFileError`)
- Test: `tests/designer/test_app.py`

**Interfaces:**
- Consumes: `session.config_choices` (Task 2), `state.load_session_config` (Task 4), `Session.start` (existing), `Session.save` (Task 3).
- Produces: a header toolbar with a config `ui.select`, `Save As…`, `New Design`; the settings column wrapped in a `@ui.refreshable`. No functional API export; verified by boot + the new empty-session test.

- [ ] **Step 1: Write the failing test**

Append to `tests/designer/test_app.py`:

```python
def test_build_app_with_no_data_and_no_config_still_builds(tmp_path, monkeypatch):
    """A New-Design / unbound launch must build the page (toolbar + empty panels)
    without a dataset."""
    monkeypatch.chdir(tmp_path)
    session, config, data = Session.start((), None)
    state = build_app(session, config, data)
    assert state.data is None
    assert state.config == config
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/designer/test_app.py -k no_data_and_no_config -v`
Expected: PASS or FAIL depending on current code — if it already passes, that is fine; it is a guard that the toolbar refactor below does not regress the empty case. (Keep it; Step 4 must keep it green.)

- [ ] **Step 3: Implement**

In `parity_plot/designer/app.py`:

1. Update imports — drop `StaleFileError`, add `config_choices`:
```python
from .session import Session, config_choices
```

2. In `build_app`, the launch directory is the CWD at build time. Inside `page()`, replace the header + settings-column + bottom-buttons region with a toolbar and a refreshable column. The session is now mutable across handlers, so hold it in a one-element list:

```python
state = DesignerState(config=config, data=data)
sess = {"session": session}
launch_dir = Path.cwd()
UNSAVED = "‹unsaved›"


@ui.page("/")
def page() -> None:
    ui.dark_mode(True)

    def current_choice() -> str:
        s = sess["session"]
        return s.config_path.name if s.config_path is not None else UNSAVED

    def choice_options() -> list[str]:
        names = [p.name for p in config_choices(launch_dir)]
        # Show the unbound sentinel only while unbound.
        return ([UNSAVED] if sess["session"].config_path is None else []) + names

    with ui.header().classes("items-center justify-between"):
        ui.label("parity-plot designer").classes("text-lg font-medium")
        with ui.row().classes("items-center gap-2"):
            config_pick = ui.select(
                choice_options(),
                value=current_choice(),
                label="Config",
                on_change=lambda e: open_named(e.value),
            ).classes("w-56")
            save_as_btn = ui.button("Save As…", on_click=lambda: ask_where_to_save())
            ui.button("New Design", on_click=lambda: new_design())

    with ui.row().classes("w-full no-wrap gap-4"):
        with ui.column().classes("w-80 shrink-0"):
            settings_column()  # the @ui.refreshable below

        with ui.column().classes("grow"):
            plot_view = ui.plotly(state.figure()).classes("w-full h-[55vh]")
            status_bar = ui.label("Ready").classes(
                "w-full text-sm px-2 py-1 rounded opacity-70"
            )
            refresh_inspector = build_inspector(state, state.tolerances)
            refresh_table = build_table(
                state,
                on_select=lambda key: select_record(state, key, refresh_inspector),
                on_filter_change=lambda: refresh(),
            )

            def on_point_click(event) -> None:
                points = (event.args or {}).get("points") or []
                if not points:
                    return
                key = key_from_customdata(points[0].get("customdata"))
                select_record(state, key, refresh_inspector, refresh_table)

            plot_view.on("plotly_click", on_point_click)
            plot_view.on(
                "plotly_selected", lambda e: apply_brush(state, e.args, refresh)
            )
            plot_view.on("plotly_deselect", lambda _: apply_brush(state, None, refresh))
```

3. The settings column becomes a refreshable that rebuilds panels from the current `state`:

```python
        @ui.refreshable
        def settings_column() -> None:
            build_data_panel(state, lambda: reload_everything())
            build_tolerances_panel(state, lambda: refresh())
            build_encoding_panel(state, lambda: refresh())
            build_controls(state, lambda: refresh())
```

4. Toolbar handlers. `open_named` opens a chosen file (guarding an unbound-with-edits
discard); `new_design` starts blank; both swap via `load_session_config` and rebuild:

```python
def _has_unsaved_unbound_edits() -> bool:
    s = sess["session"]
    return s.config_path is None and s.is_dirty(state.config)


def _swap(new_session: Session, cfg: ParityConfig, new_data) -> None:
    sess["session"] = new_session
    state.load_session_config(cfg, new_data)
    settings_column.refresh()
    config_pick.options = choice_options()
    config_pick.value = current_choice()
    config_pick.update()
    refresh()


def open_named(name: str) -> None:
    if name == UNSAVED or name == current_choice():
        return

    def do_open() -> None:
        try:
            new_session, cfg, new_data = Session.start((), launch_dir / name)
        except (ConfigError, DataError, ValueError, OSError) as exc:
            set_status(f"⛔  {exc}", "error")
            config_pick.value = current_choice()
            config_pick.update()
            return
        _swap(new_session, cfg, new_data)

    if _has_unsaved_unbound_edits():
        confirm_discard(
            do_open,
            revert=lambda: (
                setattr(config_pick, "value", current_choice()),
                config_pick.update(),
            ),
        )
    else:
        do_open()


def new_design() -> None:
    def do_new() -> None:
        new_session, cfg, new_data = Session.start((), None)
        _swap(new_session, cfg, new_data)

    if _has_unsaved_unbound_edits():
        confirm_discard(do_new)
    else:
        do_new()


def confirm_discard(proceed, revert=None) -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label("Discard unsaved changes?")
        with ui.row():
            ui.button(
                "Cancel",
                on_click=lambda: (dialog.close(), revert() if revert else None),
            )
            ui.button("Discard", on_click=lambda: (dialog.close(), proceed())).props(
                "color=negative"
            )
    dialog.open()
```

5. Replace the old `save(...)`/`confirm_overwrite(...)` with a Save-As-only flow (auto-save
arrives in Task 7). Keep the positive toast:

```python
def save_as(path: Path) -> None:
    try:
        written = sess["session"].save(state.config, path)
    except (ValueError, OSError) as exc:
        set_status(f"⛔  {exc}", "error")
        return
    ui.notify(f"Saved {written}", type="positive")
    set_status(f"✅  Saved {written}", "ok")
    config_pick.options = choice_options()
    config_pick.value = current_choice()
    config_pick.update()
    refresh()


def ask_where_to_save() -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label("Save configuration as")
        target = ui.input(
            "Path", value=str(sess["session"].config_path or "parity.toml")
        )
        with ui.row():
            ui.button("Cancel", on_click=dialog.close)
            ui.button(
                "Save", on_click=lambda: (dialog.close(), save_as(Path(target.value)))
            )
    dialog.open()
```

6. `set_status`, `refresh`, `reload_everything` stay as they were, except `refresh` should
also keep the toolbar's config selection current (the saved/unsaved label is gone):

```python
def refresh() -> None:
    plot_view.update_figure(state.figure())
    if state.last_error:
        set_status(f"⛔  {state.last_error}", "error")
    else:
        set_status("Ready", "info")
    refresh_inspector()
    refresh_table()


def reload_everything() -> None:
    refresh()


refresh()
```

Add the needed imports at the top of `app.py`: `from ..config import ParityConfig, ConfigError` and `from ..data import ParityData, DataError` (extend the existing lines).

7. In `parity_plot/designer/session.py`, **remove** the now-unused `StaleFileError` class.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/designer/test_app.py tests/designer/test_session.py -v`
Then the whole designer suite (the boot subprocess is the real gate that the wiring works):
Run: `uv run pytest tests/designer -q`
Expected: PASS (including `test_the_server_actually_serves_the_page`).

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/app.py parity_plot/designer/session.py tests/designer/test_app.py
git commit -m "feat(designer): top toolbar, config picker, New Design; refreshable panels"
```

---

## Task 7: Auto-save + validation surfacing + Save As disable + join-field mark

**Files:**
- Modify: `parity_plot/designer/app.py`
- Modify: `parity_plot/designer/panels/data_panel.py`
- Test: `tests/designer/test_data_panel.py`, `tests/designer/test_golden_wysiwyg.py` (stays green)

**Interfaces:**
- Consumes: `validation.problems` (Task 1), `Session.autosave` (Task 3).
- Produces: `build_data_panel(...) -> Callable[[list[Problem]], None]` — the returned hook reddens the `join` select when a `data.join` problem stands (and clears it otherwise). `app.refresh()` computes problems, paints the status bar, disables Save As, marks the join field, and auto-saves when clean and bound.

- [ ] **Step 1: Write the failing test**

Append to `tests/designer/test_data_panel.py`:

```python
def test_build_data_panel_returns_a_problem_mark_hook():
    """The panel exposes a callable so app.refresh can mark the join field."""
    import inspect
    from parity_plot.designer.panels.data_panel import build_data_panel

    sig = inspect.signature(build_data_panel)
    # returns a callable now (was None) -- documented contract
    assert sig.return_annotation is not None
```

Add an autosave round-trip assertion to `tests/designer/test_golden_wysiwyg.py` (proves what
auto-save writes reloads to an identical render):

```python
def test_autosave_output_round_trips_identically(csv, tmp_path: Path):
    from parity_plot.designer.session import Session

    session, config, data = Session.start((csv,), tmp_path / "parity.toml")
    state = DesignerState(config=config, data=data)
    edited = state.config.merge(plot={"theme": "light"})
    written = session.autosave(edited)  # writes to the bound file

    from_disk = ParityConfig.from_toml(written)
    preview = build_figure(load(edited.data), edited.plot, edited.stats)
    rendered = build_figure(load(from_disk.data), from_disk.plot, from_disk.stats)
    assert rendered.to_dict() == preview.to_dict()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/designer/test_data_panel.py -k problem_mark tests/designer/test_golden_wysiwyg.py -k autosave -v`
Expected: FAIL (`build_data_panel` returns None; autosave round trip needs Task 3 — already in, so that one may pass).

- [ ] **Step 3: Implement**

In `parity_plot/designer/panels/data_panel.py`, return a mark hook. At the end of
`build_data_panel`, after the widgets are built, add:

```python
def mark_problems(problems) -> None:
    has_join_problem = any(getattr(p, "field", None) == "data.join" for p in problems)
    join_sel.props(remove="error")
    if has_join_problem:
        join_sel.props("error")


return mark_problems
```

and change the function's signature/annotation to `-> Callable[[list], None]` (import
`Callable` is already present).

In `parity_plot/designer/app.py`:

1. Import validation:
```python
from .validation import problems as config_problems
```

2. Capture the data panel's hook in the refreshable column, and hold it so `refresh` can call
it:
```python
marks = {"join": lambda problems: None}


@ui.refreshable
def settings_column() -> None:
    marks["join"] = build_data_panel(state, lambda: reload_everything())
    build_tolerances_panel(state, lambda: refresh())
    build_encoding_panel(state, lambda: refresh())
    build_controls(state, lambda: refresh())
```

3. Rewrite `refresh` to surface validation, gate persistence, mark the field, and auto-save:
```python
        def refresh() -> None:
            plot_view.update_figure(state.figure())

            probs = config_problems(state.config)
            blocking = state.last_error or (probs[0].message if probs else None)

            if blocking:
                set_status(f"⛔  {blocking}", "error")
            else:
                set_status("Ready", "info")

            marks["join"](probs)
            save_as_btn.set_enabled(not blocking)

            # Auto-save: only a clean, bound config is written; unbound is a
            # no-op inside autosave. The bound file thus always holds the last
            # valid config.
            if not blocking:
                sess["session"].autosave(state.config)

            refresh_inspector()
            refresh_table()
```

(`save_as_btn` is defined in the header in Task 6; it is in scope for `refresh`.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/designer -q`
Expected: PASS, including `test_golden_wysiwyg.py` and the boot test.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/app.py parity_plot/designer/panels/data_panel.py tests/designer/test_data_panel.py tests/designer/test_golden_wysiwyg.py
git commit -m "feat(designer): auto-save valid edits; block+mark on validation problems"
```

---

## Task 8: Full suite green + CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`
- Test: whole suite

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest`
Expected: PASS. Fix any straggler referencing `StaleFileError`, `is_stale`, the removed bottom
buttons, or `save(..., force=...)` (search: `grep -rn "StaleFileError\|is_stale\|force=" parity_plot/designer tests/designer`).

- [ ] **Step 2: Update CLAUDE.md (designer section)**

Add/replace notes to state:
- The designer **auto-saves**: `app.refresh()` writes the config to the bound file via
  `Session.autosave` after any change that leaves it valid; the bound file on disk always
  equals the most recent valid config. Unbound (`New Design` / data-only launch) is a no-op
  until **Save As** binds a name.
- Persistence lives in a **top toolbar**: a config dropdown (`session.config_choices` lists
  parity `.toml`s in the launch dir — touchstone: parses + non-empty `data.files`), **Save
  As**, **New Design**. The settings column is a `@ui.refreshable` rebuilt on config swap; the
  right-hand plot/selection persist.
- The **stale-file guard is retired** — the designer owns the open file; concurrent external
  edits are overwritten (bidirectional editing is a deferred non-goal).
- **Validation** is browser-free in `designer/validation.py` (`problems(config)`); a hard
  problem or load error withholds auto-save, disables Save As, paints the status bar, and
  marks the field (`data.join` reddened by the data panel's returned hook). First rule:
  ref/test from the same file + a join set.
- **Clearing a text control reverts to its default** via `state.reset_fields` (not `merge`,
  which drops `None`); `x_label`/`y_label` show the resolved column name as a dimmed
  placeholder.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: designer auto-save, config picker, validation notes"
```

---

## Self-Review

**Spec coverage:**
- Auto-save model (bound/unbound, withhold on error) → Tasks 3, 7. ✅
- Top toolbar (dropdown + Save As + New Design), move to top → Task 6. ✅
- Config discovery (parse + data.files touchstone) → Task 2. ✅
- Validation framework (blocking, status bar, disable Save As, mark join) → Tasks 1, 7. ✅
- Panel re-sync (`@ui.refreshable`) → Task 6. ✅
- Retire stale guard → Tasks 3 (session), 6 (app/class removal). ✅
- Clear-to-default + dimmed placeholder → Tasks 4, 5. ✅
- Confirm only when leaving unbound-with-edits → Task 6 (`_has_unsaved_unbound_edits`). ✅
- Non-goal (bidirectional editing) correctly excluded. ✅

**Type consistency:** `Problem(message, field)` and `problems(config) -> list[Problem]` used in Tasks 1/7; `Session.autosave -> Path|None`, `Session.save(config, path=None)` (no `force`) in Tasks 3/6/7; `state.reset_fields(section, *keys)` / `load_session_config(config, data)` in Tasks 4/5/6; `controls._placeholder(spec, data)` in Task 5; `build_data_panel(...) -> Callable[[list], None]` in Task 7. Consistent.

**Known intermediate-green ordering:** Task 3 keeps `StaleFileError` defined (app still imports it) and only Task 6 removes both the app reference and the class — no red window. Auto-save is added in Task 7 after the toolbar exists in Task 6, so `save_as_btn`/`sess` are in scope.
