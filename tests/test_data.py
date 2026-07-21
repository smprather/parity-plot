from __future__ import annotations

import pytest

from parity_plot.config import DEFAULT_NA_VALUES, DataConfig
from parity_plot.data import DataError, from_sequences, load

NA = DEFAULT_NA_VALUES


def _wide(write_csv, name="wide.csv", ref="reference", test="test"):
    return write_csv(name, f"id,{ref},{test}\nA1,10.0,11.0\nA2,20.0,\nA3,30.0,29.0\n")


def test_wide_sorts_records_into_paired_and_unpaired(wide_csv):
    data = load(DataConfig(files=(wide_csv,), ref="wide.csv:reference",
                          test="wide.csv:test"))

    assert data.keys == ["0", "2"]
    assert data.x == [10.0, 30.0]
    assert data.y == [11.0, 29.0]
    # A2 has a reference but no test -> rug along the x axis.
    assert data.missing_y.values == [20.0]
    # (the wide_csv fixture also has A4/A5 below, see below)


def test_wide_fixture_unpaired_and_dropped(wide_csv):
    data = load(DataConfig(files=(wide_csv,), ref="wide.csv:reference",
                          test="wide.csv:test"))
    assert data.n_paired == 2          # A1, A3
    assert data.missing_y.values == [20.0]      # A2 (ref, no test)
    assert data.missing_x.values == [41.0]     # A4 (test, no ref)
    assert data.n_dropped == 1                  # A5 (neither)


def test_all_values_includes_unpaired(wide_csv):
    """The axis range is built from this, so a rug mark must not fall outside."""
    data = load(DataConfig(files=(wide_csv,), ref="wide.csv:reference",
                          test="wide.csv:test"))
    assert sorted(data.all_values()) == [10.0, 11.0, 20.0, 29.0, 30.0, 41.0]


@pytest.mark.parametrize("token", ["", "NA", "N/A", "null", "none", "nan", "-", " "])
def test_null_tokens_are_recognised(write_csv, token):
    path = write_csv("t.csv", f"id,a,b\nk1,1.0,{token}\n")
    data = load(DataConfig(files=(path,), ref="t.csv:a", test="t.csv:b"))
    assert data.n_paired == 0
    assert data.missing_y.values == [1.0]


def test_null_tokens_are_case_insensitive(write_csv):
    path = write_csv("t.csv", "id,a,b\nk1,1.0,NULL\nk2,2.0,NaN\n")
    data = load(DataConfig(files=(path,), ref="t.csv:a", test="t.csv:b"))
    assert data.n_paired == 0
    assert len(data.missing_y) == 2


def test_non_numeric_value_names_the_file_and_line(write_csv):
    path = write_csv("bad.csv", "id,a,b\nk1,1.0,2.0\nk2,3.0,oops\n")
    with pytest.raises(DataError) as exc:
        load(DataConfig(files=(path,), ref="bad.csv:a", test="bad.csv:b"))

    message = str(exc.value)
    assert "bad.csv:3" in message
    assert "'oops'" in message


def test_missing_column_lists_what_is_available(write_csv):
    path = write_csv("t.csv", "id,a,b\nk1,1,2\n")
    with pytest.raises(DataError) as exc:
        load(DataConfig(files=(path,), ref="t.csv:a", test="t.csv:nope"))
    assert "'nope'" in str(exc.value) or "nope" in str(exc.value)
    assert "['a', 'b', 'id']" in str(exc.value)


def test_pair_by_order_without_a_join_column(write_csv):
    path = write_csv("t.csv", "a,b\n1.0,2.0\n3.0,4.0\n")
    data = load(DataConfig(files=(path,), ref="t.csv:a", test="t.csv:b"))
    assert data.keys == ["0", "1"]
    assert data.x == [1.0, 3.0] and data.y == [2.0, 4.0]


def test_join_treats_an_absent_row_as_null(write_csv):
    x = write_csv("ref.csv", "id,value\nA1,10.0\nA2,20.0\nA3,30.0\n")
    y = write_csv("meas.csv", "id,value\nA1,11.0\nA3,29.0\nA9,99.0\n")

    data = load(DataConfig(files=(x, y), ref="ref.csv:value",
                          test="meas.csv:value", join="id"))

    assert data.keys == ["A1", "A3"]
    assert data.missing_y.keys == ["A2"]
    assert data.missing_x.keys == ["A9"]


def test_join_preserves_x_file_order_then_appends_y_only_keys(write_csv):
    x = write_csv("ref.csv", "id,value\nB,2.0\nA,1.0\n")
    y = write_csv("meas.csv", "id,value\nZ,26.0\nA,1.1\nB,2.1\n")

    data = load(DataConfig(files=(x, y), ref="ref.csv:value",
                          test="meas.csv:value", join="id"))

    assert data.keys == ["B", "A"]
    assert data.missing_x.keys == ["Z"]


def test_duplicate_join_key_is_rejected(write_csv):
    x = write_csv("ref.csv", "id,value\nA1,10.0\nA1,12.0\n")
    y = write_csv("meas.csv", "id,value\nA1,11.0\n")

    with pytest.raises(DataError) as exc:
        load(DataConfig(files=(x, y), ref="ref.csv:value",
                        test="meas.csv:value", join="id"))
    assert "duplicate join key" in str(exc.value)
    assert "ref.csv:3" in str(exc.value)


def test_join_column_must_exist(write_csv):
    x = write_csv("ref.csv", "id,value\nA1,10.0\n")
    y = write_csv("meas.csv", "code,value\nA1,11.0\n")
    with pytest.raises(DataError, match="join column 'id' not found"):
        load(DataConfig(files=(x, y), ref="ref.csv:value",
                        test="meas.csv:value", join="id"))


def test_from_sequences_treats_none_and_nan_as_null():
    data = from_sequences(
        [1.0, 2.0, None, 4.0, None],
        [1.1, None, 3.0, float("nan"), None],
    )
    assert data.x == [1.0] and data.y == [1.1]
    assert data.missing_y.values == [2.0, 4.0]
    assert data.missing_x.values == [3.0]
    assert data.n_dropped == 1


def test_from_sequences_checks_lengths():
    with pytest.raises(DataError, match="differ in length"):
        from_sequences([1.0, 2.0], [1.0])
    with pytest.raises(DataError, match="keys has length"):
        from_sequences([1.0], [1.0], keys=["a", "b"])


def test_empty_file_is_an_error(write_csv):
    path = write_csv("empty.csv", "")
    with pytest.raises(DataError, match="empty"):
        load(DataConfig(files=(path,), ref="empty.csv:a", test="empty.csv:b"))


def test_missing_file_is_reported_by_name(tmp_path):
    with pytest.raises(DataError, match="not found"):
        open_and_load = load(DataConfig(
            files=(tmp_path / "nope.csv",), ref="nope.csv:a", test="nope.csv:b"))


def test_no_files_is_an_error():
    with pytest.raises(DataError, match="no input files"):
        load(DataConfig())


def test_ref_and_test_are_required(write_csv):
    f = write_csv("d.csv", "a,b\n1,2\n")
    with pytest.raises(DataError, match="ref and a test"):
        load(DataConfig(files=(f,)))