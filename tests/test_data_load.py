"""The multi-file `load` around Sources: join, pair-by-order, group, numeric."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import DataConfig
from parity_plot.data import DataError, load


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# --- single file, pair by order (the old wide mode) ---

def test_one_file_two_columns_pairs_by_order(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test\n10,11\n20,22\n30,29\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test"))
    assert data.x == [10.0, 20.0, 30.0]
    assert data.y == [11.0, 22.0, 29.0]
    assert data.x_label == "reference" and data.y_label == "test"


def test_blank_cell_is_unpaired(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test\n10,11\n20,\n30,29\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test"))
    assert data.n_paired == 2
    assert data.missing_y.values == [20.0]  # ref present, test blank


# --- pair by order, unequal lengths: the tail is unpaired ---

def test_order_tail_is_unpaired(tmp_path):
    a = write(tmp_path, "a.csv", "x\n10\n20\n30\n40\n")
    b = write(tmp_path, "b.csv", "y\n11\n22\n30\n")
    data = load(DataConfig(files=(a, b), ref="a.csv:x", test="b.csv:y"))
    assert data.x == [10.0, 20.0, 30.0]
    assert data.missing_y.values == [40.0]      # ref-only tail -> rug on x-axis
    assert data.n_paired == 3


def test_order_test_longer_leaves_test_only_tail(tmp_path):
    a = write(tmp_path, "a.csv", "x\n10\n20\n")
    b = write(tmp_path, "b.csv", "y\n11\n22\n33\n")
    data = load(DataConfig(files=(a, b), ref="a.csv:x", test="b.csv:y"))
    assert data.missing_x.values == [33.0]      # test-only tail -> rug on y-axis


# --- join ---

def test_join_outer_matches_on_key(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\nA1,10\nA2,20\nA3,30\n")
    b = write(tmp_path, "b.csv", "id,v\nA1,11\nA3,29\nA9,99\n")
    data = load(DataConfig(files=(a, b), ref="a.csv:v", test="b.csv:v", join="id"))
    assert data.keys == ["A1", "A3"]
    assert data.missing_y.keys == ["A2"]        # in a, not b
    assert data.missing_x.keys == ["A9"]        # in b, not a


def test_join_key_may_be_integers(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\n1,10\n2,20\n")
    b = write(tmp_path, "b.csv", "id,v\n2,22\n1,11\n")
    data = load(DataConfig(files=(a, b), ref="a.csv:v", test="b.csv:v", join="id"))
    assert dict(zip(data.keys, data.x)) == {"1": 10.0, "2": 20.0}
    assert dict(zip(data.keys, data.y)) == {"1": 11.0, "2": 22.0}


def test_join_rejects_duplicate_keys(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\nA1,10\nA1,12\n")
    b = write(tmp_path, "b.csv", "id,v\nA1,11\n")
    with pytest.raises(DataError, match="duplicate join key"):
        load(DataConfig(files=(a, b), ref="a.csv:v", test="b.csv:v", join="id"))


def test_join_column_must_exist(tmp_path):
    a = write(tmp_path, "a.csv", "id,v\nA1,10\n")
    b = write(tmp_path, "b.csv", "code,v\nA1,11\n")
    with pytest.raises(DataError, match="join column 'id' not found"):
        load(DataConfig(files=(a, b), ref="a.csv:v", test="b.csv:v", join="id"))


# --- group ---

def test_group_labels_paired_points(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test,batch\n10,11,x\n20,22,y\n30,29,x\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test",
                           group="d.csv:batch"))
    assert data.group == ["x", "y", "x"]


def test_group_is_none_without_a_group_column(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test\n10,11\n")
    assert load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test")).group is None


def test_group_aligns_through_a_join(tmp_path):
    a = write(tmp_path, "a.csv", "id,v,batch\nA1,10,x\nA2,20,y\n")
    b = write(tmp_path, "b.csv", "id,v\nA1,11\nA2,22\n")
    data = load(DataConfig(files=(a, b), ref="a.csv:v", test="b.csv:v", join="id",
                           group="a.csv:batch"))
    assert dict(zip(data.keys, data.group)) == {"A1": "x", "A2": "y"}


def test_a_blank_group_cell_is_none(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test,batch\n10,11,x\n20,22,\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test",
                           group="d.csv:batch"))
    assert data.group == ["x", None]


# --- numeric enforcement on ref/test ---

def test_non_numeric_ref_is_rejected(tmp_path):
    f = write(tmp_path, "d.csv", "label,test\nhi,11\n")
    with pytest.raises(DataError, match="ref column 'label' has non-numeric"):
        load(DataConfig(files=(f,), ref="d.csv:label", test="d.csv:test"))


def test_non_numeric_test_names_file_and_line(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test\n10,11\n20,oops\n")
    with pytest.raises(DataError) as exc:
        load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test"))
    assert "d.csv:3" in str(exc.value)
    assert "oops" in str(exc.value)


# --- guards ---

def test_no_files_is_an_error():
    with pytest.raises(DataError, match="no input files"):
        load(DataConfig())


def test_ref_and_test_are_required(tmp_path):
    f = write(tmp_path, "d.csv", "a,b\n1,2\n")
    with pytest.raises(DataError, match="ref and a test"):
        load(DataConfig(files=(f,)))
