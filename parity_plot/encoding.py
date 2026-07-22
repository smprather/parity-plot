"""Pure marker-encoding logic: partition paired points into traces by colour/symbol keys.

This module is deliberately free of Plotly, themes, and hex colours. It works in
*keys*: a colour key is a theme token ("blue"), "pass"/"fail", or a group value;
a symbol key is a Plotly symbol name ("circle", "x", ...). ``plot.py`` resolves
keys to real colours/symbols via the theme, which is what lets one encoding
render correctly under both dark and light themes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

__all__ = [
    "CHANNELS",
    "Encoding",
    "EncodingError",
    "TraceSpec",
    "partition",
    "color_key_of",
    "symbol_key_of",
]

CHANNELS: tuple[str, str, str] = ("single", "pass-fail", "group")

# The default symbol cycle used when ``symbol_by = "group"`` and no explicit
# ``symbol_sequence`` is given. Ordered for maximum shape contrast early, so the
# first few groups are the easiest to tell apart. Plotly symbol names.
DEFAULT_SYMBOLS: tuple[str, ...] = (
    "circle",
    "square",
    "diamond",
    "triangle-up",
    "cross",
    "x",
    "star",
    "triangle-down",
    "pentagon",
    "hexagon",
    "star-triangle-up",
    "hexagram",
    "bowtie",
    "hourglass",
    "star-square",
    "star-diamond",
)

# The symbols offered in the designer's pickers. The same list backs both the
# single-symbol dropdown and the ``symbol_sequence`` multi-select. A TOML author
# is not limited to this shortlist -- any Plotly base symbol (below), with an
# optional ``-open`` / ``-dot`` / ``-open-dot`` variant suffix, is accepted.
SYMBOL_CATALOG: tuple[str, ...] = DEFAULT_SYMBOLS

# Every Plotly marker base-symbol name. A configured symbol is validated against
# this set (after stripping a variant suffix) so a typo is caught with a named
# error rather than rendering an invisible marker. This mirrors the colour-token
# check in ``themes`` and the project's "unknown key is an error" stance.
_BASE_SYMBOLS: frozenset[str] = frozenset({
    "circle", "square", "diamond", "cross", "x",
    "triangle-up", "triangle-down", "triangle-left", "triangle-right",
    "triangle-ne", "triangle-se", "triangle-sw", "triangle-nw",
    "pentagon", "hexagon", "hexagon2", "octagon",
    "star", "hexagram",
    "star-triangle-up", "star-triangle-down", "star-square", "star-diamond",
    "diamond-tall", "diamond-wide", "hourglass", "bowtie",
    "circle-cross", "circle-x", "square-cross", "square-x",
    "diamond-cross", "diamond-x", "cross-thin", "x-thin",
    "asterisk", "hash",
    "y-up", "y-down", "y-left", "y-right",
    "line-ew", "line-ns", "line-ne", "line-nw",
    "arrow-up", "arrow-down", "arrow-left", "arrow-right",
    "arrow-bar-up", "arrow-bar-down", "arrow-bar-left", "arrow-bar-right",
    "arrow", "arrow-wide",
})
_SYMBOL_VARIANTS: tuple[str, ...] = ("-open-dot", "-open", "-dot")


def _validate_symbol(symbol: str, *, where: str) -> None:
    """Raise :class:`EncodingError` if ``symbol`` is not a known Plotly symbol.

    A variant suffix (``-open``/``-dot``/``-open-dot``) is stripped before the
    base name is checked, so ``"circle-open-dot"`` validates via ``"circle"``.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise EncodingError(f"{where} must be a non-empty symbol name, got {symbol!r}")
    base = symbol
    for suffix in _SYMBOL_VARIANTS:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if base not in _BASE_SYMBOLS:
        raise EncodingError(
            f"{where}: unknown symbol {symbol!r}; base name {base!r} is not a "
            f"Plotly marker symbol"
        )

# Bucket keys for the group channel.
_NO_COLUMN_BUCKET = "ungrouped"
_NONE_VALUE_BUCKET = "(none)"


class EncodingError(ValueError):
    """Raised for an unknown ``color_by``/``symbol_by`` channel."""


@dataclass(frozen=True)
class Encoding:
    """How marker colour and symbol are driven from the data.

    Each channel is one of :data:`CHANNELS`:

    - ``"single"``    — every point shares ``color`` / ``symbol``.
    - ``"pass-fail"`` — the overall verdict: pass → green-ish + circle,
      fail → red-ish + x (the colour/symbol *keys* emitted here are
      ``"pass"``/``"fail"`` and ``"circle"``/``"x"``; the theme resolves them).
    - ``"group"``     — the point's group value: a qualitative palette / symbol
      cycle assigned to distinct values in first-seen order.

    ``symbol_sequence`` overrides the default symbol cycle for ``symbol_by =
    "group"`` — the distinct groups (first-seen order) are assigned symbols from
    it, wrapping if there are more groups than symbols. Empty means the built-in
    :data:`DEFAULT_SYMBOLS`. It is stored as a tuple so the frozen dataclass stays
    hashable even when a list arrives from TOML.
    """

    color_by: str = "single"
    symbol_by: str = "single"
    color: str = "blue"
    symbol: str = "circle"
    symbol_sequence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.color_by not in CHANNELS:
            raise EncodingError(
                f"color_by must be one of {CHANNELS!r}, got {self.color_by!r}"
            )
        if self.symbol_by not in CHANNELS:
            raise EncodingError(
                f"symbol_by must be one of {CHANNELS!r}, got {self.symbol_by!r}"
            )
        _validate_symbol(self.symbol, where="symbol")
        # TOML (and the designer's multi-select) hand over a list; normalise to a
        # tuple so the frozen dataclass is hashable and compares by value.
        object.__setattr__(self, "symbol_sequence", tuple(self.symbol_sequence))
        for s in self.symbol_sequence:
            _validate_symbol(s, where="symbol_sequence entry")


@dataclass(frozen=True)
class TraceSpec:
    """One trace's point indices and the keys ``plot.py`` will resolve."""

    name: str
    indices: list[int]
    color_key: str
    symbol_key: str


def color_key_of(
    i: int,
    verdict: bool,
    group: str | None,
    enc: Encoding,
    *,
    has_group_column: bool,
) -> str:
    """Colour key for one point.

    ``group`` is the per-point group value (``None`` means an actual missing
    value); ``has_group_column`` distinguishes "no group column at all" from
    "a column whose value is None here".
    """
    if enc.color_by == "single":
        return enc.color
    if enc.color_by == "pass-fail":
        return "pass" if verdict else "fail"
    # group
    if not has_group_column:
        return _NO_COLUMN_BUCKET
    if group is None:
        return _NONE_VALUE_BUCKET
    return str(group)


def symbol_key_of(
    i: int,
    verdict: bool,
    group: str | None,
    enc: Encoding,
    *,
    has_group_column: bool,
) -> str:
    """Symbol key for one point.

    For ``single``/``pass-fail`` the key is already a Plotly symbol name. For
    ``group`` the key is the *group value* (mirroring :func:`color_key_of`), and
    ``plot.py`` resolves it to an actual symbol through the sequence — so the
    trace is named by the group, not by the glyph, and the group→symbol mapping
    is configurable via ``symbol_sequence``.
    """
    if enc.symbol_by == "single":
        return enc.symbol
    if enc.symbol_by == "pass-fail":
        return "circle" if verdict else "x"
    # group: same bucketing as the colour channel.
    if not has_group_column:
        return _NO_COLUMN_BUCKET
    if group is None:
        return _NONE_VALUE_BUCKET
    return str(group)


def _channel_label(
    channel: str, key: str, *, verdict: bool, group: str | None
) -> str | None:
    """The *meaningful* dimension label for a channel, for trace naming.

    ``pass-fail`` labels by verdict ("pass"/"fail") even on the symbol channel,
    where the key is a symbol name ("circle"/"x") — the name should read as the
    verdict, not the glyph. ``single`` contributes nothing.
    """
    if channel == "single":
        return None
    if channel == "pass-fail":
        return "pass" if verdict else "fail"
    return key  # group: the bucket key already carries the meaning


def _trace_name(
    enc: Encoding,
    color_key: str,
    symbol_key: str,
    *,
    verdict: bool,
    group: str | None,
) -> str:
    color_label = _channel_label(
        enc.color_by, color_key, verdict=verdict, group=group
    )
    symbol_label = _channel_label(
        enc.symbol_by, symbol_key, verdict=verdict, group=group
    )
    if color_label is not None and symbol_label is not None:
        return f"{color_label} · {symbol_label}"
    if color_label is not None:
        return color_label
    if symbol_label is not None:
        return symbol_label
    return "paired"


def partition(
    n: int,
    verdicts: Sequence[bool],
    groups: Sequence[str | None] | None,
    enc: Encoding,
) -> list[TraceSpec]:
    """Split ``n`` paired points into one :class:`TraceSpec` per distinct
    ``(colour-key, symbol-key)`` pair, in first-seen order.

    Every point index appears in exactly one trace. ``verdicts`` is the
    precomputed per-point verdict (``True`` = pass); ``groups`` is the per-point
    group value, or ``None`` when there is no group column at all.
    """
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")
    if len(verdicts) != n:
        raise ValueError(
            f"verdicts length {len(verdicts)} does not match n={n}"
        )
    has_group_column = groups is not None
    if has_group_column and len(groups) != n:  # type: ignore[arg-type]
        raise ValueError(
            f"groups length {len(groups)} does not match n={n}"  # type: ignore[arg-type]
        )

    # (color_key, symbol_key) -> (indices, insertion_order, verdict, group)
    buckets: dict[
        tuple[str, str], tuple[list[int], int, bool, str | None]
    ] = {}
    next_order = 0
    for i in range(n):
        verdict = bool(verdicts[i])
        group = groups[i] if has_group_column else None
        ck = color_key_of(
            i, verdict, group, enc, has_group_column=has_group_column
        )
        sk = symbol_key_of(
            i, verdict, group, enc, has_group_column=has_group_column
        )
        key = (ck, sk)
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = ([i], next_order, verdict, group)
            next_order += 1
        else:
            bucket[0].append(i)

    ordered = sorted(buckets.items(), key=lambda kv: kv[1][1])
    return [
        TraceSpec(
            name=_trace_name(
                enc, ck, sk, verdict=verdict, group=group
            ),
            indices=indices,
            color_key=ck,
            symbol_key=sk,
        )
        for (ck, sk), (indices, _order, verdict, group) in ordered
    ]