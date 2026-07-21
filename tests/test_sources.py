# tests/test_sources.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import DEFAULT_NA_VALUES
from parity_plot.data import DataError
from parity_plot.sources import Sources, open_sources


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_opens_a_file_and_lists_qualified_columns(tmp_path):
    f = write(tmp_path, "meas.csv", "id,voltage,batch\nA1,10.0,x\nA2,20.0,y\n")
    src = open_sources((f,))
    assert src.columns() == ["meas.csv:id", "meas.csv:voltage", "meas.csv:batch"]


def test_resolve_returns_the_column_values(tmp_path):
    f = write(tmp_path, "meas.csv", "id,voltage\nA1,10.0\nA2,20.0\n")
    col = open_sources((f,)).resolve("meas.csv:voltage")
    assert col.name == "voltage"
    assert col.values == ["10.0", "20.0"]


def test_numeric_columns_excludes_text(tmp_path):
    f = write(tmp_path, "d.csv", "id,voltage,label\nA1,10.0,hi\nA2,20.0,lo\n")
    src = open_sources((f,))
    # id is text (A1/A2), label is text; only voltage is numeric.
    assert src.numeric_columns(DEFAULT_NA_VALUES) == ["d.csv:voltage"]


def test_a_column_of_integers_counts_as_numeric(tmp_path):
    f = write(tmp_path, "d.csv", "n\n1\n2\n3\n")
    assert open_sources((f,)).numeric_columns(DEFAULT_NA_VALUES) == ["d.csv:n"]


def test_blank_cells_do_not_disqualify_a_numeric_column(tmp_path):
    f = write(tmp_path, "d.csv", "v\n1.0\n\n3.0\n")
    assert open_sources((f,)).numeric_columns(DEFAULT_NA_VALUES) == ["d.csv:v"]


def test_resolve_splits_on_the_last_colon(tmp_path):
    # a column literally named with a colon is unusual, but the file part is
    # matched first, so the remainder is the column.
    f = write(tmp_path, "meas.csv", "id,v\nA1,1.0\n")
    assert open_sources((f,)).resolve("meas.csv:v").name == "v"


def test_basename_resolves_when_unique(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    f = write(sub, "meas.csv", "id,v\nA1,1.0\n")
    src = open_sources((f,))
    assert src.resolve("meas.csv:v").name == "v"          # basename
    assert src.resolve(f"{f}:v").name == "v"               # full path also works


def test_ambiguous_basename_requires_the_full_path(tmp_path):
    a = write(tmp_path / "one", "meas.csv", "id,v\nA,1\n") if (tmp_path / "one").mkdir() or True else None
    b = write(tmp_path / "two", "meas.csv", "id,v\nB,2\n") if (tmp_path / "two").mkdir() or True else None
    src = open_sources((a, b))
    with pytest.raises(DataError, match="ambiguous"):
        src.resolve("meas.csv:v")
    assert src.resolve(f"{a}:v").values == ["1"]           # full path disambiguates


def test_resolve_reports_an_unknown_file(tmp_path):
    f = write(tmp_path, "meas.csv", "id,v\nA1,1.0\n")
    with pytest.raises(DataError, match="no open file"):
        open_sources((f,)).resolve("ghost.csv:v")


def test_resolve_reports_an_unknown_column(tmp_path):
    f = write(tmp_path, "meas.csv", "id,v\nA1,1.0\n")
    with pytest.raises(DataError, match="nope"):
        open_sources((f,)).resolve("meas.csv:nope")


def test_a_missing_file_is_reported_by_name(tmp_path):
    with pytest.raises(DataError, match="not found"):
        open_sources((tmp_path / "ghost.csv",))


def test_length_is_the_row_count(tmp_path):
    f = write(tmp_path, "d.csv", "v\n1\n2\n3\n")
    assert open_sources((f,)).length(f) == 3