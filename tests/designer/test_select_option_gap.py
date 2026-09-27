"""A select must never be built with a value its own options do not contain.

``ui.select(options, value=...)`` raises ``ValueError: Invalid value`` at
construction, and NiceGUI turns that into an HTTP 500 for the whole page. The
2026-09-26 scan listed four ways the designer's data panel could hit it, and
all four are the same defect: the option list is derived from the files, while
the value comes from the config, and nothing guarantees the value is *in* the
derived list.

Each case is a real config state, not a hypothetical:

* a file is briefly unreadable, so ``column_options`` degrades to all-empty;
* ref/test were written in the path form (``/dir/w.csv:a``), which ``load``
  accepts and the options never offer;
* two open files share a basename, so ``w.csv:x`` is ambiguous and only the
  full path resolves;
* the ref column is all-NA, so it is not "numeric" by the options' definition
  even though ``load`` treats it as a valid axis.
"""

from __future__ import annotations

from pathlib import Path

from parity_plot.config import DataConfig
from parity_plot.designer.panels.data_panel import (
    _NONE,
    column_options,
    current_only_options,
)


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_current_values_are_offered_even_with_no_files():
    """A config whose files are not readable must still render.

    This is the NFS case: ``column_options`` swallows the read error and returns
    all-empty, and a select built from those with a live value raises.
    """
    data = DataConfig(
        files=(Path("/gone/w.csv"),),
        ref="w.csv:reference",
        test="w.csv:test",
    )
    options = current_only_options(data)
    assert "w.csv:reference" in options["ref"]
    assert "w.csv:test" in options["test"]


def test_a_path_form_ref_is_offered_verbatim(tmp_path):
    """``load`` resolves the full path; the options must offer the same spelling."""
    f = write(tmp_path, "w.csv", "id,reference,test\nA,1,2\n")
    data = DataConfig(files=(f,), ref=f"{f}:reference", test=f"{f}:test")
    options = current_only_options(data)
    assert f"{f}:reference" in options["ref"]
    assert f"{f}:test" in options["test"]


def test_the_none_sentinel_is_never_offered_as_a_column(tmp_path):
    """An unset join is the sentinel, not a column name."""
    f = write(tmp_path, "w.csv", "id,reference,test\nA,1,2\n")
    data = DataConfig(files=(f,), ref="w.csv:reference")
    options = current_only_options(data)
    assert _NONE not in options["join"]
    assert _NONE not in options["ref"]
    assert _NONE not in options["test"]


def test_pinned_group_and_colour_values_are_offered(tmp_path):
    """A composite group and a colour column are values too, not just axes."""
    f = write(tmp_path, "w.csv", "id,reference,test,batch,temp\nA,1,2,x,20\n")
    data = DataConfig(
        files=(f,),
        ref="w.csv:reference",
        test="w.csv:test",
        group=("batch", "vendor"),
        color_column="w.csv:temp",
        hover_columns=("w.csv:batch",),
    )
    options = current_only_options(data)
    assert "vendor" in options["group"]
    assert "w.csv:temp" in options["color_column"]
    assert "w.csv:batch" in options["hover_columns"]


def test_an_all_na_axis_column_is_still_offered(tmp_path):
    """``_is_numeric`` needs one number; ``_require_numeric`` does not.

    So an all-NA ref is a perfectly loadable axis that the numeric-only
    derivation will not offer -- and a select cannot hold an unlisted value.
    """
    f = write(tmp_path, "w.csv", "id,reference,test\nA,1,2\nB,NA,3\nC,,4\n")
    options = column_options((f,), ref="w.csv:reference", test="w.csv:test")
    assert "w.csv:reference" in options["ref"]
    assert "w.csv:test" in options["test"]


def test_a_current_value_the_derivation_drops_is_put_back(tmp_path):
    """``other`` is all-NA, so the honest numeric list excludes it.

    Offering it anyway is the point: it is the configured ref, and dropping it
    from the list would 500 the page instead of showing the bad config.
    """
    f = write(tmp_path, "w.csv", "id,reference,test,other\nA,1,2,NA\nB,NA,3,NA\n")
    assert "w.csv:other" not in column_options((f,))["ref"]
    options = column_options((f,), ref="w.csv:other", test="w.csv:test")
    assert "w.csv:other" in options["ref"]


def test_ambiguous_basenames_are_offered_by_full_path(tmp_path):
    """Two open files called ``d.csv``: only the full path resolves.

    ``Sources._match`` raises "ambiguous file" for a bare ``d.csv:col`` and
    accepts the full path, so offering the bare form would hand the user a
    selection that always errors.
    """
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    a = write(tmp_path, "one/d.csv", "id,reference\nA,1\n")
    b = write(tmp_path, "two/d.csv", "id,test\nA,2\n")

    options = column_options((a, b))
    assert f"{a}:reference" in options["ref"]
    assert f"{b}:test" in options["ref"]
    # And nothing offers the ambiguous bare form.
    assert "d.csv:reference" not in options["ref"]
    assert "d.csv:test" not in options["ref"]


def test_an_unambiguous_file_keeps_its_short_name(tmp_path):
    """Full paths everywhere would be unreadable; only repeats need them."""
    a = write(tmp_path, "a.csv", "id,reference\nA,1\n")
    b = write(tmp_path, "b.csv", "id,test\nA,2\n")
    options = column_options((a, b))
    assert "a.csv:reference" in options["ref"]
    assert "b.csv:test" in options["ref"]


def test_hover_candidates_are_also_unambiguous(tmp_path):
    """The same bare-basename trap, in the hover picker."""
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    a = write(tmp_path, "one/d.csv", "id,reference,package\nA,1,SMD\n")
    b = write(tmp_path, "two/d.csv", "id,test\nA,2\n")

    options = column_options((a, b), ref=f"{a}:reference", test=f"{b}:test")
    assert f"{a}:package" in options["hover_columns"]
    assert "d.csv:package" not in options["hover_columns"]
