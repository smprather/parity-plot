# Designer Phase 1 (Skeleton) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local browser app, `parity-plot design`, that renders a parity plot live while every plot/stats/output setting is edited, and saves the result back to a `parity.toml` without destroying its comments.

**Architecture:** A new `parity_plot/designer/` package. All logic lives in pure, browser-free modules (`serialize`, `session`, `state`); NiceGUI only assembles widgets and forwards their events into `DesignerState`. The preview is produced by calling the CLI's own `build_figure` — never a reimplementation — so the designer cannot render anything the CLI would not.

**Tech Stack:** Python ≥3.11, NiceGUI 3.14, tomlkit 0.15, Plotly 6.9, pytest 9.

## Global Constraints

- **Python floor is `>=3.11`.** NiceGUI requires `<4,>=3.10`; do not raise or lower the project floor.
- **Never reimplement plotting, statistics, or tolerance geometry.** The designer calls `parity_plot.plot.build_figure`, `parity_plot.stats.compute`, and `parity_plot.tolerance.Tolerance`. A setting the designer cannot express through `ParityConfig` is a setting it does not offer.
- **All config edits go through `ParityConfig.merge`**, so the designer inherits the same validation and the same error text as the TOML and CLI paths. Never construct `PlotConfig(...)` directly from widget values.
- **An invalid input must never blank the plot.** The last good figure stays on screen until a valid one replaces it.
- **Filters are exploration state and never reach the saved TOML.** (No filters exist in Phase 1; do not add any.)
- **No numpy or pandas.** Standard library only, as elsewhere in this repo.
- **`nicegui` and `tomlkit` are an optional extra.** `import nicegui` must not happen at `parity_plot` import time, or the plotting CLI breaks for anyone without the extra.
- Relative tolerance is a **ratio**; percent must be written explicitly (`10pct`). Parse with `parity_plot.tolerance.parse_reltol`. Never present a percent-only control.
- Run tests with `.venv/bin/python -m pytest` (or `uv run pytest`).

---

### Task 1: TOML serializer with comment preservation

`config.py` only reads TOML — `tomllib` is read-only by design. Saving needs a writer, and the naive version regenerates the file and destroys the comments in a config meant to be hand-edited and committed. `tomlkit` updates values in place instead.

**Files:**
- Create: `parity_plot/designer/__init__.py`
- Create: `parity_plot/designer/serialize.py`
- Test: `tests/designer/test_serialize.py`
- Create: `tests/designer/__init__.py` (empty)

**Interfaces:**
- Consumes: `parity_plot.config.ParityConfig`, `EXAMPLE_TOML`
- Produces: `config_to_toml(config: ParityConfig, existing: str | None = None) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_serialize.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import EXAMPLE_TOML, ParityConfig
from parity_plot.designer.serialize import config_to_toml

WITH_COMMENTS = """\
# my project's tolerance policy
[plot]
# dark reads better on the lab projector
theme = "dark"
reltol = 0.10
"""


def test_round_trips_through_the_normal_loader(tmp_path: Path):
    config = ParityConfig.from_dict({"plot": {"theme": "light", "abstol": 2.0}})

    text = config_to_toml(config)
    path = tmp_path / "out.toml"
    path.write_text(text, encoding="utf-8")

    assert ParityConfig.from_toml(path) == config


def test_comments_survive_a_save():
    """The config is meant to be hand-edited and committed; a save that eats
    the comments makes the designer unusable on a real project file."""
    config = ParityConfig.from_dict({"plot": {"theme": "light"}})

    text = config_to_toml(config, existing=WITH_COMMENTS)

    assert "# my project's tolerance policy" in text
    assert "# dark reads better on the lab projector" in text
    assert 'theme = "light"' in text


def test_untouched_values_keep_their_original_spelling():
    """`10pct` and `0.1` mean the same thing; rewriting one as the other is a
    gratuitous diff in a file under version control."""
    existing = '[plot]\nreltol = "10pct"\n'
    config = ParityConfig.from_dict({"plot": {"reltol": "10pct", "theme": "light"}})

    text = config_to_toml(config, existing=existing)

    assert '"10pct"' in text


def test_changed_values_are_written():
    existing = '[plot]\nreltol = "10pct"\n'
    config = ParityConfig.from_dict({"plot": {"reltol": 0.25}})

    text = config_to_toml(config, existing=existing)

    assert "0.25" in text
    assert '"10pct"' not in text


def test_none_values_are_removed_not_written_as_null():
    existing = "[plot]\nabstol = 2.0\n"
    config = ParityConfig()  # abstol defaults to None

    text = config_to_toml(config, existing=existing)

    assert "abstol" not in text


def test_paths_and_tuples_become_toml_types(tmp_path: Path):
    config = ParityConfig.from_dict(
        {"data": {"paths": ["a.csv", "b.csv"]}, "stats": {"metrics": ["n", "rmse"]}}
    )

    text = config_to_toml(config)
    path = tmp_path / "out.toml"
    path.write_text(text, encoding="utf-8")
    loaded = ParityConfig.from_toml(path)

    assert loaded.data.paths == (Path("a.csv"), Path("b.csv"))
    assert loaded.stats.metrics == ("n", "rmse")


def test_a_fresh_document_carries_the_example_comments():
    text = config_to_toml(ParityConfig())
    assert "#" in text  # generated from EXAMPLE_TOML, comments included
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_serialize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/__init__.py
"""Interactive designer for parity-plot.

Importing this package pulls in NiceGUI, which is an optional extra. Nothing in
`parity_plot` proper may import it at module scope.
"""
```

```python
# parity_plot/designer/serialize.py
"""Writing a ParityConfig back to TOML.

`tomllib` is read-only, so saving needs its own writer. The naive approach --
regenerate the file from the config -- destroys every comment in it, which is
unacceptable for a file meant to be hand-edited and committed. `tomlkit` parses
into a document that remembers its own formatting, so values can be updated in
place and everything around them survives.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import tomlkit

from ..config import EXAMPLE_TOML, ParityConfig

SECTIONS = ("data", "plot", "stats", "output")


def config_to_toml(config: ParityConfig, existing: str | None = None) -> str:
    """Render ``config`` as TOML, updating ``existing`` in place if given.

    Without ``existing``, a fresh document is generated from the documented
    example so a first save still arrives with its comments.
    """
    doc = tomlkit.parse(existing if existing is not None else EXAMPLE_TOML)
    current = _safe_load(doc)

    for name in SECTIONS:
        section = getattr(config, name)
        table = doc.get(name)
        if table is None:
            table = tomlkit.table()
            doc[name] = table

        for field in fields(section):
            value = getattr(section, field.name)
            if value is None:
                # An unset option is an absent key, not an explicit null.
                if field.name in table:
                    del table[field.name]
                continue
            if _already_equals(current, name, field.name, value):
                # Leave the existing text alone so "10pct" is not rewritten as
                # 0.1 -- same value, gratuitous diff.
                continue
            table[field.name] = _to_toml_value(value)

    return tomlkit.dumps(doc)


def _safe_load(doc: Any) -> ParityConfig | None:
    """The existing document as a config, or None if it does not parse.

    A malformed file on disk must not stop a save; it just means nothing can be
    treated as already-equal.
    """
    try:
        return ParityConfig.from_dict(_plain(doc))
    except Exception:
        return None


def _already_equals(current: ParityConfig | None, section: str, key: str, value: Any) -> bool:
    if current is None:
        return False
    return getattr(getattr(current, section), key) == value


def _plain(value: Any) -> Any:
    """Strip tomlkit's wrapper types so ParityConfig sees plain Python."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, str):
        return str(value)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return value


def _to_toml_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [_to_toml_value(v) for v in value]
    return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_serialize.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/ tests/designer/
git commit -m "feat(designer): TOML serializer preserving comments and spelling"
```

---

### Task 2: Session — load, save, dirty and staleness tracking

**Files:**
- Create: `parity_plot/designer/session.py`
- Test: `tests/designer/test_session.py`

**Interfaces:**
- Consumes: `config_to_toml` (Task 1), `parity_plot.config.ParityConfig`, `parity_plot.data.load`
- Produces:
  - `Session.start(data_paths: tuple[Path, ...], config_path: Path | None) -> tuple[Session, ParityConfig, ParityData]`
  - `Session.save(config: ParityConfig, path: Path | None = None) -> Path`
  - `Session.is_dirty(config: ParityConfig) -> bool`
  - `Session.is_stale() -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_session.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.designer.session import Session, StaleFileError

WIDE = """\
id,reference,measured
A1,10.0,11.0
A2,20.0,
A3,30.0,29.0
"""


@pytest.fixture
def csv(tmp_path: Path) -> Path:
    path = tmp_path / "wide.csv"
    path.write_text(WIDE, encoding="utf-8")
    return path


def test_start_loads_data_from_paths(csv):
    session, config, data = Session.start((csv,), None)

    assert data.n_paired == 2
    assert len(data.missing_y) == 1
    assert config == ParityConfig().merge(data={"paths": (csv,)})


def test_start_loads_config_and_its_paths(csv, tmp_path: Path):
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text(
        f'[data]\npaths = ["{csv.as_posix()}"]\n\n[plot]\ntheme = "light"\n',
        encoding="utf-8",
    )

    session, config, data = Session.start((), cfg_path)

    assert config.plot.theme == "light"
    assert data.n_paired == 2


def test_command_line_paths_win_over_the_config_file(csv, tmp_path: Path):
    other = tmp_path / "other.csv"
    other.write_text(WIDE, encoding="utf-8")
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text(f'[data]\npaths = ["{other.as_posix()}"]\n', encoding="utf-8")

    _, config, _ = Session.start((csv,), cfg_path)

    assert config.data.paths == (csv,)


def test_dirty_only_once_the_config_changes(csv):
    session, config, _ = Session.start((csv,), None)

    assert not session.is_dirty(config)
    assert session.is_dirty(config.merge(plot={"theme": "light"}))


def test_save_writes_and_clears_dirty(csv, tmp_path: Path):
    session, config, _ = Session.start((csv,), None)
    edited = config.merge(plot={"theme": "light"})
    out = tmp_path / "saved.toml"

    written = session.save(edited, out)

    assert written == out
    assert ParityConfig.from_toml(out).plot.theme == "light"
    assert not session.is_dirty(edited)


def test_save_without_a_path_needs_one_from_somewhere(csv):
    session, config, _ = Session.start((csv,), None)
    with pytest.raises(ValueError, match="no config path"):
        session.save(config)


def test_save_reuses_the_loaded_path(csv, tmp_path: Path):
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text('[plot]\ntheme = "dark"\n', encoding="utf-8")
    session, config, _ = Session.start((csv,), cfg_path)

    written = session.save(config.merge(plot={"theme": "light"}))

    assert written == cfg_path
    assert ParityConfig.from_toml(cfg_path).plot.theme == "light"


def test_stale_when_the_file_changed_underneath(csv, tmp_path: Path):
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text('[plot]\ntheme = "dark"\n', encoding="utf-8")
    session, config, _ = Session.start((csv,), cfg_path)

    assert not session.is_stale()
    cfg_path.write_text('[plot]\ntheme = "light"\n', encoding="utf-8")
    assert session.is_stale()


def test_saving_over_a_changed_file_refuses_until_forced(csv, tmp_path: Path):
    """Silently clobbering an edit made in another window loses work."""
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text('[plot]\ntheme = "dark"\n', encoding="utf-8")
    session, config, _ = Session.start((csv,), cfg_path)
    cfg_path.write_text("[plot]\n# edited elsewhere\n", encoding="utf-8")

    with pytest.raises(StaleFileError):
        session.save(config)

    session.save(config, force=True)
    assert "dark" in cfg_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.session'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/session.py
"""Where the designer's data and config came from, and where they go back to."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import ConfigError, ParityConfig
from ..data import ParityData, load
from .serialize import config_to_toml


class StaleFileError(RuntimeError):
    """The config file changed on disk after it was loaded."""


@dataclass
class Session:
    config_path: Path | None = None
    original_text: str | None = None
    disk_text: str | None = None
    saved_config: ParityConfig | None = None

    @classmethod
    def start(
        cls, data_paths: tuple[Path, ...], config_path: Path | None
    ) -> tuple[Session, ParityConfig, ParityData]:
        """Load config then data, with command-line paths winning.

        Same precedence as the CLI: an explicit path on the command line beats
        whatever the config file names.
        """
        if config_path is not None:
            text = Path(config_path).read_text(encoding="utf-8")
            config = ParityConfig.from_toml(config_path)
        else:
            text = None
            config = ParityConfig()

        if data_paths:
            config = config.merge(data={"paths": tuple(data_paths)})

        data = load(config.data)
        session = cls(
            config_path=Path(config_path) if config_path else None,
            original_text=text,
            disk_text=text,
            saved_config=config,
        )
        return session, config, data

    def is_dirty(self, config: ParityConfig) -> bool:
        return config != self.saved_config

    def is_stale(self) -> bool:
        """True when the file changed since we last read or wrote it."""
        if self.config_path is None or not self.config_path.exists():
            return False
        return self.config_path.read_text(encoding="utf-8") != self.disk_text

    def save(
        self, config: ParityConfig, path: Path | None = None, force: bool = False
    ) -> Path:
        target = Path(path) if path is not None else self.config_path
        if target is None:
            raise ValueError("no config path to save to; choose one with Save As")

        writing_in_place = path is None or Path(path) == self.config_path
        if writing_in_place and not force and self.is_stale():
            raise StaleFileError(
                f"{target} changed on disk since it was opened; "
                f"saving now would discard that edit"
            )

        existing = target.read_text(encoding="utf-8") if target.exists() else None
        text = config_to_toml(config, existing=existing)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

        self.config_path = target
        self.disk_text = text
        self.saved_config = config
        return target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_session.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/session.py tests/designer/test_session.py
git commit -m "feat(designer): session load, save, dirty and staleness tracking"
```

---

### Task 3: DesignerState — the single source of truth

**Files:**
- Create: `parity_plot/designer/state.py`
- Test: `tests/designer/test_state.py`

**Interfaces:**
- Consumes: `parity_plot.plot.build_figure`, `parity_plot.config.ParityConfig`, `parity_plot.data.ParityData`
- Produces:
  - `DesignerState(config: ParityConfig, data: ParityData)`
  - `DesignerState.update(section: str, **values) -> bool`
  - `DesignerState.figure() -> go.Figure`
  - `DesignerState.last_error: str | None`
  - `DesignerState.selection: str | None`

Phase 3 adds a `filters: FilterSet` field here. Do not add it now.

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_state.py
from __future__ import annotations

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import from_sequences
from parity_plot.designer.state import DesignerState


@pytest.fixture
def state() -> DesignerState:
    data = from_sequences(x=[1.0, 2.0, 3.0], y=[1.1, 2.2, None], keys=["a", "b", "c"])
    return DesignerState(config=ParityConfig(), data=data)


def test_figure_comes_from_the_cli_code_path(state):
    """The preview must be the CLI's own figure, or the two can drift."""
    from parity_plot.plot import build_figure

    assert state.figure().to_dict() == build_figure(
        state.data, state.config.plot, state.config.stats
    ).to_dict()


def test_update_applies_a_setting(state):
    assert state.update("plot", theme="light")
    assert state.config.plot.theme == "light"
    assert state.last_error is None


def test_update_reports_failure_and_keeps_the_old_value(state):
    assert not state.update("plot", theme="neon")
    assert state.config.plot.theme == "dark"
    assert "neon" in state.last_error


def test_an_invalid_update_never_blanks_the_plot(state):
    good = state.figure().to_dict()
    state.update("plot", theme="neon")
    assert state.figure().to_dict() == good


def test_a_figure_that_fails_to_build_falls_back_to_the_last_good_one(state):
    good = state.figure().to_dict()
    # band_style passes config validation but build_figure rejects it.
    object.__setattr__(state.config.plot, "band_style", "dotted")
    state.config = state.config.merge(plot={"reltol": 0.1})

    assert state.figure().to_dict() == good
    assert state.last_error is not None


def test_the_first_figure_cannot_fall_back_and_raises(state):
    state.config = state.config.merge(plot={"theme": "dark"})
    object.__setattr__(state.config.plot, "band_style", "dotted")
    state.config = state.config.merge(plot={"reltol": 0.1})
    with pytest.raises(ValueError):
        state.figure()


def test_none_values_are_ignored_by_update(state):
    state.update("plot", theme="light")
    state.update("plot", theme=None)
    assert state.config.plot.theme == "light"


def test_selection_defaults_to_nothing(state):
    assert state.selection is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.state'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/state.py
"""The designer's single source of truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import plotly.graph_objects as go

from ..config import ConfigError, ParityConfig
from ..data import ParityData
from ..plot import build_figure


@dataclass
class DesignerState:
    """Everything the UI reads from and writes to.

    Widgets never hold state of their own; they push edits in here and re-read
    the result, so the config on screen and the config that will be saved
    cannot disagree.
    """

    config: ParityConfig
    data: ParityData
    selection: str | None = None
    last_error: str | None = None
    _last_figure: go.Figure | None = field(default=None, repr=False)

    def update(self, section: str, **values: Any) -> bool:
        """Apply settings to one config section. Returns whether it worked.

        Routed through ``ParityConfig.merge`` so the designer inherits exactly
        the validation and error text the TOML and CLI paths already use.
        """
        try:
            self.config = self.config.merge(**{section: values})
        except (ConfigError, ValueError) as exc:
            self.last_error = str(exc)
            return False
        self.last_error = None
        return True

    def figure(self) -> go.Figure:
        """Build the preview, keeping the last good one if this build fails.

        A rejected setting must not clear the screen -- losing the plot on a
        typo makes the tool feel broken and hides what you were comparing
        against.
        """
        try:
            figure = build_figure(self.data, self.config.plot, self.config.stats)
        except (ConfigError, ValueError) as exc:
            self.last_error = str(exc)
            if self._last_figure is None:
                raise
            return self._last_figure

        self.last_error = None
        self._last_figure = figure
        return figure
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_state.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/state.py tests/designer/test_state.py
git commit -m "feat(designer): DesignerState with last-good-figure fallback"
```

---

### Task 4: The `design` subcommand and its missing-extra guard

**Files:**
- Create: `parity_plot/designer/launch.py`
- Modify: `parity_plot/cli.py` (add the `design` command and its option group)
- Test: `tests/designer/test_launch.py`

**Interfaces:**
- Consumes: `Session.start` (Task 2), `DesignerState` (Task 3)
- Produces:
  - `launch.require_nicegui() -> None` — raises `MissingDependencyError` with an actionable message
  - `launch.run(data_paths, config_path, port, open_browser, reload=False) -> None`
  - `launch.MissingDependencyError`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_launch.py
from __future__ import annotations

import builtins
from pathlib import Path

import pytest
from click.testing import CliRunner

from parity_plot.cli import cli
from parity_plot.designer.launch import MissingDependencyError, require_nicegui

WIDE = "id,reference,measured\nA1,10.0,11.0\nA2,20.0,21.0\n"


@pytest.fixture
def csv(tmp_path: Path) -> Path:
    path = tmp_path / "wide.csv"
    path.write_text(WIDE, encoding="utf-8")
    return path


def test_require_nicegui_passes_when_installed():
    require_nicegui()  # the designer extra is installed in this environment


def test_require_nicegui_names_the_command_to_run(monkeypatch):
    """Someone without the extra needs to be told exactly what to install."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "nicegui" or name.startswith("nicegui."):
            raise ImportError("No module named 'nicegui'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(MissingDependencyError) as exc:
        require_nicegui()

    assert "--extra designer" in str(exc.value)


def test_design_command_is_registered():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "design" in result.output


def test_design_help_lists_its_options():
    result = CliRunner().invoke(cli, ["design", "--help"])
    assert result.exit_code == 0
    for flag in ("--config", "--port", "--open-browser"):
        assert flag in result.output


def test_design_starts_a_session_without_running_a_server(csv, monkeypatch):
    """Verify wiring: the command must reach `run` with the parsed arguments."""
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("parity_plot.designer.launch.run", fake_run)

    result = CliRunner().invoke(cli, ["design", str(csv), "--port", "9123", "--no-open-browser"])

    assert result.exit_code == 0, result.output
    assert captured["data_paths"] == (csv,)
    assert captured["port"] == 9123
    assert captured["open_browser"] is False


def test_design_reports_a_bad_csv_without_a_traceback(tmp_path, monkeypatch):
    monkeypatch.setattr("parity_plot.designer.launch.run", lambda **kw: None)
    bad = tmp_path / "bad.csv"
    bad.write_text("id,reference,measured\nA1,1.0,oops\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["design", str(bad), "--no-open-browser"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_launch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.launch'`

- [ ] **Step 3: Write the implementation**

Create `parity_plot/designer/launch.py`:

```python
"""Starting the designer, and failing clearly when it cannot start."""

from __future__ import annotations

import socket
from pathlib import Path


class MissingDependencyError(RuntimeError):
    """The designer extra is not installed."""


def require_nicegui() -> None:
    """Fail with the install command rather than a bare ImportError."""
    try:
        import nicegui  # noqa: F401
    except ImportError as exc:
        raise MissingDependencyError(
            "the designer needs NiceGUI, which is an optional extra. "
            "Install it with:  uv sync --extra designer"
        ) from exc


def free_port(preferred: int) -> int:
    """Return ``preferred`` if it is free, otherwise any open port.

    Refusing to start because a stale server holds the port is a worse
    experience than moving to another one and saying so.
    """
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run(
    data_paths: tuple[Path, ...],
    config_path: Path | None,
    port: int,
    open_browser: bool,
) -> None:
    """Build the app and serve it. Imports NiceGUI lazily."""
    require_nicegui()

    from nicegui import ui

    from .app import build_app
    from .session import Session

    session, config, data = Session.start(data_paths, config_path)
    build_app(session, config, data)

    chosen = free_port(port)
    if chosen != port:
        print(f"port {port} is in use; serving on {chosen} instead")

    ui.run(
        port=chosen,
        show=open_browser,
        title="parity-plot designer",
        reload=False,
        favicon="📉",
    )
```

Add to `parity_plot/cli.py`, after the `init_config` command and before `def main()`:

```python
@cli.command()
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("-c", "--config", type=click.Path(dir_okay=False, path_type=Path), help="TOML config file to open and save back to.")
@click.option("--port", type=int, default=8080, show_default=True, help="Port to serve on.  Falls back to a free port if taken.")
@click.option("--open-browser/--no-open-browser", "open_browser", default=True, help="Open the designer in the default browser.  [default: open]")
def design(
    paths: tuple[Path, ...],
    config: Path | None,
    port: int,
    open_browser: bool,
) -> None:
    """Open the interactive designer.

    Edit every plot setting against your real data and watch the result
    update, then save the settings back to a `parity.toml`.
    """
    from .designer import launch

    try:
        launch.run(
            data_paths=tuple(paths),
            config_path=config,
            port=port,
            open_browser=open_browser,
        )
    except (ConfigError, DataError, launch.MissingDependencyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None
```

Add to `HELP_CONFIG`'s `option_groups`, alongside the other commands:

```python
        "parity-plot design": [
            {"name": "Input", "options": ["PATHS", "--config"]},
            {"name": "Server", "options": ["--port", "--open-browser"]},
            {"name": "Help", "options": ["--help"]},
        ],
```

And add `design` to the `command_groups` "Plotting" list so it appears grouped:

```python
            {"name": "Plotting", "commands": ["plot", "design"]},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_launch.py -v`
Expected: PASS, 6 tests

Then confirm nothing else broke: `.venv/bin/python -m pytest -q`
Expected: all previous tests still pass.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/launch.py parity_plot/cli.py tests/designer/test_launch.py
git commit -m "feat(designer): design subcommand with missing-extra guard"
```

---

### Task 5: Control panel — every setting, bound to state

**Files:**
- Create: `parity_plot/designer/panels/__init__.py` (empty)
- Create: `parity_plot/designer/panels/controls.py`
- Test: `tests/designer/test_controls.py`

**Interfaces:**
- Consumes: `DesignerState` (Task 3)
- Produces:
  - `controls.CONTROL_SPECS: tuple[ControlSpec, ...]` — the declarative description of every control
  - `controls.ControlSpec(section, key, label, kind, choices, help)`
  - `controls.build_controls(state: DesignerState, on_change: Callable[[], None]) -> None`

`CONTROL_SPECS` is pure data and is tested without a browser. `build_controls` is the only part that touches NiceGUI.

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_controls.py
from __future__ import annotations

from dataclasses import fields

import pytest

from parity_plot.config import (
    BAND_STYLES,
    LEGEND_POSITIONS,
    NULL_MODES,
    OUTPUT_FORMATS,
    THEMES,
    OutputConfig,
    PlotConfig,
    StatsConfig,
)
from parity_plot.designer.panels.controls import CONTROL_SPECS, ControlSpec


def specs_for(section: str) -> dict[str, ControlSpec]:
    return {s.key: s for s in CONTROL_SPECS if s.section == section}


def test_every_plot_setting_has_a_control():
    """A setting with no control is a setting the designer silently cannot
    reach, which makes the saved config differ from what was on screen."""
    assert specs_for("plot").keys() == {f.name for f in fields(PlotConfig)}


def test_every_stats_and_output_setting_has_a_control():
    assert specs_for("stats").keys() == {f.name for f in fields(StatsConfig)}
    assert specs_for("output").keys() == {f.name for f in fields(OutputConfig)}


def test_data_settings_are_not_editable_in_phase_1():
    """The dataset is fixed for the session; column mapping is Phase 2."""
    assert specs_for("data") == {}


@pytest.mark.parametrize(
    "section, key, expected",
    [
        ("plot", "theme", THEMES),
        ("plot", "legend", LEGEND_POSITIONS),
        ("plot", "nulls", NULL_MODES),
        ("plot", "band_style", BAND_STYLES),
        ("output", "format", OUTPUT_FORMATS),
    ],
)
def test_choice_controls_offer_exactly_the_valid_values(section, key, expected):
    spec = specs_for(section)[key]
    assert spec.kind == "choice"
    assert spec.choices == tuple(expected)


def test_relative_tolerance_is_a_text_control_not_a_percent_spinner():
    """`--reltol` takes a ratio or an explicit `10pct`; a percent-only spinner
    would reintroduce exactly the unit ambiguity that spelling prevents."""
    spec = specs_for("plot")["reltol"]
    assert spec.kind == "text"
    assert "pct" in spec.help


def test_booleans_are_switches():
    for key in ("log", "equal_axes", "identity_line"):
        assert specs_for("plot")[key].kind == "switch"
    assert specs_for("stats")["show"].kind == "switch"


def test_every_spec_has_a_human_label():
    for spec in CONTROL_SPECS:
        assert spec.label and not spec.label.endswith("_")
        assert spec.help
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_controls.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.panels'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/panels/controls.py
"""The settings panel.

`CONTROL_SPECS` is declarative data describing every control, so the set of
controls can be tested against the config dataclasses without a browser. A
setting with no control here is a setting the designer cannot reach, which
would make the saved config differ from what was on screen -- hence the test
that walks the dataclass fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ...config import (
    BAND_STYLES,
    LEGEND_POSITIONS,
    NULL_MODES,
    OUTPUT_FORMATS,
    THEMES,
)
from ..state import DesignerState


@dataclass(frozen=True)
class ControlSpec:
    section: str
    key: str
    label: str
    kind: str  # "text" | "number" | "switch" | "choice"
    help: str
    choices: tuple[str, ...] = ()
    group: str = "Appearance"


CONTROL_SPECS: tuple[ControlSpec, ...] = (
    # --- Appearance -------------------------------------------------------
    ControlSpec("plot", "title", "Title", "text", "Plot title."),
    ControlSpec("plot", "x_label", "X label", "text", "Defaults to the column name."),
    ControlSpec("plot", "y_label", "Y label", "text", "Defaults to the column name."),
    ControlSpec("plot", "theme", "Theme", "choice", "Colour theme.", THEMES),
    ControlSpec("plot", "legend", "Legend", "choice", "Where the legend sits.", LEGEND_POSITIONS),
    ControlSpec("plot", "nulls", "Unpaired records", "choice", "Rug ticks, or hidden.", NULL_MODES),
    ControlSpec("plot", "log", "Log axes", "switch", "Logarithmic x and y."),
    ControlSpec("plot", "equal_axes", "Lock 45°", "switch", "Share one range and a 1:1 pixel scale."),
    ControlSpec("plot", "identity_line", "Show y = x", "switch", "Draw the zero-error line."),
    # --- Tolerances -------------------------------------------------------
    ControlSpec(
        "plot", "abstol", "Absolute tolerance", "number",
        "In the data's own units. Draws lines parallel to y = x.",
        group="Tolerances",
    ),
    ControlSpec(
        "plot", "reltol", "Relative tolerance", "text",
        "A ratio (0.1), or a percentage written out (10pct).",
        group="Tolerances",
    ),
    ControlSpec(
        "plot", "band_style", "Limit style", "choice",
        "Lines, or a shaded band.", BAND_STYLES, group="Tolerances",
    ),
    # --- Statistics -------------------------------------------------------
    ControlSpec("stats", "show", "Show statistics", "switch", "Display the metrics box.", group="Statistics"),
    ControlSpec("stats", "metrics", "Metrics", "text", "Comma-separated: n, r2, rmse, mae, bias.", group="Statistics"),
    # --- Output -----------------------------------------------------------
    ControlSpec("output", "path", "Output file", "text", "Where `plot` writes to.", group="Output"),
    ControlSpec("output", "format", "Format", "choice", "html needs nothing; the rest need kaleido.", OUTPUT_FORMATS, group="Output"),
    ControlSpec("output", "width", "Width", "number", "Figure width in pixels.", group="Output"),
    ControlSpec("output", "height", "Height", "number", "Figure height in pixels.", group="Output"),
)

GROUPS = ("Appearance", "Tolerances", "Statistics", "Output")


def build_controls(state: DesignerState, on_change: Callable[[], None]) -> None:
    """Render every control, grouped, wired straight into ``state``."""
    from nicegui import ui

    for group in GROUPS:
        specs = [s for s in CONTROL_SPECS if s.group == group]
        if not specs:
            continue
        with ui.expansion(group, value=True).classes("w-full"):
            for spec in specs:
                _build_one(state, spec, on_change)


def _build_one(state: DesignerState, spec: ControlSpec, on_change: Callable[[], None]) -> None:
    from nicegui import ui

    current = getattr(getattr(state.config, spec.section), spec.key)

    def apply(value: Any) -> None:
        if not state.update(spec.section, **{spec.key: _clean(spec, value)}):
            ui.notify(state.last_error, type="negative")
        on_change()

    if spec.kind == "switch":
        ui.switch(spec.label, value=bool(current), on_change=lambda e: apply(e.value)).tooltip(spec.help)
    elif spec.kind == "choice":
        ui.select(list(spec.choices), value=current, label=spec.label,
                  on_change=lambda e: apply(e.value)).classes("w-full").tooltip(spec.help)
    elif spec.kind == "number":
        ui.number(spec.label, value=current,
                  on_change=lambda e: apply(e.value)).classes("w-full").tooltip(spec.help)
    else:
        ui.input(spec.label, value=_as_text(current),
                 on_change=lambda e: apply(e.value)).classes("w-full").tooltip(spec.help)


def _clean(spec: ControlSpec, value: Any) -> Any:
    """Turn a widget value into something ParityConfig.merge accepts.

    Blank text means "unset", which merge reads as None and therefore skips --
    so an emptied field falls back to the config default rather than erroring.
    """
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if spec.key == "metrics":
            return tuple(part.strip() for part in value.split(",") if part.strip())
    return value


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (tuple, list)):
        return ", ".join(str(v) for v in value)
    return str(value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_controls.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/panels/ tests/designer/test_controls.py
git commit -m "feat(designer): declarative control specs covering every setting"
```

---

### Task 6: App assembly — live preview, save, and the error banner

**Files:**
- Create: `parity_plot/designer/app.py`
- Test: `tests/designer/test_app.py`

**Interfaces:**
- Consumes: `Session` (Task 2), `DesignerState` (Task 3), `build_controls` (Task 5)
- Produces: `app.build_app(session: Session, config: ParityConfig, data: ParityData) -> DesignerState`

- [ ] **Step 1: Write the failing tests**

```python
# tests/designer/test_app.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import from_sequences
from parity_plot.designer.app import build_app
from parity_plot.designer.session import Session

pytest_plugins = ("nicegui.testing.plugin",)


@pytest.fixture
def session_and_data(tmp_path: Path):
    csv = tmp_path / "wide.csv"
    csv.write_text("id,reference,measured\nA1,10.0,11.0\nA2,20.0,21.0\n", encoding="utf-8")
    return Session.start((csv,), None)


def test_build_app_returns_state_wired_to_the_session(session_and_data):
    session, config, data = session_and_data
    state = build_app(session, config, data)
    assert state.config == config
    assert state.data is data


def test_editing_through_state_changes_the_figure(session_and_data):
    session, config, data = session_and_data
    state = build_app(session, config, data)

    before = state.figure().to_dict()
    state.update("plot", theme="light")
    after = state.figure().to_dict()

    assert before != after


def test_saving_writes_what_is_on_screen(session_and_data, tmp_path: Path):
    session, config, data = session_and_data
    state = build_app(session, config, data)
    state.update("plot", theme="light", abstol=2.0)

    out = tmp_path / "saved.toml"
    session.save(state.config, out)

    reloaded = ParityConfig.from_toml(out)
    assert reloaded.plot.theme == "light"
    assert reloaded.plot.abstol == 2.0


@pytest.mark.module_under_test("parity_plot.designer.app")
async def test_the_page_renders_with_a_plot_and_controls(user, session_and_data):
    session, config, data = session_and_data
    build_app(session, config, data)

    await user.open("/")
    await user.should_see("Theme")
    await user.should_see("Save")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/designer/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.designer.app'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/designer/app.py
"""NiceGUI assembly.

This module owns layout and event wiring only. Anything worth a test belongs in
`state.py`, `session.py`, or `serialize.py`, which need no browser.
"""

from __future__ import annotations

from pathlib import Path

from ..config import ParityConfig
from ..data import ParityData
from .panels.controls import build_controls
from .session import Session, StaleFileError
from .state import DesignerState


def build_app(session: Session, config: ParityConfig, data: ParityData) -> DesignerState:
    """Register the designer page and return the state it drives."""
    from nicegui import ui

    state = DesignerState(config=config, data=data)

    @ui.page("/")
    def page() -> None:
        ui.dark_mode(True)

        with ui.header().classes("items-center justify-between"):
            ui.label("parity-plot designer").classes("text-lg font-medium")
            status = ui.label("").classes("text-sm opacity-70")

        with ui.row().classes("w-full no-wrap gap-4"):
            with ui.column().classes("w-80 shrink-0"):
                ui.label("Settings").classes("text-base font-medium")
                build_controls(state, lambda: refresh())
                ui.separator()
                with ui.row():
                    ui.button("Save", on_click=lambda: save(None))
                    ui.button("Save As…", on_click=lambda: ask_where_to_save())

            with ui.column().classes("grow"):
                plot_view = ui.plotly(state.figure()).classes("w-full h-[80vh]")
                error_banner = ui.label("").classes("text-red-400 text-sm")

        def refresh() -> None:
            plot_view.update_figure(state.figure())
            error_banner.text = state.last_error or ""
            status.text = "unsaved changes" if session.is_dirty(state.config) else "saved"

        def save(path: Path | None, force: bool = False) -> None:
            try:
                written = session.save(state.config, path, force=force)
            except StaleFileError as exc:
                confirm_overwrite(str(exc))
                return
            except (ValueError, OSError) as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.notify(f"Saved {written}", type="positive")
            refresh()

        def confirm_overwrite(message: str) -> None:
            with ui.dialog() as dialog, ui.card():
                ui.label(message)
                with ui.row():
                    ui.button("Cancel", on_click=dialog.close)
                    ui.button(
                        "Overwrite",
                        on_click=lambda: (dialog.close(), save(None, force=True)),
                    ).props("color=negative")
            dialog.open()

        def ask_where_to_save() -> None:
            with ui.dialog() as dialog, ui.card():
                ui.label("Save configuration as")
                target = ui.input("Path", value=str(session.config_path or "parity.toml"))
                with ui.row():
                    ui.button("Cancel", on_click=dialog.close)
                    ui.button(
                        "Save",
                        on_click=lambda: (dialog.close(), save(Path(target.value))),
                    )
            dialog.open()

        refresh()

    return state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/designer/test_app.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/app.py tests/designer/test_app.py
git commit -m "feat(designer): app assembly with live preview and save"
```

---

### Task 7: The golden test, docs, and packaging

The WYSIWYG guarantee, stated executably. If this fails, the designer is lying about what the CLI will do.

**Files:**
- Test: `tests/designer/test_golden_wysiwyg.py`
- Modify: `README.md` (add a Designer section)
- Modify: `CLAUDE.md` (add designer architecture notes)
- Verify: `pyproject.toml` already carries the `designer` extra

**Interfaces:**
- Consumes: everything above

- [ ] **Step 1: Write the failing test**

```python
# tests/designer/test_golden_wysiwyg.py
"""The designer must not be able to lie about what the CLI will produce."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.session import Session
from parity_plot.designer.state import DesignerState
from parity_plot.plot import build_figure

WIDE = """\
id,reference,measured
A1,10.0,11.0
A2,20.0,
A3,30.0,29.0
A4,,41.0
A5,,
A6,50.0,54.0
"""


@pytest.fixture
def csv(tmp_path: Path) -> Path:
    path = tmp_path / "wide.csv"
    path.write_text(WIDE, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "edits",
    [
        {"theme": "light"},
        {"abstol": 2.0},
        {"reltol": 0.1},
        {"abstol": 2.0, "reltol": 0.1, "band_style": "shaded"},
        {"legend": "bottom", "nulls": "drop"},
        {"log": True, "identity_line": False},
        {"title": "Lab run 7", "x_label": "golden", "y_label": "DUT"},
    ],
)
def test_designer_preview_equals_what_the_cli_renders(csv, tmp_path: Path, edits):
    session, config, data = Session.start((csv,), None)
    state = DesignerState(config=config, data=data)
    assert state.update("plot", **edits), state.last_error

    preview = state.figure()

    out = tmp_path / "parity.toml"
    session.save(state.config, out)
    from_disk = ParityConfig.from_toml(out)
    rendered = build_figure(load(from_disk.data), from_disk.plot, from_disk.stats)

    assert rendered.to_dict() == preview.to_dict()


def test_a_saved_config_reloads_into_an_identical_designer(csv, tmp_path: Path):
    session, config, data = Session.start((csv,), None)
    state = DesignerState(config=config, data=data)
    state.update("plot", theme="light", abstol=3.0, legend="bottom")

    out = tmp_path / "parity.toml"
    session.save(state.config, out)

    reopened_session, reopened_config, reopened_data = Session.start((), out)
    reopened = DesignerState(config=reopened_config, data=reopened_data)

    assert reopened.figure().to_dict() == state.figure().to_dict()
    assert not reopened_session.is_dirty(reopened_config)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/designer/test_golden_wysiwyg.py -v`
Expected: FAIL — the module under test does not exist yet if earlier tasks are incomplete; if all are complete, this should pass immediately, which is itself the confirmation that the pieces agree.

- [ ] **Step 3: Fix any mismatch**

If a case fails, the fault is in the designer, not the test. The usual cause is a control writing a value the config accepts but `build_figure` interprets differently. Fix the designer so the two agree; do not relax the assertion.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — all previous tests plus the new designer tests.

- [ ] **Step 5: Update the docs**

Add to `README.md` after the "Config file" section:

```markdown
## Interactive designer

```bash
uv sync --extra designer
uv run parity-plot design data/example.csv -c parity.toml
```

Opens a local browser app: edit any setting and the plot updates live, then save
back to the TOML. Comments in an existing config survive the round trip.

The preview is produced by the same `build_figure` the CLI uses, so what you see
is exactly what `parity-plot plot -c parity.toml` will render. That equivalence
is pinned by a test rather than assumed.
```

Add to `CLAUDE.md` after the tolerance section:

```markdown
**The designer must never reimplement plotting.** `parity_plot/designer/` calls
`build_figure` for its preview. `tests/designer/test_golden_wysiwyg.py` asserts
that a config saved from the designer renders an identical figure through the
CLI path — if that test ever fails, the designer is lying about what the CLI
will do, and the designer is what needs fixing.

Logic lives in `state.py`, `session.py`, and `serialize.py`, all browser-free
and unit-tested; `app.py` and `panels/` only wire widgets. Anything worth
testing belongs in the pure modules.

`serialize.py` uses tomlkit rather than generating TOML, because a config meant
to be hand-edited and committed must not lose its comments on save. It also
leaves a key untouched when its value has not changed, so `reltol = "10pct"` is
not rewritten as `0.1`.

`nicegui` is an optional extra. Never import it at `parity_plot` module scope —
`designer/launch.py` imports it lazily and raises `MissingDependencyError` with
the install command.
```

- [ ] **Step 6: Verify the app really starts**

Run: `.venv/bin/parity-plot design data/example.csv --port 8099 --no-open-browser &`
then `sleep 3 && curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8099/`
Expected: `200`. Kill the server afterwards.

- [ ] **Step 7: Commit**

```bash
git add tests/designer/test_golden_wysiwyg.py README.md CLAUDE.md
git commit -m "test(designer): pin the designer/CLI figure equivalence"
```

---

## Self-Review

**Spec coverage.** Phase 1 of the spec calls for: launch with `plot`'s argument shape (Task 4), live preview via `build_figure` (Tasks 3, 6), all `PlotConfig`/`StatsConfig`/`OutputConfig` controls with `DataConfig` excluded (Task 5), tolerance inputs accepting the CLI's spellings (Task 5), save/save-as with dirty tracking (Tasks 2, 6), comment-preserving serialization (Task 1), the stale-file prompt (Tasks 2, 6), port fallback (Task 4), the missing-extra message (Task 4), the golden test (Task 7), and the error-handling table (Tasks 3, 4, 6). Phases 2 and 3 are deliberately out of scope for this plan and get their own.

**Type consistency.** `DesignerState.update(section, **values) -> bool` is used identically in Tasks 5, 6, and 7. `Session.save(config, path=None, force=False) -> Path` matches its callers in Task 6. `ControlSpec` field order matches every construction in Task 5. `build_app(session, config, data) -> DesignerState` matches its call in `launch.run`.

**Known gap, deliberate:** `state.py` has no `filters` field. The spec's state model includes one, but it is unreachable until Phase 3 introduces `FilterSet`; adding an always-empty field now would be untestable scaffolding. Phase 3's plan adds the field and its tests together.
