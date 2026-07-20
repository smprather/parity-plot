# tests/designer/test_data_panel.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.designer.panels.data_panel import mapping_options

WIDE = "id,reference,measured\nA1,10.0,11.0\n"
JOIN_X = "id,value\nA1,10.0\n"
JOIN_Y = "id,value\nA1,11.0\n"


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_one_file_offers_its_own_columns(tmp_path):
    path = write(tmp_path, "wide.csv", WIDE)
    options = mapping_options((path,))
    assert options["key"] == ["id", "reference", "measured"]
    assert options["x"] == ["id", "reference", "measured"]


def test_two_files_offer_only_columns_common_to_both(tmp_path):
    """In join mode the key must exist in both files or the join cannot run."""
    x = write(tmp_path, "x.csv", JOIN_X)
    y = write(tmp_path, "y.csv", JOIN_Y)
    assert mapping_options((x, y))["key"] == ["id", "value"]


def test_two_files_with_nothing_in_common_offer_no_key(tmp_path):
    x = write(tmp_path, "x.csv", "a,b\n1,2\n")
    y = write(tmp_path, "y.csv", "c,d\n3,4\n")
    assert mapping_options((x, y))["key"] == []


def test_no_paths_offers_nothing(tmp_path):
    assert mapping_options(()) == {"key": [], "x": [], "y": []}


def test_an_unreadable_file_yields_empty_options_rather_than_raising(tmp_path):
    """The panel must still render so the user can pick a different file."""
    assert mapping_options((tmp_path / "ghost.csv",)) == {"key": [], "x": [], "y": []}