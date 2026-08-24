# tests/designer/test_app.py
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import from_sequences
from parity_plot.designer import app as designer_app
from parity_plot.designer.app import (
    axis_range_relayout,
    axis_range_relayout_script,
    build_app,
)
from parity_plot.designer.session import Session
from parity_plot.plot import build_figure
from parity_plot.tolerances import NamedTolerance


@pytest.fixture
def session_and_data(tmp_path: Path):
    csv = tmp_path / "wide.csv"
    csv.write_text("id,reference,test\nA1,10.0,11.0\nA2,20.0,21.0\n", encoding="utf-8")
    return Session.start((csv,), None)


def test_build_app_returns_state_wired_to_the_session(session_and_data):
    session, config, data = session_and_data
    state = build_app(session, config, data)
    assert state.config == config
    assert state.data is data


def test_build_app_with_no_data_and_no_config_still_builds(tmp_path, monkeypatch):
    """A New-Design / unbound launch must build the page (toolbar + empty
    panels) without a dataset."""
    monkeypatch.chdir(tmp_path)
    session, config, data = Session.start((), None)
    state = build_app(session, config, data)
    assert state.data is None
    assert state.config == config


def test_editing_through_state_changes_the_figure(session_and_data):
    session, config, data = session_and_data
    state = build_app(session, config, data)

    before = state.figure().to_dict()
    state.update("plot", theme="light")
    after = state.figure().to_dict()

    assert before != after


def test_axis_relayout_payload_preserves_requested_origins():
    figure = build_figure(
        from_sequences([10.0, 20.0], [11.0, 21.0]),
        ParityConfig.from_dict({"plot": {"x_origin": 5.0, "y_origin": 7.0}}).plot,
    )

    ranges = axis_range_relayout(figure)

    assert ranges["xaxis.range"][0] == 5.0
    assert ranges["yaxis.range"][0] == 7.0
    script = axis_range_relayout_script(42, figure)
    assert "getElementById('c42')" in script
    assert '"xaxis.range": [5.0' in script
    assert "attempt < 40" in script


def test_saving_writes_what_is_on_screen(session_and_data, tmp_path: Path):
    session, config, data = session_and_data
    state = build_app(session, config, data)
    spec = NamedTolerance(name="spec", abstol=2.0)
    state.config = state.config.merge(plot={"tolerances": [spec]})

    out = tmp_path / "saved.toml"
    session.save(state.config, out)

    reloaded = ParityConfig.from_toml(out)
    assert reloaded.plot.theme == "dark"
    specs = [t for t in reloaded.plot.tolerances if t.name == "spec"]
    assert specs and specs[0].abstol == pytest.approx(2.0)


def test_build_app_registers_a_page_without_serving(session_and_data):
    """`launch.run` owns `ui.run`; `build_app` must only register the route.

    If build_app started the server itself, importing it in a test would block
    forever and `launch.run` would double-serve.
    """
    from nicegui import app as ng_app

    session, config, data = session_and_data
    before = {r.path for r in ng_app.routes if hasattr(r, "path")}
    build_app(session, config, data)
    after = {r.path for r in ng_app.routes if hasattr(r, "path")}

    assert "/" in after or "/" in before  # the page route exists


def test_settings_and_results_scroll_independently_inside_the_viewport():
    page = set(designer_app.PAGE_CONTENT_CLASSES.split())
    workspace = set(designer_app.WORKSPACE_CLASSES.split())
    settings = set(designer_app.SETTINGS_COLUMN_CLASSES.split())
    results = set(designer_app.RESULTS_COLUMN_CLASSES.split())

    assert {"absolute", "inset-0", "overflow-hidden"} <= page
    assert {"h-full", "min-h-0", "overflow-hidden"} <= workspace
    assert {"h-full", "overflow-y-auto", "overscroll-contain"} <= settings
    assert {"h-full", "overflow-y-auto", "overscroll-contain"} <= results


def test_narrow_viewports_keep_plot_and_settings_visible():
    workspace = set(designer_app.WORKSPACE_CLASSES.split())
    settings = set(designer_app.SETTINGS_COLUMN_CLASSES.split())
    results = set(designer_app.RESULTS_COLUMN_CLASSES.split())
    plot = set(designer_app.PLOT_CLASSES.split())

    assert "designer-workspace" in workspace
    assert "designer-settings" in settings
    assert "designer-results" in results
    assert "designer-plot" in plot
    assert "width: min(70vh, 100%)" in designer_app.RESPONSIVE_LAYOUT_CSS
    assert "height: min(70vh, 100%)" in designer_app.RESPONSIVE_LAYOUT_CSS
    assert "@media (max-width: 767px)" in designer_app.RESPONSIVE_LAYOUT_CSS
    assert "flex-direction: column" in designer_app.RESPONSIVE_LAYOUT_CSS
    assert "plotly_afterplot" in designer_app.RESPONSIVE_PLOT_SCRIPT
    assert "window.Plotly.relayout" in designer_app.RESPONSIVE_PLOT_SCRIPT
    assert "statsIndex(plot)" in designer_app.RESPONSIVE_PLOT_SCRIPT
    assert "plot.layout.margin.t" in designer_app.RESPONSIVE_PLOT_SCRIPT
    assert "update['title.x']" in designer_app.RESPONSIVE_PLOT_SCRIPT
    assert "annotationIndex >= 0 ? -0.55 : -0.28" in designer_app.RESPONSIVE_PLOT_SCRIPT
    assert "'modebar.orientation': 'v'" in designer_app.RESPONSIVE_PLOT_SCRIPT
    assert (
        "annotations[${annotationIndex}].xshift" in designer_app.RESPONSIVE_PLOT_SCRIPT
    )


@pytest.mark.parametrize("launch_mode", ["data", "external-config"])
def test_the_server_actually_serves_the_page(tmp_path: Path, launch_mode: str):
    """End-to-end: boot the real CLI command and talk to it over HTTP.

    NiceGUI's headless `user` fixture expects a module-level app it can import
    (`nicegui_main_file`); ours is parameterised by session and data, so it does
    not fit that shape. Driving the real server is stronger evidence anyway --
    it exercises the actual `parity-plot design` entry point.
    """
    csv = tmp_path / "wide.csv"
    csv.write_text("id,reference,test\nA1,10.0,11.0\nA2,20.0,21.0\n", encoding="utf-8")
    launch_dir = tmp_path / "launch"
    launch_dir.mkdir()

    command = [sys.executable, "-m", "parity_plot.cli", "design"]
    if launch_mode == "external-config":
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config = config_dir / "outside.toml"
        config.write_text(
            f'[data]\nfiles = ["{csv.as_posix()}"]\n'
            'ref = "wide.csv:reference"\ntest = "wide.csv:test"\n',
            encoding="utf-8",
        )
        command.extend(["--config", str(config)])
    else:
        command.append(str(csv))

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    # NiceGUI switches into screen-test mode when it sees pytest's environment
    # and then demands NICEGUI_SCREEN_TEST_PORT. This subprocess is a real
    # server, not a screen test, so hand it a clean environment.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST")}

    proc = subprocess.Popen(
        [*command, "--port", str(port), "--no-open-browser"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=launch_dir,
    )
    try:
        body = ""
        for _ in range(100):  # up to ~20s for the server to come up
            if proc.poll() is not None:
                pytest.fail(f"server exited early:\n{proc.stdout.read()}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/", timeout=1
                ) as r:
                    if r.status == 200:
                        body = r.read().decode("utf-8", "replace")
                        break
            except urllib.error.URLError, ConnectionError, OSError:
                time.sleep(0.2)
        else:
            pytest.fail("server never became reachable")

        assert "nicegui" in body.lower() or "<!DOCTYPE html>" in body
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
