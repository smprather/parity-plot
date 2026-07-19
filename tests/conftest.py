from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    """Stop the test suite from launching browser windows.

    Opening the result is on by default, so without this every CLI test would
    spawn a real window. Yields the list of URIs that *would* have been opened,
    which is also how the open-behaviour tests assert.
    """
    opened: list[str] = []
    monkeypatch.setattr(
        "webbrowser.open", lambda uri, *a, **kw: opened.append(uri) or True
    )
    return opened


@pytest.fixture
def write_csv(tmp_path: Path):
    """Write a CSV from literal (indented) text and return its path."""

    def _write(name: str, text: str) -> Path:
        path = tmp_path / name
        path.write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")
        return path

    return _write


@pytest.fixture
def wide_csv(write_csv):
    """A small wide file covering every null case.

    A2 has no measured value, A4 has no reference, A5 has neither.
    """
    return write_csv(
        "wide.csv",
        """
        id,reference,measured
        A1,10.0,11.0
        A2,20.0,
        A3,30.0,29.0
        A4,,41.0
        A5,,
        """,
    )
