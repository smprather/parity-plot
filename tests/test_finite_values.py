"""Numeric plot data must be finite -- including the colour channel.

The convention holds for ref and test (``_parse`` rejects infinity, maps NaN to
a null) and is documented as a project-wide rule, but the colour channel never
went through it: ``_require_numeric`` only asks ``float(text)``, which happily
accepts ``"inf"``, and ``_color_value`` then stored it. The result is a
``color_values`` list holding a non-finite float, which is exactly what the
finite-data convention exists to prevent -- and a colorscale handed an infinity
is a plotly rendering error, not a plot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import DataError, ParityData, load


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def load_with_colour(tmp_path: Path, colour: str) -> ParityData:
    f = write(
        tmp_path,
        "d.csv",
        f"id,reference,test,temp\nA1,10,11,{colour}\nA2,20,22,30\n",
    )
    return load(
        ParityConfig()
        .merge(
            data={
                "files": (f,),
                "ref": "d.csv:reference",
                "test": "d.csv:test",
                "color_column": "d.csv:temp",
            }
        )
        .data
    )


def test_an_infinite_colour_value_is_rejected(tmp_path):
    with pytest.raises(DataError) as excinfo:
        load_with_colour(tmp_path, "inf")
    # The message has to name the file, or it is unactionable in a designer
    # that is showing a column picker rather than a CSV.
    assert "temp" in str(excinfo.value)


def test_a_negative_infinite_colour_value_is_rejected(tmp_path):
    with pytest.raises(DataError):
        load_with_colour(tmp_path, "-inf")


def test_a_nan_colour_value_is_a_null_not_an_error(tmp_path):
    """NaN means "no reading", like a blank cell -- the same as everywhere else."""
    data = load_with_colour(tmp_path, "nan")
    assert data.color_values == [None, 30.0]


def test_a_blank_colour_value_is_a_null(tmp_path):
    data = load_with_colour(tmp_path, "")
    assert data.color_values == [None, 30.0]


def test_ordinary_colour_values_still_load(tmp_path):
    data = load_with_colour(tmp_path, "20.5")
    assert data.color_values == [20.5, 30.0]
    assert data.color_label == "temp"


def test_an_infinite_column_is_not_offered_as_numeric(tmp_path):
    """The same leniency in the picker: ``inf`` is not a number a colour can be.

    ``column_options`` gates the colour column on ``_is_numeric``, so leaving
    infinity acceptable there means the designer offers a column that then
    fails to load -- the worst of both.
    """
    from parity_plot.designer.panels.data_panel import column_options

    f = write(tmp_path, "d.csv", "id,reference,test,temp\nA1,10,11,inf\n")
    options = column_options((f,), ref="d.csv:reference", test="d.csv:test")
    assert "d.csv:temp" not in options["color_column"]


def test_an_infinite_axis_column_is_not_offered_either(tmp_path):
    """``float("inf")`` parses, so the numeric test has to reject it itself.

    Without that, the picker offers a column that then fails to load -- the
    worst of both. The sibling ``test`` column is genuinely numeric and stays.
    """
    from parity_plot.designer.panels.data_panel import column_options

    f = write(tmp_path, "d.csv", "id,reference,test\nA1,inf,11\nA2,20,22\n")
    options = column_options((f,))
    assert "d.csv:reference" not in options["ref"]
    assert "d.csv:test" in options["ref"]


def test_in_memory_infinity_is_reported_not_raised_raw(tmp_path):
    """``from_sequences`` is the library entry point: no raw TypeError/ValueError."""
    from parity_plot.data import from_sequences

    with pytest.raises(DataError) as excinfo:
        from_sequences([1.0, float("inf")], [1.0, 2.0])
    assert "infinite" in str(excinfo.value)


def test_in_memory_text_is_reported_not_raised_raw():
    """A caller who breaks the "iterable of numbers" contract still gets DataError.

    Cast because the sequence API is typed for numbers: the point of the test is
    what happens when a caller ignores that, not that the type allows it.
    """
    from parity_plot.data import from_sequences

    with pytest.raises(DataError):
        from_sequences(cast(Any, ["a", "b"]), [1.0, 2.0])
