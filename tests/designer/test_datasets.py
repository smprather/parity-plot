# tests/designer/test_datasets.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.designer.datasets import Peek, peek, suggest_mapping


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_peek_reads_headers_and_one_sample_row(tmp_path):
    path = write(tmp_path, "a.csv", "id,reference,measured\nA1,10.0,11.0\nA2,20.0,21.0\n")

    result = peek(path)

    assert result.columns == ["id", "reference", "measured"]
    assert result.sample == {"id": "A1", "reference": "10.0", "measured": "11.0"}


def test_peek_identifies_numeric_columns(tmp_path):
    path = write(tmp_path, "a.csv", "id,reference,measured\nA1,10.0,11.0\n")
    assert peek(path).numeric == {"reference", "measured"}


def test_peek_does_not_read_the_whole_file(tmp_path):
    """A large file must not be pulled into memory just to list its columns."""
    rows = "\n".join(f"A{i},{i}.0,{i}.5" for i in range(200_000))
    path = write(tmp_path, "big.csv", f"id,reference,measured\n{rows}\n")

    result = peek(path)

    assert result.columns == ["id", "reference", "measured"]
    assert result.sample["id"] == "A0"


def test_peek_handles_a_header_only_file(tmp_path):
    path = write(tmp_path, "empty.csv", "id,reference,measured\n")
    result = peek(path)
    assert result.columns == ["id", "reference", "measured"]
    assert result.sample == {}
    assert result.numeric == set()


def test_peek_reports_a_missing_file_by_name(tmp_path):
    from parity_plot.data import DataError

    with pytest.raises(DataError, match="not found"):
        peek(tmp_path / "nope.csv")


def test_peek_reports_an_empty_file(tmp_path):
    from parity_plot.data import DataError

    path = write(tmp_path, "empty.csv", "")
    with pytest.raises(DataError, match="empty"):
        peek(path)


@pytest.mark.parametrize(
    "columns, expected",
    [
        (["id", "reference", "measured"], {"key": "id", "x": "reference", "y": "measured"}),
        (["name", "expected", "actual"], {"key": "name", "x": "expected", "y": "actual"}),
        (["part", "golden", "dut"], {"key": "part", "x": "golden", "y": "dut"}),
        (["serial", "ref", "meas"], {"key": "serial", "x": "ref", "y": "meas"}),
    ],
)
def test_suggest_mapping_recognises_common_names(columns, expected):
    sample = {c: ("A1" if i == 0 else "1.0") for i, c in enumerate(columns)}
    numeric = {c for c in columns[1:]}
    assert suggest_mapping(Peek(columns, sample, numeric)) == expected


def test_suggest_mapping_falls_back_to_the_first_numeric_columns():
    """Unrecognised names still need a usable starting guess."""
    peeked = Peek(
        columns=["tag", "alpha", "beta"],
        sample={"tag": "T1", "alpha": "1.0", "beta": "2.0"},
        numeric={"alpha", "beta"},
    )
    assert suggest_mapping(peeked) == {"key": "tag", "x": "alpha", "y": "beta"}


def test_suggest_mapping_leaves_gaps_when_there_is_nothing_to_guess():
    peeked = Peek(columns=["only"], sample={"only": "x"}, numeric=set())
    assert suggest_mapping(peeked) == {"key": "only", "x": None, "y": None}


def test_suggest_mapping_never_reuses_one_column_twice():
    peeked = Peek(columns=["value"], sample={"value": "1.0"}, numeric={"value"})
    guess = suggest_mapping(peeked)
    chosen = [v for v in guess.values() if v is not None]
    assert len(chosen) == len(set(chosen))