"""CSV loading, outer joining, and null classification.

Everything downstream consumes a single :class:`ParityData` struct, so neither
input mode (wide file vs. two joined files) leaks past this module.

A record that exists in one dataset but not the other cannot be a point on the
plot -- it has only one coordinate. Rather than dropping it, such a record is
kept in ``missing_x`` or ``missing_y`` so the plot can show it as a rug mark on
the axis of the value that *is* known.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Sequence

from .config import DataConfig


class DataError(ValueError):
    """Raised for unreadable, malformed, or ambiguous input data."""


@dataclass(frozen=True)
class Unpaired:
    """Records with a value in one dataset and nothing in the other."""

    keys: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.values)


@dataclass(frozen=True)
class ParityData:
    keys: list[str] = field(default_factory=list)
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    missing_y: Unpaired = field(default_factory=Unpaired)
    missing_x: Unpaired = field(default_factory=Unpaired)
    n_dropped: int = 0
    x_label: str = "x"
    y_label: str = "y"
    # Per-paired-point group label, or None when no group column was chosen.
    # Aligned to `keys`/`x`/`y`; an entry may be None if that point's group cell
    # was blank. Drives colour/symbol-by-group in Phase 2.
    group: list[str | None] | None = None
    # Per-paired-point numeric value for the colorscale channel, aligned to
    # keys/x/y; None when no colour column (or every value blank). color_label
    # is the column's display name, used as the colorbar title.
    color_values: list[float | None] | None = None
    color_label: str = ""
    # Extra hover rows, aligned to keys/x/y. hover_labels is the display text
    # per column; hover_values is one tuple per paired point (row-major, which
    # is the shape Plotly's customdata wants). None when no hover columns.
    hover_labels: tuple[str, ...] = ()
    hover_values: list[tuple[str, ...]] | None = None

    @property
    def n_paired(self) -> int:
        return len(self.x)

    @property
    def n_unpaired(self) -> int:
        return len(self.missing_x) + len(self.missing_y)

    def all_values(self) -> list[float]:
        """Every finite value, paired or not -- the basis for the axis range.

        Unpaired values are included so a rug mark can never fall outside the
        plotted range.
        """
        return [*self.x, *self.y, *self.missing_y.values, *self.missing_x.values]

    def select_paired(self, indices: Iterable[int]) -> ParityData:
        """Keep paired rows at ``indices``, preserving every aligned channel."""
        kept = list(indices)
        return replace(
            self,
            keys=[self.keys[i] for i in kept],
            x=[self.x[i] for i in kept],
            y=[self.y[i] for i in kept],
            group=[self.group[i] for i in kept] if self.group is not None else None,
            color_values=(
                [self.color_values[i] for i in kept]
                if self.color_values is not None
                else None
            ),
            hover_values=(
                [self.hover_values[i] for i in kept]
                if self.hover_values is not None
                else None
            ),
        )


def load(cfg: DataConfig) -> ParityData:
    """Load per the config: N files, ref/test as file:column, join or order.

    The two plotted series are ``ref`` and ``test``, each a ``file:column`` into
    the open set. A ``join`` column aligns rows across files by key; without one,
    rows pair by position and the longer column's tail is left unpaired. An
    optional ``group`` column labels each paired point.

    Both former modes are special cases: one file with two columns and no join is
    the old wide mode; two files with a join is the old pair mode. There is no
    dispatch on file count.
    """
    from .sources import open_sources  # lazy: sources imports helpers from here

    if not cfg.files:
        raise DataError("no input files; pass a CSV path or set data.files")
    if not cfg.ref or not cfg.test:
        raise DataError("both a ref and a test column are required (file:column)")

    src = open_sources(cfg.files, cfg.na_values)
    na = _na_set(cfg.na_values)

    ref_col = src.resolve(cfg.ref)
    test_col = src.resolve(cfg.test)
    _require_numeric(ref_col, na, "ref")
    _require_numeric(test_col, na, "test")

    # Both axis files must carry the join column. `_index_by_key` checks this
    # too, but it runs after the per-point lookups are built, and an auto-hover
    # column drawn from the same file would raise first -- reporting a missing
    # join key in the language of the hover channel. Check it here so the
    # canonical message wins no matter which channel trips over it.
    if cfg.join:
        for col in (ref_col, test_col):
            if cfg.join not in src.tables[col.file]:
                raise DataError(
                    f"{col.file}: join column {cfg.join!r} not found; "
                    f"available: {sorted(src.tables[col.file])}"
                )

    # Group is a bare, file-independent column name: it labels the paired entity,
    # not a per-file measurement. It may live in one file or several; when in
    # several, the value must agree for each paired point -- a part cannot be
    # both a "diode" and a "mosfet". A file that lacks it simply does not vote.
    group_lookup = _group_lookup(src, cfg.group, cfg.join, na) if cfg.group else None

    color_col = src.resolve(cfg.color_column) if cfg.color_column else None
    if color_col is not None:
        _require_numeric(color_col, na, "color_column")
    color_lookup = _color_lookup(src, color_col, cfg.join, na) if color_col else None

    # Absent hover_columns means "auto": every candidate column. Resolved here
    # rather than stored, so the set follows a ref/test change instead of going
    # stale.
    if cfg.hover_columns is None:
        hover_refs: tuple[str, ...] = tuple(
            hover_candidates(src, cfg.ref, cfg.test, cfg.join)
        )
    else:
        hover_refs = tuple(cfg.hover_columns)
        _validate_hover(src, hover_refs, ref_col, test_col, cfg.join)
    hover_lookup = _hover_lookup(src, hover_refs, cfg.join, na) if hover_refs else None

    builder = _Builder(
        x_label=ref_col.name,
        y_label=test_col.name,
        color_label=color_col.name if color_col else "",
        hover_labels=hover_labels_for(hover_refs),
    )
    if cfg.join:
        _load_joined(
            builder,
            src,
            ref_col,
            test_col,
            group_lookup,
            color_lookup,
            hover_lookup,
            cfg.join,
            na,
        )
    else:
        _load_by_order(
            builder,
            ref_col,
            test_col,
            group_lookup,
            color_lookup,
            hover_lookup,
            na,
        )
    return builder.build()


def _group_lookup(src, groups: tuple[str, ...], join: str | None, na: frozenset[str]):
    """A callable giving a paired point's composite group label.

    Each column is resolved file-independently (present in one file or several,
    values must agree across files via ``_agree``). The point's label joins the
    per-column values with ", "; a blank column contributes "(none)", and a
    point whose columns are all blank has no group (``None``).
    """
    per_column = [_one_group_lookup(src, col, join, na) for col in groups]

    def composite(point):
        parts = [fn(point) for fn in per_column]
        if all(p is None for p in parts):
            return None
        return ", ".join("(none)" if p is None else p for p in parts)

    return composite


def _color_lookup(src, color_col, join: str | None, na: frozenset[str]):
    """A callable giving a paired point's numeric colour value.

    Pinned to the colour column's own file (no cross-file agreement): the same
    column can legitimately differ between the reference and test files.
    """
    if join:
        table = src.tables[color_col.file]
        if join not in table:
            raise DataError(
                f"{color_col.file}: colour column's file lacks join column "
                f"{join!r}; cannot align colour values"
            )
        indexed = _values_by_key(color_col.file, table, color_col.name, join)
        mapping = {key: value for key, (_, value) in indexed.items()}

        def lookup(key):
            return _color_value(mapping.get(key), na)

        return lookup

    values = color_col.values

    def lookup_by_index(index):
        return _color_value(values[index] if index < len(values) else None, na)

    return lookup_by_index


def _color_value(raw: str | None, na: frozenset[str]) -> float | None:
    """Parse a colour cell to a float, or None if blank/NA.

    The whole column has already passed ``_require_numeric``, so ``float`` here
    cannot raise on a non-null cell.
    """
    if raw is None:
        return None
    text = raw.strip()
    if text.lower() in na:
        return None
    return float(text)


def hover_candidates(src, ref: str, test: str, join: str | None) -> list[str]:
    """The ``file:column`` refs offered as hover rows, in a stable order.

    Only the files backing ref and test: a third open file has no per-point
    alignment without a join into it. The ref column, the test column and the
    join column are left out because the hover already shows all three -- as
    the x row, the y row and the bold key line -- and a config able to
    duplicate them can only look like a bug.
    """
    ref_col = src.resolve(ref)
    test_col = src.resolve(test)
    # Ref's file first, then test's file only if it is a different file. Order
    # within a file is its header order, so the picker reads top-to-bottom.
    files: list[Path] = [ref_col.file]
    if test_col.file != ref_col.file:
        files.append(test_col.file)

    # Exclusions are per file, not global: a column that merely shares a name
    # with the *other* file's axis column is a different measurement and stays
    # offered. The join, being one key across all files, is excluded everywhere.
    excluded: dict[Path, set[str]] = {path: set() for path in files}
    excluded[ref_col.file].add(ref_col.name)
    excluded[test_col.file].add(test_col.name)
    if join is not None:
        for names in excluded.values():
            names.add(join)

    out: list[str] = []
    for path in files:
        for column in src.tables[path]:
            if column in excluded[path]:
                continue
            out.append(f"{path.name}:{column}")
    return out


def hover_labels_for(refs: Sequence[str]) -> tuple[str, ...]:
    """Display text per hover column: the shortest unambiguous name.

    A bare column name reads best, but two files can both carry `temperature`
    and two identical hover rows are worse than a long label -- so a name
    appearing more than once in this selection is prefixed with its file.
    """
    bare = [ref.rpartition(":")[2] for ref in refs]
    seen: dict[str, int] = {}
    for name in bare:
        seen[name] = seen.get(name, 0) + 1
    labels: list[str] = []
    for ref, name in zip(refs, bare):
        if seen[name] > 1:
            file_part = ref.rpartition(":")[0]
            labels.append(f"{Path(file_part).name}:{name}")
        else:
            labels.append(name)
    return tuple(labels)


def _hover_text(raw: str | None, na: frozenset[str]) -> str:
    """One hover cell as raw text -- no coercion, no formatting.

    Showing the file's own text is lossless and cannot misreport a number.
    Configurable float formatting needs a per-column schema and is deliberately
    deferred (see the spec's Future work). A null renders as an em dash so
    "present but blank" is legible rather than looking like a dropped row.
    """
    if raw is None:
        return "—"
    text = raw.strip()
    if text.lower() in na:
        return "—"
    return text


def _hover_lookup(src, refs: Sequence[str], join: str | None, na: frozenset[str]):
    """A callable giving a paired point's hover cells, one per ref.

    Mirrors :func:`_color_lookup`: a dict keyed by the join value, or an index
    lookup when pairing by order. Pinned per file -- no ``_agree`` voting, since
    a pinned ref has nothing to reconcile.
    """
    cols = [src.resolve(r) for r in refs]

    if join:
        mappings: list[dict[str, str]] = []
        for col in cols:
            table = src.tables[col.file]
            if join not in table:
                raise DataError(
                    f"{col.file}: hover column's file lacks join column "
                    f"{join!r}; cannot align hover values"
                )
            mappings.append(dict(zip(table[join], col.values)))

        def lookup_by_key(key):
            return tuple(_hover_text(m.get(key), na) for m in mappings)

        return lookup_by_key

    def lookup_by_index(index: int):
        cells: list[str] = []
        for col in cols:
            raw = col.values[index] if index < len(col.values) else None
            cells.append(_hover_text(raw, na))
        return tuple(cells)

    return lookup_by_index


def _validate_hover(
    src, refs: Sequence[str], ref_col, test_col, join: str | None
) -> None:
    """Reject a pinned hover ref the candidate rules do not allow.

    Silently rendering nothing for a ref the user typed is exactly the failure
    this project rejects for unknown TOML keys.
    """
    axis_files = {ref_col.file, test_col.file}
    # dict, not a set: ref and test may share one file, and naming it twice in
    # the message reads like a bug in the tool rather than one in the config.
    names = sorted({f.name: None for f in (ref_col.file, test_col.file)})
    axes = {(ref_col.file, ref_col.name), (test_col.file, test_col.name)}
    for r in refs:
        col = src.resolve(r)
        if col.file not in axis_files:
            raise DataError(
                f"hover column {r!r} is in {col.file.name}, which backs neither "
                f"ref nor test; hover columns come from the ref/test files ({names})"
            )
        if (col.file, col.name) in axes:
            raise DataError(
                f"hover column {r!r} is already shown as an axis row in the hover"
            )
        if join is not None and col.name == join:
            raise DataError(
                f"hover column {r!r} is already the hover's key line (the join column)"
            )


def _one_group_lookup(src, group: str, join: str | None, na: frozenset[str]):
    """The single-column resolver (the old ``_group_lookup`` body)."""
    files = src.files_with_column(group)
    if not files:
        raise DataError(
            f"group column {group!r} not found in any open file; "
            f"available: {sorted(set(src.columns()))}"
        )

    if join:
        for file in files:
            if join not in src.tables[file]:
                raise DataError(
                    f"{file}: group column {group!r}'s file lacks join column "
                    f"{join!r}; cannot align group values"
                )
        keyed = {
            file: {
                key: value
                for key, (_, value) in _values_by_key(
                    file, src.tables[file], group, join
                ).items()
            }
            for file in files
        }

        def lookup(key: str, _keyed=keyed, _group=group):
            return _agree(
                {f: d[key] for f, d in _keyed.items() if key in d}, key, _group, na
            )

        return lookup

    columns = {f: src.tables[f][group] for f in files}

    def lookup_by_index(index: int, _columns=columns, _group=group):
        present = {f: v[index] for f, v in _columns.items() if index < len(v)}
        return _agree(present, str(index), _group, na)

    return lookup_by_index


def _agree(values: dict, point: str, column: str, na: frozenset[str]) -> str | None:
    """The one group value the files agree on, or None if none, or raise."""
    cleaned = {f: v.strip() for f, v in values.items() if v.strip().lower() not in na}
    distinct = set(cleaned.values())
    if len(distinct) > 1:
        detail = ", ".join(f"{f.name}={v!r}" for f, v in sorted(cleaned.items()))
        raise DataError(
            f"{point}: group column {column!r} disagrees across files ({detail})"
        )
    return next(iter(distinct)) if distinct else None


def _require_numeric(col, na: frozenset[str], role: str) -> None:
    """ref and test are the axes -- every non-NA cell must be a number."""
    for index, raw in enumerate(col.values):
        text = (raw or "").strip()
        if text.lower() in na:
            continue
        try:
            float(text)
        except ValueError:
            raise DataError(
                f"{col.file}:{index + 2}: {role} column {col.name!r} has "
                f"non-numeric value {text!r}"
            ) from None


def _load_by_order(
    builder: "_Builder",
    ref_col,
    test_col,
    group_lookup,
    color_lookup,
    hover_lookup,
    na,
) -> None:
    """Pair rows by position; the longer column's tail becomes unpaired."""
    n = max(len(ref_col.values), len(test_col.values))
    for i in range(n):
        rv = ref_col.values[i] if i < len(ref_col.values) else None
        tv = test_col.values[i] if i < len(test_col.values) else None
        builder.add(
            str(i),
            _parse(rv, na, ref_col.file, i + 2, ref_col.name)
            if rv is not None
            else None,
            _parse(tv, na, test_col.file, i + 2, test_col.name)
            if tv is not None
            else None,
            group=group_lookup(i) if group_lookup else None,
            color=color_lookup(i) if color_lookup else None,
            hover=hover_lookup(i) if hover_lookup else None,
        )


def _load_joined(
    builder: "_Builder",
    src,
    ref_col,
    test_col,
    group_lookup,
    color_lookup,
    hover_lookup,
    join,
    na,
) -> None:
    """Outer-join ref and test files on ``join``; a key on one side is unpaired."""
    ref_by = _index_by_key(src, ref_col, join)
    test_by = _index_by_key(src, test_col, join)

    # ref-file order first, then keys only in the test file -- deterministic and
    # mirroring how the data was laid out.
    ordered = list(ref_by) + [k for k in test_by if k not in ref_by]
    for key in ordered:
        rline, rraw = ref_by.get(key, (0, None))
        tline, traw = test_by.get(key, (0, None))
        builder.add(
            key,
            _parse(rraw, na, ref_col.file, rline, ref_col.name)
            if rraw is not None
            else None,
            _parse(traw, na, test_col.file, tline, test_col.name)
            if traw is not None
            else None,
            group=group_lookup(key) if group_lookup else None,
            color=color_lookup(key) if color_lookup else None,
            hover=hover_lookup(key) if hover_lookup else None,
        )


def _index_by_key(src, col, join: str) -> dict[str, tuple[int, str]]:
    """{join-key: (line, raw value)} for one column, keyed on the join column.

    The key file must contain the join column, and its keys must be unique -- a
    duplicate would make the join ambiguous.
    """
    table = src.tables[col.file]
    if join not in table:
        raise DataError(
            f"{col.file}: join column {join!r} not found; available: {sorted(table)}"
        )
    return _values_by_key(col.file, table, col.name, join)


def _values_by_key(
    path: Path,
    table: dict[str, list[str]],
    value_column: str,
    join: str,
) -> dict[str, tuple[int, str]]:
    """Index one column by a unique join key."""
    keys = table[join]
    out: dict[str, tuple[int, str]] = {}
    for index, (key, value) in enumerate(zip(keys, table[value_column])):
        key = (key or "").strip()
        if key in out:
            raise DataError(
                f"{path}:{index + 2}: duplicate join key {key!r}; the join "
                f"would be ambiguous"
            )
        out[key] = (index + 2, value)
    return out


def from_sequences(
    x: Iterable[float | None],
    y: Iterable[float | None],
    keys: Sequence[str] | None = None,
    group: Sequence[str | None] | None = None,
    x_label: str = "x",
    y_label: str = "y",
) -> ParityData:
    """Build from in-memory sequences, treating ``None``/NaN as null.

    This is the entry point for the Python API when the caller already has
    arrays in hand (lists, pandas Series, numpy arrays -- anything iterable).
    """
    xs, ys = list(x), list(y)
    if len(xs) != len(ys):
        raise DataError(f"x and y differ in length: {len(xs)} vs {len(ys)}")
    if keys is not None and len(keys) != len(xs):
        raise DataError(f"keys has length {len(keys)}, expected {len(xs)}")
    groups = list(group) if group is not None else None
    if groups is not None and len(groups) != len(xs):
        raise DataError(f"group has length {len(groups)}, expected {len(xs)}")

    builder = _Builder(x_label=x_label, y_label=y_label)
    for i, (xv, yv) in enumerate(zip(xs, ys)):
        key = keys[i] if keys is not None else str(i)
        gv = groups[i] if groups is not None else None
        builder.add(str(key), _clean(xv), _clean(yv), group=gv)
    return builder.build()


class _Builder:
    """Accumulates records and sorts them into paired / unpaired / dropped."""

    def __init__(
        self,
        x_label: str,
        y_label: str,
        color_label: str = "",
        hover_labels: tuple[str, ...] = (),
    ) -> None:
        self.keys: list[str] = []
        self.x: list[float] = []
        self.y: list[float] = []
        self.groups: list[str | None] = []
        self.colors: list[float | None] = []
        self.hovers: list[tuple[str, ...]] = []
        self.missing_y_keys: list[str] = []
        self.missing_y_vals: list[float] = []
        self.missing_x_keys: list[str] = []
        self.missing_x_vals: list[float] = []
        self.n_dropped = 0
        self.x_label = x_label
        self.y_label = y_label
        self.color_label = color_label
        self.hover_labels = hover_labels

    def add(
        self,
        key: str,
        xv: float | None,
        yv: float | None,
        group: str | None = None,
        color: float | None = None,
        hover: tuple[str, ...] | None = None,
    ) -> None:
        if xv is not None and yv is not None:
            self.keys.append(key)
            self.x.append(xv)
            self.y.append(yv)
            # Group is a property of a paired point only; unpaired records have
            # no place in the encoded scatter, so their group is not tracked.
            self.groups.append(group)
            self.colors.append(color)
            # A hover row is a paired-point concern, exactly as group and colour
            # already are.
            self.hovers.append(hover or ())
        elif xv is not None:
            self.missing_y_keys.append(key)
            self.missing_y_vals.append(xv)
        elif yv is not None:
            self.missing_x_keys.append(key)
            self.missing_x_vals.append(yv)
        else:
            self.n_dropped += 1

    def build(self) -> ParityData:
        # None unless a group column actually supplied a label somewhere.
        group = self.groups if any(g is not None for g in self.groups) else None
        color_values = self.colors if any(c is not None for c in self.colors) else None
        return ParityData(
            keys=self.keys,
            x=self.x,
            y=self.y,
            missing_y=Unpaired(self.missing_y_keys, self.missing_y_vals),
            missing_x=Unpaired(self.missing_x_keys, self.missing_x_vals),
            n_dropped=self.n_dropped,
            x_label=self.x_label,
            y_label=self.y_label,
            group=group,
            color_values=color_values,
            color_label=self.color_label,
            hover_labels=self.hover_labels,
            hover_values=self.hovers if self.hover_labels else None,
        )


def _read_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    """Return ``(line_number, row)`` pairs; line 1 is the header."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                return []
            return [(i, row) for i, row in enumerate(reader, start=2)]
    except FileNotFoundError:
        raise DataError(f"input file not found: {path}") from None
    except OSError as exc:
        raise DataError(f"could not read {path}: {exc}") from None


def _require_columns(path: Path, header: Iterable[str], needed: Iterable[str]) -> None:
    available = set(header)
    missing = sorted(set(needed) - available)
    if missing:
        raise DataError(
            f"{path}: missing column(s) {missing}; available columns are "
            f"{sorted(available)}"
        )


def _na_set(na_values: Sequence[str]) -> frozenset[str]:
    return frozenset(v.strip().lower() for v in na_values)


def _parse(
    raw: str | None, na: frozenset[str], path: Path, line: int, column: str
) -> float | None:
    """Parse one cell to a float, or ``None`` if it is null.

    A value that is neither null nor numeric is an error rather than a silent
    null: quietly coercing it would corrupt every statistic downstream.
    """
    if raw is None:
        return None
    text = raw.strip()
    if text.lower() in na:
        return None
    try:
        value = float(text)
    except ValueError:
        raise DataError(
            f"{path}:{line}: column {column!r} has non-numeric value {text!r}"
        ) from None
    if math.isnan(value):
        return None
    if math.isinf(value):
        raise DataError(f"{path}:{line}: column {column!r} is infinite")
    return value


def _clean(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if math.isnan(number):
        return None
    if math.isinf(number):
        raise DataError(f"in-memory sequence value {value!r} is infinite")
    return number
