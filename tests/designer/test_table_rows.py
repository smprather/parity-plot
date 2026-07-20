# tests/designer/test_table_rows.py
from __future__ import annotations

import pytest

from parity_plot.designer.records import RecordView
from parity_plot.designer.table_rows import COLUMNS, to_rows


@pytest.fixture
def views():
    return [
        RecordView("a", 10.0, 11.0, 1.0, 0.1, "paired", ("spec",)),
        RecordView("b", 100.0, 101.0, 1.0, 0.01, "paired", ()),
        RecordView("d", 70.0, None, None, None, "missing y", None),
    ]


def test_every_column_is_sortable():
    """Sorting by absolute error is the question this table exists to answer."""
    assert COLUMNS
    assert all(column["sortable"] for column in COLUMNS)


def test_column_fields_match_the_row_keys(views):
    row = to_rows(views)[0]
    for column in COLUMNS:
        assert column["field"] in row


def test_row_key_column_comes_first():
    assert COLUMNS[0]["field"] == "key"


def test_numbers_stay_numbers_so_sorting_is_numeric(views):
    """Formatted strings would sort lexically: 9 after 100."""
    row = to_rows(views)[0]
    assert isinstance(row["x"], float)
    assert isinstance(row["error"], float)


def test_numbers_are_rounded_for_display(views):
    rows = to_rows([RecordView("z", 1 / 3, 2 / 3, 1 / 3, 1 / 3, "paired", None)])
    assert rows[0]["x"] == pytest.approx(0.333333, abs=1e-6)
    assert len(str(rows[0]["x"])) < 12


def test_relative_error_is_shown_as_a_percentage(views):
    assert to_rows(views)[0]["rel_error"] == pytest.approx(10.0)
    assert to_rows(views)[1]["rel_error"] == pytest.approx(1.0)


def test_missing_values_are_none_not_zero(views):
    row = next(r for r in to_rows(views) if r["key"] == "d")
    assert row["y"] is None
    assert row["error"] is None
    assert row["rel_error"] is None


def test_verdict_reads_as_words(views):
    rows = {r["key"]: r for r in to_rows(views)}
    assert rows["a"]["verdict"] == "spec"        # failed the "spec" tolerance
    assert rows["b"]["verdict"] == "pass"        # judged and passed
    assert rows["d"]["verdict"] == ""            # never judged, so no verdict claimed


def test_status_is_carried_through(views):
    rows = {r["key"]: r for r in to_rows(views)}
    assert rows["d"]["status"] == "missing y"


def test_empty_input_gives_no_rows():
    assert to_rows([]) == []