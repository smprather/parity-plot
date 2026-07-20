# tests/designer/test_table_panel.py
from __future__ import annotations

from parity_plot.designer.panels.table import summary_text


def test_summary_states_both_numbers_when_filtered():
    """A filtered view that looks unfiltered is a trap."""
    assert summary_text(14, 1000) == "showing 14 of 1,000"


def test_summary_is_plain_when_nothing_is_hidden():
    assert summary_text(1000, 1000) == "1,000 records"


def test_summary_handles_an_empty_result():
    assert summary_text(0, 1000) == "showing 0 of 1,000"


def test_summary_handles_an_empty_dataset():
    assert summary_text(0, 0) == "0 records"