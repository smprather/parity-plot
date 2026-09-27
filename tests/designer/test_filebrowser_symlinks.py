"""The file browser must survive the filesystem misbehaving.

Two defects from the 2026-09-26 scan, both about directories that are not the
plain, readable kind the code assumed:

* **Symlinks were invisible.** ``list_dir`` classified with
  ``follow_symlinks=False``, so a symlink was neither a dir nor a file and was
  silently dropped -- which is the normal shape of a project on NFS where the
  data lives in a shared mount.
* **Only ``NotADirectoryError`` was handled.** A ``PermissionError``, a
  directory removed while it was being listed, or an NFS ``ESTALE`` killed the
  background task; the dialog stayed showing the *previous* listing with no
  message, so it looked frozen rather than failed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.designer.filebrowser import list_dir


def test_a_symlinked_file_is_listed(tmp_path):
    target = tmp_path / "real.csv"
    target.write_text("id,v\nA,1\n", encoding="utf-8")
    link = tmp_path / "link.csv"
    link.symlink_to(target)
    names = [e.name for e in list_dir(tmp_path).entries]
    assert "link.csv" in names


def test_a_symlinked_directory_can_be_navigated_into(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "inner.csv").write_text("id,v\nA,1\n", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real)

    top = [e.name for e in list_dir(tmp_path).entries]
    assert "link" in top
    # And following it works, rather than showing an empty directory.
    inside = list_dir(link)
    assert [e.name for e in inside.entries] == ["inner.csv"]
    assert inside.cwd == Path(link).resolve()


def test_a_dangling_symlink_is_skipped_not_fatal(tmp_path):
    """A link to a file that does not exist: nothing to show, no crash."""
    (tmp_path / "gone.csv").symlink_to(tmp_path / "missing.csv")
    (tmp_path / "real.csv").write_text("id,v\nA,1\n", encoding="utf-8")
    names = [e.name for e in list_dir(tmp_path).entries]
    assert "real.csv" in names


def test_a_symlinked_file_reports_its_real_size(tmp_path):
    target = tmp_path / "real.csv"
    target.write_text("id,v\nA,1\n", encoding="utf-8")
    link = tmp_path / "link.csv"
    link.symlink_to(target)
    entry = next(e for e in list_dir(tmp_path).entries if e.name == "link.csv")
    assert entry.size == target.stat().st_size
    assert entry.is_dir is False


def test_dotfiles_stay_hidden_but_dot_directories_are_navigable(tmp_path):
    (tmp_path / ".hidden.csv").write_text("id,v\nA,1\n", encoding="utf-8")
    (tmp_path / ".data").mkdir()
    (tmp_path / ".data" / "x.csv").write_text("id,v\nA,1\n", encoding="utf-8")
    names = [e.name for e in list_dir(tmp_path).entries]
    assert ".hidden.csv" not in names
    assert ".data" in names


def test_the_csv_pattern_still_filters_symlinked_files(tmp_path):
    """Following a symlink must not widen the pattern to every file type."""
    (tmp_path / "notes.txt").symlink_to(tmp_path / "other.txt")
    (tmp_path / "other.txt").write_text("hello", encoding="utf-8")
    names = [e.name for e in list_dir(tmp_path).entries]
    assert names == []


def test_a_missing_directory_raises_not_a_directory_error(tmp_path):
    with pytest.raises(NotADirectoryError):
        list_dir(tmp_path / "nope")


def test_a_file_passed_as_a_directory_raises_not_a_directory_error(tmp_path):
    f = tmp_path / "d.csv"
    f.write_text("id,v\nA,1\n", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        list_dir(f)
