# tests/designer/test_launch.py
from __future__ import annotations

import builtins
from pathlib import Path

import pytest
from click.testing import CliRunner

from parity_plot.cli import cli
from parity_plot.designer.launch import MissingDependencyError, require_nicegui

WIDE = "id,reference,test\nA1,10.0,11.0\nA2,20.0,21.0\n"


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


def test_design_reports_a_bad_csv_without_a_traceback(tmp_path):
    """`run` is deliberately NOT stubbed here.

    Loading happens before any UI is built, so a bad CSV fails on the real code
    path without a server ever starting. Stubbing `run` would stub out the very
    thing under test.
    """
    # Only one numeric column: the single-file default needs two, so the load
    # fails with a clear message rather than a traceback.
    bad = tmp_path / "bad.csv"
    bad.write_text("id,reference,note\nA1,1.0,oops\n", encoding="utf-8")

    result = CliRunner().invoke(cli, ["design", str(bad), "--no-open-browser"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "numeric" in result.output  # names the problem: not enough numeric columns


def test_bad_input_fails_before_any_server_starts(tmp_path, monkeypatch):
    """Validation must precede the UI, not follow it."""
    started = []
    monkeypatch.setattr(
        "parity_plot.designer.launch.free_port", lambda p: started.append(p) or p
    )
    bad = tmp_path / "bad.csv"
    bad.write_text("id,reference,test\nA1,1.0,oops\n", encoding="utf-8")

    CliRunner().invoke(cli, ["design", str(bad), "--no-open-browser"])

    assert started == []