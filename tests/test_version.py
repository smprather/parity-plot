"""The version is a CalVer date, declared in exactly one place.

Two things are guarded here, and neither was guarded before.

**Drift.** ``pyproject.toml`` and ``parity_plot.__version__`` are two
hand-edited copies of the same fact. Nothing compared them, so a release could
ship a wheel stamped one version while ``--version`` printed another, and the
only way to notice was to inspect the artifact.

**Shape.** The project moved to calendar versioning (``YYYY.M.N``), which is
valid PEP 440 -- year, month, release-within-month. That only helps if the number
actually *is* a date: under PEP 440 a bare ``9.2`` would be micro ``9.2`` and
compare as greater than every month-numbered release, silently breaking
resolution for anyone pinning a range.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from parity_plot import __version__

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# YYYY.M.N -- a 4-digit year, a 1-or-2-digit month, a 1-or-2-digit sequence.
# Unpadded on purpose: 2026.9.1, not 2026.09.01. PEP 440 reads both as
# (2026, 9, 1), but the padded form invites being read as a date by something
# that is not a version parser, and the padded form sorts identically -- so
# there is nothing to gain and a year-looking string to lose.
CALVER = re.compile(r"^(?P<year>\d{4})\.(?P<month>\d{1,2})\.(?P<sequence>\d{1,2})$")


def declared_version() -> str:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def test_the_version_is_a_calendar_version():
    assert CALVER.match(__version__), (
        f"{__version__!r} is not YYYY.M.N calendar versioning"
    )


def test_the_month_is_a_real_month():
    match = CALVER.match(__version__)
    assert match, "shape asserted elsewhere; this only reads the groups"
    month = int(match["month"])
    assert 1 <= month <= 12, f"month {month} is not a calendar month"


def test_pyproject_and_dunder_version_cannot_drift():
    """Two hand-edited copies of one fact is a release-time trap.

    The wheel's version comes from pyproject; ``parity-plot --version`` and
    every doc that quotes ``__version__`` come from the module. A bump that
    touches only one of them publishes an artifact that disagrees with itself.
    """
    assert declared_version() == __version__


def test_the_version_survives_a_pep440_round_trip():
    """PEP 440 must read it back exactly, or dependency resolution is guessing."""
    packaging_version = pytest.importorskip("packaging.version")
    parsed = packaging_version.Version(__version__)
    assert str(parsed) == __version__
    assert parsed.epoch == 0, "an epoch would outrank every other release"


def test_the_month_rolls_over_into_the_next_year():
    """The property that makes the scheme a date rather than a counter.

    Under PEP 440 these are just numbers, so this is the one place the intent is
    written down: month 12 must not sort above January of the next year.
    """
    packaging_version = pytest.importorskip("packaging.version")
    v = packaging_version.Version
    assert v("2027.1.1") > v("2026.12.9")
    assert v("2026.10.1") > v("2026.9.9")


def test_the_sequence_orders_within_a_month():
    """Two releases in one month differ only in the third component."""
    packaging_version = pytest.importorskip("packaging.version")
    v = packaging_version.Version
    assert v("2026.9.1") < v("2026.9.2")
