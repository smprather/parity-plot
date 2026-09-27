"""A CSV that is not valid UTF-8 must fail like every other data error.

The three readers -- ``data._read_rows`` (the full load), and ``datasets.peek``
/ ``preview`` (the column picker and the peek dialog) -- wrapped only
``OSError``. A file with a latin-1 byte raises ``UnicodeDecodeError``, which is
a ``ValueError``, and an over-long field raises ``csv.Error``; both escaped
unwrapped.

The consequence was different in each place, and all of it bad: the CLI printed
``'utf-8' codec can't decode byte 0xe9`` with no file name; the column picker
caught only ``DataError``, so the background task died silently -- the file
appeared in the list and nothing loaded, with no message; and at panel build
the same escape was an HTTP 500.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import DataError, load
from parity_plot.designer.datasets import peek, preview


def latin1(tmp_path: Path) -> Path:
    """A CSV whose second column is not valid UTF-8."""
    p = tmp_path / "bad.csv"
    p.write_bytes(b"id,reference,test\nA1,10,caf\xe9\n")
    return p


def overlong_field(tmp_path: Path) -> Path:
    """A single field past csv's default 128 KiB limit -> csv.Error."""
    p = tmp_path / "wide.csv"
    p.write_text("id,v\n" + "A," + "x" * 200_000 + "\n", encoding="utf-8")
    return p


def test_loading_a_non_utf8_csv_names_the_file(tmp_path):
    f = latin1(tmp_path)
    config = ParityConfig().merge(
        data={"files": (f,), "ref": "bad.csv:id", "test": "bad.csv:reference"}
    )
    with pytest.raises(DataError) as excinfo:
        load(config.data)
    message = str(excinfo.value)
    assert "bad.csv" in message
    # And it has to say what is wrong, not just which file.
    assert "utf-8" in message.lower()


def test_loading_an_overlong_field_names_the_file(tmp_path):
    f = overlong_field(tmp_path)
    config = ParityConfig().merge(
        data={"files": (f,), "ref": "wide.csv:id", "test": "wide.csv:v"}
    )
    with pytest.raises(DataError) as excinfo:
        load(config.data)
    assert "wide.csv" in str(excinfo.value)


def test_peek_on_a_non_utf8_csv_raises_data_error(tmp_path):
    with pytest.raises(DataError) as excinfo:
        peek(latin1(tmp_path))
    assert "bad.csv" in str(excinfo.value)


def test_peek_on_an_overlong_field_raises_data_error(tmp_path):
    with pytest.raises(DataError) as excinfo:
        peek(overlong_field(tmp_path))
    assert "wide.csv" in str(excinfo.value)


def test_preview_on_a_non_utf8_csv_raises_data_error(tmp_path):
    with pytest.raises(DataError) as excinfo:
        preview(latin1(tmp_path))
    assert "bad.csv" in str(excinfo.value)


def test_preview_on_an_overlong_field_raises_data_error(tmp_path):
    with pytest.raises(DataError) as excinfo:
        preview(overlong_field(tmp_path))
    assert "wide.csv" in str(excinfo.value)


def test_the_picker_survives_a_bad_file_and_still_offers_the_good_one(tmp_path):
    """The panel must render, not die: ``column_options`` catches DataError only.

    This is the exact case from the scan -- the background task used to die, the
    file was listed, nothing loaded, and there was no message anywhere.
    """
    from parity_plot.designer.panels.data_panel import column_options

    bad = latin1(tmp_path)
    good = tmp_path / "good.csv"
    good.write_text("id,reference,test\nA,1,2\n", encoding="utf-8")

    options = column_options(
        (bad, good), ref="good.csv:reference", test="good.csv:test"
    )
    assert "good.csv:reference" in options["ref"]


def test_a_utf8_bom_is_still_stripped(tmp_path):
    """The decode error handling must not break the BOM tolerance."""
    p = tmp_path / "bom.csv"
    p.write_bytes("id,v\nA,1\n".encode("utf-8-sig"))
    assert peek(p).columns == ["id", "v"]
