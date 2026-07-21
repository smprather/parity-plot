from __future__ import annotations

from pathlib import Path

from parity_plot.designer.panels.data_panel import column_options


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_ref_and_test_are_numeric_columns_only(tmp_path):
    f = write(tmp_path, "d.csv", "id,voltage,label\nA1,10.0,hi\nA2,20.0,lo\n")
    opts = column_options((f,))
    # id and label are text; only voltage is numeric.
    assert opts["ref"] == ["d.csv:voltage"]
    assert opts["test"] == ["d.csv:voltage"]


def test_group_offers_every_column(tmp_path):
    f = write(tmp_path, "d.csv", "id,voltage,batch\nA1,10.0,x\n")
    opts = column_options((f,))
    assert opts["group"] == ["d.csv:id", "d.csv:voltage", "d.csv:batch"]


def test_join_is_columns_common_to_all_files(tmp_path):
    a = write(tmp_path, "a.csv", "id,extra,v\nA1,1,10\n")
    b = write(tmp_path, "b.csv", "id,v\nA1,11\n")
    opts = column_options((a, b))
    # id and v are in both; extra is only in a.
    assert set(opts["join"]) == {"id", "v"}
    assert "extra" not in opts["join"]


def test_ref_test_span_all_open_files(tmp_path):
    a = write(tmp_path, "a.csv", "id,x\nA1,1.0\n")
    b = write(tmp_path, "b.csv", "id,y\nA1,2.0\n")
    opts = column_options((a, b))
    assert "a.csv:x" in opts["ref"]
    assert "b.csv:y" in opts["ref"]


def test_no_files_offers_nothing():
    assert column_options(()) == {"ref": [], "test": [], "group": [], "join": []}


def test_an_unreadable_file_yields_empty_rather_than_raising(tmp_path):
    assert column_options((tmp_path / "ghost.csv",)) == {
        "ref": [], "test": [], "group": [], "join": [],
    }
