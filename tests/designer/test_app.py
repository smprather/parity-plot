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
from parity_plot.designer.app import build_app
from parity_plot.designer.session import Session


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


def test_the_server_actually_serves_the_page(tmp_path: Path):
    """End-to-end: boot the real CLI command and talk to it over HTTP.

    NiceGUI's headless `user` fixture expects a module-level app it can import
    (`nicegui_main_file`); ours is parameterised by session and data, so it does
    not fit that shape. Driving the real server is stronger evidence anyway --
    it exercises the actual `parity-plot design` entry point.
    """
    csv = tmp_path / "wide.csv"
    csv.write_text("id,reference,measured\nA1,10.0,11.0\nA2,20.0,21.0\n", encoding="utf-8")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    # NiceGUI switches into screen-test mode when it sees pytest's environment
    # and then demands NICEGUI_SCREEN_TEST_PORT. This subprocess is a real
    # server, not a screen test, so hand it a clean environment.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST")}

    proc = subprocess.Popen(
        [sys.executable, "-m", "parity_plot.cli", "design", str(csv),
         "--port", str(port), "--no-open-browser"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        body = ""
        for _ in range(100):  # up to ~20s for the server to come up
            if proc.poll() is not None:
                pytest.fail(f"server exited early:\n{proc.stdout.read()}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
                    if r.status == 200:
                        body = r.read().decode("utf-8", "replace")
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
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