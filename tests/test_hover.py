"""Hover-text column selection: the auto set, pinned refs, alignment, labels."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import DataConfig
from parity_plot.data import (
    DataError,
    hover_candidates,
    hover_labels_for,
    load,
)
from parity_plot.sources import open_sources


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# --- the auto candidate set ---


def test_auto_lists_every_column_except_ref_test_and_join(tmp_path):
    a = _write(tmp_path, "ref.csv", "id,value,package,vendor\nA,10,SMD,Acme\n")
    b = _write(tmp_path, "meas.csv", "id,value,package\nA,11,SMD\n")
    src = open_sources((a, b))
    cands = hover_candidates(src, "ref.csv:value", "meas.csv:value", "id")
    # ref's file first (header order), then test's file; ref/test/join excluded
    # per file -- package survives in both because it is not an axis column.
    assert cands == [
        "ref.csv:package",
        "ref.csv:vendor",
        "meas.csv:package",
    ]


def test_auto_wide_mode_excludes_both_axis_columns(tmp_path):
    f = _write(tmp_path, "d.csv", "reference,test,package,vendor\n10,11,SMD,Acme\n")
    src = open_sources((f,))
    cands = hover_candidates(src, "d.csv:reference", "d.csv:test", None)
    assert cands == ["d.csv:package", "d.csv:vendor"]


def test_axis_exclusion_is_per_file_not_global(tmp_path):
    """A column sharing the *other* file's axis name is a different column.

    ref is ref.csv:v and test is meas.csv:w, so ref.csv's own `w` is neither
    axis -- it is some third measurement that happens to share a name, and
    excluding it globally would hide data the hover should show.
    """
    a = _write(tmp_path, "ref.csv", "id,v,w\nA,10,99\n")
    b = _write(tmp_path, "meas.csv", "id,w\nA,11\n")
    src = open_sources((a, b))
    cands = hover_candidates(src, "ref.csv:v", "meas.csv:w", "id")
    assert cands == ["ref.csv:w"]


def test_auto_does_not_offer_a_third_open_file(tmp_path):
    a = _write(tmp_path, "ref.csv", "id,value,package\nA,10,SMD\n")
    b = _write(tmp_path, "meas.csv", "id,value\nA,11\n")
    extra = _write(tmp_path, "extra.csv", "id,note\nA,hello\n")
    src = open_sources((a, b, extra))
    cands = hover_candidates(src, "ref.csv:value", "meas.csv:value", "id")
    assert all(not c.startswith("extra.csv:") for c in cands)
    assert cands == ["ref.csv:package"]


# --- pinned subset honoured in order ---


def test_pinned_subset_is_honoured_in_given_order(tmp_path):
    f = _write(
        tmp_path,
        "d.csv",
        "reference,test,package,vendor,temperature\n10,11,SMD,Acme,25\n",
    )
    data = load(
        DataConfig(
            files=(f,),
            ref="d.csv:reference",
            test="d.csv:test",
            hover_columns=("d.csv:vendor", "d.csv:package"),
        )
    )
    assert data.hover_labels == ("vendor", "package")
    assert data.hover_values == [("Acme", "SMD")]


# --- suppress ---


def test_empty_tuple_suppresses_hover(tmp_path):
    f = _write(tmp_path, "d.csv", "reference,test,package\n10,11,SMD\n")
    data = load(
        DataConfig(
            files=(f,),
            ref="d.csv:reference",
            test="d.csv:test",
            hover_columns=(),
        )
    )
    assert data.hover_values is None
    assert data.hover_labels == ()


def test_auto_on_a_file_with_no_extra_columns_yields_nothing(tmp_path):
    f = _write(tmp_path, "d.csv", "reference,test\n10,11\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test"))
    assert data.hover_values is None
    assert data.hover_labels == ()


# --- alignment ---


def test_values_align_under_a_join(tmp_path):
    a = _write(tmp_path, "ref.csv", "id,value,package\nA,10,SMD\nB,20,DIP\n")
    # Shuffle the test file's row order so a positional bug cannot pass.
    b = _write(tmp_path, "meas.csv", "id,value\nB,22\nA,11\n")
    data = load(
        DataConfig(
            files=(a, b),
            ref="ref.csv:value",
            test="meas.csv:value",
            join="id",
            hover_columns=("ref.csv:package",),
        )
    )
    assert dict(zip(data.keys, data.hover_values)) == {"A": ("SMD",), "B": ("DIP",)}


def test_values_align_when_pairing_by_order(tmp_path):
    f = _write(
        tmp_path, "d.csv", "reference,test,package\n10,11,SMD\n20,22,DIP\n30,29,QFN\n"
    )
    data = load(
        DataConfig(
            files=(f,),
            ref="d.csv:reference",
            test="d.csv:test",
            hover_columns=("d.csv:package",),
        )
    )
    assert data.hover_values == [("SMD",), ("DIP",), ("QFN",)]


# --- null rendering ---


def test_blank_and_na_cells_render_as_em_dash(tmp_path):
    f = _write(tmp_path, "d.csv", "reference,test,note\n10,11,SMD\n20,22,\n30,29,NA\n")
    data = load(
        DataConfig(
            files=(f,),
            ref="d.csv:reference",
            test="d.csv:test",
            hover_columns=("d.csv:note",),
        )
    )
    assert data.hover_values == [("SMD",), ("—",), ("—",)]


# --- validation: refs outside the candidate rules ---


def test_ref_naming_a_third_open_file_raises(tmp_path):
    a = _write(tmp_path, "ref.csv", "id,value,package\nA,10,SMD\n")
    b = _write(tmp_path, "meas.csv", "id,value\nA,11\n")
    extra = _write(tmp_path, "extra.csv", "id,note\nA,hello\n")
    with pytest.raises(DataError) as exc:
        load(
            DataConfig(
                files=(a, b, extra),
                ref="ref.csv:value",
                test="meas.csv:value",
                join="id",
                hover_columns=("extra.csv:note",),
            )
        )
    assert "extra.csv" in str(exc.value)
    assert "neither ref nor test" in str(exc.value)


def test_ref_naming_the_ref_column_raises(tmp_path):
    f = _write(tmp_path, "d.csv", "reference,test,package\n10,11,SMD\n")
    with pytest.raises(DataError, match="already shown as an axis row"):
        load(
            DataConfig(
                files=(f,),
                ref="d.csv:reference",
                test="d.csv:test",
                hover_columns=("d.csv:reference",),
            )
        )


def test_ref_naming_the_join_column_raises(tmp_path):
    a = _write(tmp_path, "ref.csv", "id,value,package\nA,10,SMD\n")
    b = _write(tmp_path, "meas.csv", "id,value\nA,11\n")
    with pytest.raises(DataError, match="key line"):
        load(
            DataConfig(
                files=(a, b),
                ref="ref.csv:value",
                test="meas.csv:value",
                join="id",
                hover_columns=("ref.csv:id",),
            )
        )


# --- hover_labels_for disambiguation ---


def test_labels_are_bare_when_unambiguous():
    assert hover_labels_for(("ref.csv:package", "ref.csv:vendor")) == (
        "package",
        "vendor",
    )


def test_labels_prefix_file_when_a_bare_name_repeats():
    labels = hover_labels_for(("ref.csv:temperature", "meas.csv:temperature"))
    assert labels == ("ref.csv:temperature", "meas.csv:temperature")


def test_a_full_path_ref_labels_with_path_name(tmp_path):
    full = str(tmp_path / "reference.csv")
    labels = hover_labels_for((f"{full}:temperature", "measured.csv:temperature"))
    assert labels == ("reference.csv:temperature", "measured.csv:temperature")
