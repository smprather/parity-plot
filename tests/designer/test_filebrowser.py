"""Tests for `parity_plot.designer.filebrowser`."""

from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.designer.filebrowser import Entry, Listing, list_dir


def test_subdirs_before_csvs_each_alphabetical(tmp_path: Path) -> None:
    (tmp_path / "zebra.csv").write_text("a,b\n1,2\n")
    (tmp_path / "alpha.csv").write_text("a,b\n1,2\n")
    (tmp_path / "mid.csv").write_text("a,b\n1,2\n")
    (tmp_path / "zdir").mkdir()
    (tmp_path / "adir").mkdir()
    (tmp_path / "mdir").mkdir()

    listing = list_dir(tmp_path)

    names = [e.name for e in listing.entries]
    assert names == ["adir", "mdir", "zdir", "alpha.csv", "mid.csv", "zebra.csv"]


def test_non_csv_excluded_by_default_pattern(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    (tmp_path / "notes.txt").write_text("hello\n")

    listing = list_dir(tmp_path)

    assert [e.name for e in listing.entries] == ["data.csv"]


def test_dotfiles_excluded(tmp_path: Path) -> None:
    (tmp_path / ".hidden.csv").write_text("a,b\n1,2\n")
    (tmp_path / ".gitkeep").write_text("")
    (tmp_path / "visible.csv").write_text("a,b\n1,2\n")
    (tmp_path / ".dotdir").mkdir()

    listing = list_dir(tmp_path)

    assert [e.name for e in listing.entries] == ["visible.csv"]


def test_parent_is_parent_dir(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    listing = list_dir(sub)
    assert listing.parent == tmp_path.resolve()


def test_root_has_no_parent() -> None:
    listing = list_dir("/")
    assert listing.parent is None
    assert listing.cwd == Path("/")


def test_nonexistent_path_raises(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        list_dir(tmp_path / "does-not-exist")


def test_file_path_not_dir_raises(tmp_path: Path) -> None:
    f = tmp_path / "afile.csv"
    f.write_text("a,b\n1,2\n")
    with pytest.raises(NotADirectoryError):
        list_dir(f)


def test_file_size_reported(tmp_path: Path) -> None:
    content = "a,b\n1,2\n3,4\n5,6\n"
    (tmp_path / "sized.csv").write_text(content)

    listing = list_dir(tmp_path)

    [entry] = [e for e in listing.entries if e.name == "sized.csv"]
    assert entry.is_dir is False
    assert entry.size == len(content.encode())


def test_entry_for_dir_has_zero_size(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()

    listing = list_dir(tmp_path)

    [entry] = [e for e in listing.entries if e.name == "subdir"]
    assert entry.is_dir is True
    assert entry.size == 0


def test_resolves_and_normalises(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "x.csv").write_text("a,b\n1,2\n")

    listing = list_dir(tmp_path / "sub" / "..")

    assert listing.cwd == tmp_path.resolve()
    assert listing.parent == tmp_path.resolve().parent
    names = [e.name for e in listing.entries]
    assert names == ["sub", "x.csv"]


def test_custom_pattern(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text("a\n1\n")
    (tmp_path / "b.txt").write_text("x\n")

    listing = list_dir(tmp_path, pattern="*.txt")

    assert [e.name for e in listing.entries] == ["b.txt"]


def test_cwd_is_absolute(tmp_path: Path) -> None:
    listing = list_dir(tmp_path)
    assert listing.cwd.is_absolute()
    assert listing.cwd == tmp_path.resolve()


def test_listing_and_entry_types(tmp_path: Path) -> None:
    (tmp_path / "f.csv").write_text("a\n1\n")
    listing = list_dir(tmp_path)
    assert isinstance(listing, Listing)
    assert all(isinstance(e, Entry) for e in listing.entries)


def test_entries_are_frozen(tmp_path: Path) -> None:
    (tmp_path / "f.csv").write_text("a\n1\n")
    listing = list_dir(tmp_path)
    entry = listing.entries[0]
    with pytest.raises(Exception):
        entry.size = 99  # type: ignore[misc]