"""The designer must not be able to lie about what the CLI will produce."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import load
from parity_plot.designer.session import Session
from parity_plot.designer.state import DesignerState
from parity_plot.plot import build_figure
from parity_plot.tolerances import PARITY_NAME, NamedTolerance

WIDE = """\
id,reference,test
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


def _state_with(csv: Path, plot: dict) -> DesignerState:
    """Build a designer state on `csv` with the given plot overrides.

    The designer's `update` routes through `ParityConfig.merge`, which rejects
    the retired scalar tolerance keys -- editing the list is Phase 3 UI work.
    These tests exercise save/reload/render equality, not the editing path, so
    they build the config directly through `from_dict`.
    """
    config = ParityConfig.from_dict(
        {"data": {"files": [str(csv)], "ref": "wide.csv:reference",
                  "test": "wide.csv:test", "join": "id"},
         "plot": plot}
    )
    state = DesignerState(config=config, data=load(config.data))
    return state


@pytest.mark.parametrize(
    "plot",
    [
        {"theme": "light"},
        {"tolerances": [{"name": "spec", "abstol": 2.0}]},
        {"tolerances": [{"name": "spec", "reltol": 0.1}]},
        {
            "tolerances": [
                {"name": "spec", "abstol": 2.0, "reltol": 0.1, "style": "shaded"},
            ]
        },
        {"legend": "bottom", "nulls": "drop"},
        {
            "tolerances": [
                {"name": "parity", "builtin": True, "enabled": False},
                {"name": "spec", "reltol": 0.1},
            ]
        },
        {"title": "Lab run 7", "x_label": "golden", "y_label": "DUT"},
        {"equal_axes": False},
        {
            "tolerances": [
                {"name": "loose", "reltol": 0.25, "style": "lines"},
                {"name": "tight", "reltol": 0.05},
            ],
            "legend": "none",
        },
    ],
)
def test_designer_preview_equals_what_the_cli_renders(csv, tmp_path: Path, plot):
    """Edit in the designer, save, reload through the CLI path, compare figures.

    If this fails, a config built in the designer renders differently from the
    designer's own preview -- which makes every saved config untrustworthy.
    """
    state = _state_with(csv, plot)
    assert state.last_error is None, state.last_error

    preview = state.figure()

    out = tmp_path / "parity.toml"
    Session().save(state.config, out)
    from_disk = ParityConfig.from_toml(out)
    rendered = build_figure(load(from_disk.data), from_disk.plot, from_disk.stats)

    assert rendered.to_dict() == preview.to_dict()


def test_stats_settings_also_survive_the_round_trip(csv, tmp_path: Path):
    session, config, data = Session.start((csv,), None)
    state = DesignerState(config=config, data=data)
    assert state.update("stats", show=False), state.last_error

    preview = state.figure()

    out = tmp_path / "parity.toml"
    session.save(state.config, out)
    from_disk = ParityConfig.from_toml(out)
    rendered = build_figure(load(from_disk.data), from_disk.plot, from_disk.stats)

    assert rendered.to_dict() == preview.to_dict()
    assert rendered.layout.annotations == ()


def test_a_saved_config_reloads_into_an_identical_designer(csv, tmp_path: Path):
    state = _state_with(
        csv,
        {
            "theme": "light",
            "legend": "bottom",
            "tolerances": [{"name": "spec", "abstol": 3.0}],
        },
    )

    out = tmp_path / "parity.toml"
    Session().save(state.config, out)

    reopened_session, reopened_config, reopened_data = Session.start((), out)
    reopened = DesignerState(config=reopened_config, data=reopened_data)

    assert reopened.figure().to_dict() == state.figure().to_dict()
    assert not reopened_session.is_dirty(reopened_config)


def test_the_cli_plot_command_renders_a_designer_config(csv, tmp_path: Path):
    """The end the user actually reaches: design, save, then `parity-plot plot -c`."""
    from click.testing import CliRunner

    from parity_plot.cli import cli

    state = _state_with(
        csv, {"theme": "light", "tolerances": [{"name": "spec", "reltol": 0.1}]}
    )

    toml_path = tmp_path / "parity.toml"
    Session().save(state.config, toml_path)

    html = tmp_path / "out.html"
    result = CliRunner().invoke(
        cli, ["plot", "-c", str(toml_path), "-o", str(html), "--no-open-browser"]
    )

    assert result.exit_code == 0, result.output
    assert html.exists()


def test_comments_in_a_config_survive_a_designer_save(csv, tmp_path: Path):
    """A config is hand-edited and committed; saving must not strip its comments."""
    toml_path = tmp_path / "parity.toml"
    toml_path.write_text(
        "# lab tolerance policy, agreed 2026-03\n"
        "[plot]\n"
        "# dark reads better on the bench projector\n"
        'theme = "dark"\n'
        "[[plot.tolerances]]\n"
        'name = "spec"\n'
        "reltol = 0.10\n"
        f'\n[data]\nfiles = ["{csv.as_posix()}"]\nref = "wide.csv:reference"\n'
        f'test = "wide.csv:test"\njoin = "id"\n',
        encoding="utf-8",
    )

    session, config, data = Session.start((), toml_path)
    state = DesignerState(config=config, data=data)
    state.update("plot", theme="light")
    session.save(state.config)

    saved = toml_path.read_text(encoding="utf-8")
    assert "# lab tolerance policy, agreed 2026-03" in saved
    assert "# dark reads better on the bench projector" in saved
    assert 'theme = "light"' in saved


def test_a_multi_tolerance_config_round_trips_identically(csv, tmp_path: Path):
    """Several tolerances plus a customised parity entry: the serializer must
    write them all, and reloading must produce the same figure the designer
    previewed. This is the case the plan calls out -- if it fails, the
    serializer is emitting something `from_toml` reads back differently."""
    disabled_parity = NamedTolerance(
        name=PARITY_NAME, builtin=True, kind="info", enabled=False
    )
    state = _state_with(
        csv,
        {
            "theme": "light",
            "log": True,
            "tolerances": [
                disabled_parity,
                {"name": "loose", "reltol": 0.25, "style": "shaded"},
                {"name": "tight", "abstol": 1.0, "reltol": 0.05},
            ],
        },
    )
    assert state.last_error is None, state.last_error

    preview = state.figure()

    out = tmp_path / "parity.toml"
    Session().save(state.config, out)
    from_disk = ParityConfig.from_toml(out)
    rendered = build_figure(load(from_disk.data), from_disk.plot, from_disk.stats)

    assert from_disk.plot.tolerances == state.config.plot.tolerances
    assert rendered.to_dict() == preview.to_dict()