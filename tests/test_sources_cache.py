"""``open_sources`` is the hottest read in the designer, and it is pure.

The 2026-09-26 scan measured Add File doing ~6 full reads of every open CSV,
and even after coalescing that fan-out, one ref/test change reads twice
(``column_options`` for the option lists, then ``load``). On NFS each of those
is seconds, and a reconnect that reloads the page repeats them all.

A file's contents are a pure function of its bytes, so a ``Sources`` can be
cached against ``(path, mtime_ns, size)``. The stat is one cheap round trip
against the full read it saves, and any rewrite changes mtime or size, so a
stale entry cannot survive a genuine edit.
"""

from __future__ import annotations

from pathlib import Path

from parity_plot import sources as sources_mod
from parity_plot.sources import clear_cache, open_sources


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_a_second_read_of_an_unchanged_file_is_served_from_cache(tmp_path, monkeypatch):
    f = write(tmp_path, "d.csv", "id,v\nA,1\n")
    clear_cache()
    calls: list[Path] = []
    real = sources_mod._read_rows

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(sources_mod, "_read_rows", counting)

    first = open_sources((f,))
    second = open_sources((f,))

    # The read count is the point: the second call did not touch the file.
    assert calls == [f], "the file was read twice"
    # The parsed table is shared (identity of the thin Sources wrapper is not
    # part of the contract -- a fresh one is built per call so ``order`` cannot
    # be mutated by a caller).
    assert second.tables[f] is first.tables[f]


def test_rewriting_a_file_invalidates_its_entry(tmp_path):
    """The whole correctness argument: a write must change mtime or size.

    Without this the designer would keep showing the old columns after the user
    fixed a broken file, which is a much worse bug than a slow read.
    """
    f = write(tmp_path, "d.csv", "id,v\nA,1\n")
    clear_cache()
    assert open_sources((f,)).numeric_refs() == ["d.csv:v"]

    # A rewrite with the same length is the hard case: only mtime distinguishes
    # it, which is exactly why the key includes mtime_ns and not just size.
    write(tmp_path, "d.csv", "id,w\nA,9\n")
    assert open_sources((f,)).numeric_refs() == ["d.csv:w"]


def test_growing_a_file_invalidates_its_entry(tmp_path):
    f = write(tmp_path, "d.csv", "id,v\nA,1\n")
    clear_cache()
    open_sources((f,))
    write(tmp_path, "d.csv", "id,v\nA,1\nB,2\n")
    assert open_sources((f,)).length(f) == 2


def test_a_deleted_file_still_raises(tmp_path):
    """A cache hit must not paper over the file having gone away."""
    f = write(tmp_path, "d.csv", "id,v\nA,1\n")
    clear_cache()
    open_sources((f,))
    f.unlink()
    from parity_plot.data import DataError

    try:
        open_sources((f,))
    except DataError:
        pass
    else:  # pragma: no cover -- the point of the test
        raise AssertionError("a deleted file was served from cache")


def test_the_cache_is_bounded(tmp_path):
    """A designer session opens and closes files; the cache must not grow forever."""
    clear_cache()
    for i in range(sources_mod.CACHE_LIMIT + 3):
        f = write(tmp_path, f"d{i}.csv", "id,v\nA,1\n")
        open_sources((f,))
    assert len(sources_mod._CACHE) <= sources_mod.CACHE_LIMIT
    clear_cache()


def test_clear_cache_empties_it(tmp_path):
    f = write(tmp_path, "d.csv", "id,v\nA,1\n")
    clear_cache()
    open_sources((f,))
    clear_cache()
    assert sources_mod._CACHE == {}


def test_a_file_rewritten_during_its_read_is_not_cached_as_current(
    tmp_path, monkeypatch
):
    """Stamp before reading, or a concurrent rewrite pins the old contents.

    Stamped *after* the read, the old rows were filed under the new file's
    ``(mtime, size)``, and every later lookup served them until the file
    changed yet again. A writer regenerating a CSV while the designer reads it
    is the ordinary way to hit this on a shared filesystem.
    """
    f = write(tmp_path, "d.csv", "id,v\nA,1\n")
    clear_cache()
    real = sources_mod._read_rows
    rewritten = {"done": False}

    def read_then_rewrite(path):
        rows = real(path)
        if not rewritten["done"]:
            rewritten["done"] = True
            path.write_text("id,v\nA,1\nB,2\n", encoding="utf-8")
        return rows

    monkeypatch.setattr(sources_mod, "_read_rows", read_then_rewrite)
    assert open_sources((f,)).tables[f]["id"] == ["A"]  # the racing read
    assert open_sources((f,)).tables[f]["id"] == ["A", "B"]
