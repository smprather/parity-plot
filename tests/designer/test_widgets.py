"""Reading a ``ui.number`` field without trusting it.

Every designer panel that takes a number reads it straight out of a widget the
user can type into. NiceGUI's ``ui.number`` holds whatever is in the field, and
mid-edit that is often not a number at all: an empty string while clearing it,
a lone ``-``, a partially typed exponent. ``int("")`` and ``float("-")`` raise
``ValueError``, and a raise inside a sync event handler is invisible -- the
status bar never repaints, the edit is lost, and the panel simply stops
responding.

The guards are not theoretical: the fields these read are
``abstol``/``reltol`` (free typing, ``%.4g``), the manual histogram bucket
count, and the viewport origins.

This module is deliberately browser-free -- ``parity_plot.designer.widgets`` --
so the panels that use it stay unit-testable without booting a page.
"""

from __future__ import annotations

import pytest

from parity_plot.designer.widgets import as_float, as_int


@pytest.mark.parametrize(
    "value",
    ["", None, "-", "1e", "abc", "1.2.3", " ", "1,5"],
)
def test_as_float_returns_the_default_for_junk(value):
    assert as_float(value, 7.5) == 7.5


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, 1.0), (1.5, 1.5), ("2.5", 2.5), (0, 0.0), (-3, -3.0)],
)
def test_as_float_reads_a_real_number(value, expected):
    assert as_float(value) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_as_float_rejects_non_finite_numbers(value):
    """Plot data must be finite, and so must the numbers typed into a field."""
    assert as_float(value, 3.0) == 3.0


def test_as_float_default_is_optional():
    assert as_float("junk") is None
    assert as_float("2") == 2.0


@pytest.mark.parametrize("value", ["", None, "-", "abc", "2.5.1"])
def test_as_int_returns_the_default_for_junk(value):
    assert as_int(value, 10) == 10


def test_as_int_truncates_a_float_field_value():
    assert as_int(7.9, 10) == 7


def test_as_int_default_is_optional():
    assert as_int("nope") is None


def test_a_boolean_is_not_a_number_here():
    """``isinstance(True, int)`` is True in Python; a switch must not read as 1."""
    assert as_int(True, 5) == 5
    assert as_float(True, 5.0) == 5.0


def test_nan_text_is_rejected():
    assert as_float("nan", 1.0) == 1.0
    assert as_float("inf", 1.0) == 1.0
