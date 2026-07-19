from __future__ import annotations

import pytest

from parity_plot.config import DEFAULT_NA_VALUES, DataConfig
from parity_plot.data import (
    DataError,
    from_sequences,
    load,
    load_pair,
    load_wide,
)

NA = DEFAULT_NA_VALUES


def test_wide_sorts_records_into_paired_and_unpaired(wide_csv):
    data = load_wide(wide_csv, "reference", "measured", "id", na_values=NA)

    assert data.keys == ["A1", "A3"]
    assert data.x == [10.0, 30.0]
    assert data.y == [11.0, 29.0]
    # A2 has a reference but no measurement -> rug along the x axis.
    assert data.missing_y.keys == ["A2"]
    assert data.missing_y.values == [20.0]
    # A4 is the mirror case.
    assert data.missing_x.keys == ["A4"]
    assert data.missing_x.values == [41.0]
    # A5 has nothing to plot on either axis.
    assert data.n_dropped == 1


def test_all_values_includes_unpaired(wide_csv):
    """The axis range is built from this, so a rug mark must not fall outside."""
    data = load_wide(wide_csv, "reference", "measured", "id", na_values=NA)
    assert sorted(data.all_values()) == [10.0, 11.0, 20.0, 29.0, 30.0, 41.0]


@pytest.mark.parametrize("token", ["", "NA", "N/A", "null", "none", "nan", "-", " "])
def test_null_tokens_are_recognised(write_csv, token):
    path = write_csv("t.csv", f"id,a,b\nk1,1.0,{token}\n")
    data = load_wide(path, "a", "b", "id", na_values=NA)
    assert data.n_paired == 0
    assert data.missing_y.values == [1.0]


def test_null_tokens_are_case_insensitive(write_csv):
    path = write_csv("t.csv", "id,a,b\nk1,1.0,NULL\nk2,2.0,NaN\n")
    data = load_wide(path, "a", "b", "id", na_values=NA)
    assert data.n_paired == 0
    assert len(data.missing_y) == 2


def test_non_numeric_value_names_the_file_and_line(write_csv):
    path = write_csv("bad.csv", "id,a,b\nk1,1.0,2.0\nk2,3.0,oops\n")
    with pytest.raises(DataError) as exc:
        load_wide(path, "a", "b", "id", na_values=NA)

    message = str(exc.value)
    assert "bad.csv:3" in message
    assert "'oops'" in message


def test_missing_column_lists_what_is_available(write_csv):
    path = write_csv("t.csv", "id,a,b\nk1,1,2\n")
    with pytest.raises(DataError) as exc:
        load_wide(path, "a", "nope", "id", na_values=NA)
    assert "'nope'" in str(exc.value) or "nope" in str(exc.value)
    assert "['a', 'b', 'id']" in str(exc.value)


def test_key_column_is_optional_in_wide_mode(write_csv):
    path = write_csv("t.csv", "a,b\n1.0,2.0\n3.0,4.0\n")
    data = load_wide(path, "a", "b", key_col=None, na_values=NA)
    assert data.keys == ["1", "2"]


def test_join_treats_an_absent_row_as_null(write_csv):
    x = write_csv("ref.csv", "id,value\nA1,10.0\nA2,20.0\nA3,30.0\n")
    y = write_csv("meas.csv", "id,value\nA1,11.0\nA3,29.0\nA9,99.0\n")

    data = load_pair(x, y, key_col="id", value_col="value", na_values=NA)

    assert data.keys == ["A1", "A3"]
    assert data.missing_y.keys == ["A2"]
    assert data.missing_x.keys == ["A9"]


def test_join_preserves_x_file_order_then_appends_y_only_keys(write_csv):
    x = write_csv("ref.csv", "id,value\nB,2.0\nA,1.0\n")
    y = write_csv("meas.csv", "id,value\nZ,26.0\nA,1.1\nB,2.1\n")

    data = load_pair(x, y, key_col="id", value_col="value", na_values=NA)

    assert data.keys == ["B", "A"]
    assert data.missing_x.keys == ["Z"]


def test_join_falls_back_to_the_axis_named_column(write_csv):
    """A file may name its column `reference` rather than the generic `value`."""
    x = write_csv("ref.csv", "id,reference\nA1,10.0\n")
    y = write_csv("meas.csv", "id,measured\nA1,11.0\n")

    data = load_pair(
        x, y, key_col="id", value_col="value",
        x_col="reference", y_col="measured", na_values=NA,
    )

    assert data.x == [10.0] and data.y == [11.0]
    assert data.x_label == "reference"
    assert data.y_label == "measured"


def test_duplicate_join_key_is_rejected(write_csv):
    x = write_csv("ref.csv", "id,value\nA1,10.0\nA1,12.0\n")
    y = write_csv("meas.csv", "id,value\nA1,11.0\n")

    with pytest.raises(DataError) as exc:
        load_pair(x, y, key_col="id", value_col="value", na_values=NA)
    assert "duplicate key" in str(exc.value)
    assert "ref.csv:3" in str(exc.value)


def test_join_without_a_key_column_is_rejected(write_csv):
    x = write_csv("ref.csv", "id,value\nA1,10.0\n")
    y = write_csv("meas.csv", "id,value\nA1,11.0\n")
    with pytest.raises(DataError, match="key column"):
        load_pair(x, y, key_col=None, value_col="value", na_values=NA)


def test_load_dispatches_on_path_count(wide_csv, write_csv):
    one = load(DataConfig(paths=(wide_csv,), x="reference", y="measured", key="id"))
    assert one.n_paired == 2

    x = write_csv("ref.csv", "id,value\nA1,10.0\n")
    y = write_csv("meas.csv", "id,value\nA1,11.0\n")
    two = load(DataConfig(paths=(x, y), key="id", value="value"))
    assert two.n_paired == 1


def test_load_rejects_zero_and_too_many_paths(wide_csv):
    with pytest.raises(DataError, match="no input paths"):
        load(DataConfig(paths=()))
    with pytest.raises(DataError, match="1 path"):
        load(DataConfig(paths=(wide_csv, wide_csv, wide_csv), key="id"))


def test_from_sequences_treats_none_and_nan_as_null():
    data = from_sequences(
        x=[1.0, 2.0, None, 4.0, None],
        y=[1.1, None, 3.0, float("nan"), None],
    )
    assert data.x == [1.0] and data.y == [1.1]
    assert data.missing_y.values == [2.0, 4.0]
    assert data.missing_x.values == [3.0]
    assert data.n_dropped == 1


def test_from_sequences_checks_lengths():
    with pytest.raises(DataError, match="differ in length"):
        from_sequences(x=[1.0, 2.0], y=[1.0])
    with pytest.raises(DataError, match="keys has length"):
        from_sequences(x=[1.0], y=[1.0], keys=["a", "b"])


def test_empty_file_is_an_error(write_csv):
    path = write_csv("empty.csv", "")
    with pytest.raises(DataError, match="empty"):
        load_wide(path, "a", "b", na_values=NA)


def test_missing_file_is_reported_by_name(tmp_path):
    with pytest.raises(DataError, match="not found"):
        load_wide(tmp_path / "nope.csv", "a", "b", na_values=NA)
