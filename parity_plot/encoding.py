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

# A stable symbol cycle used when ``symbol_by = "group"``. Plotly symbol names.
_SYMBOL_CYCLE: tuple[str, ...] = (
    "circle",
    "x",
    "diamond",
    "square",
    "triangle-up",
    "cross",
    "star",
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
    """

    color_by: str = "single"
    symbol_by: str = "single"
    color: str = "blue"
    symbol: str = "circle"

    def __post_init__(self) -> None:
        if self.color_by not in CHANNELS:
            raise EncodingError(
                f"color_by must be one of {CHANNELS!r}, got {self.color_by!r}"
            )
        if self.symbol_by not in CHANNELS:
            raise EncodingError(
                f"symbol_by must be one of {CHANNELS!r}, got {self.symbol_by!r}"
            )


@dataclass(frozen=True)
class TraceSpec:
    """One trace's point indices and the keys ``plot.py`` will resolve."""

    name: str
    indices: list[int]
    color_key: str
    symbol_key: str


def _group_first_seen_order(groups: Sequence[str | None]) -> list[str | None]:
    """Distinct group values in first-seen order (None included)."""
    order: list[str | None] = []
    seen: set[str | None] = set()
    for g in groups:
        if g not in seen:
            seen.add(g)
            order.append(g)
    return order


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
    group_order: Sequence[str | None],
) -> str:
    """Symbol key for one point."""
    if enc.symbol_by == "single":
        return enc.symbol
    if enc.symbol_by == "pass-fail":
        return "circle" if verdict else "x"
    # group: cycle by the group's first-seen index
    if not has_group_column:
        return _SYMBOL_CYCLE[0]
    idx = group_order.index(group) if group in group_order else 0
    return _SYMBOL_CYCLE[idx % len(_SYMBOL_CYCLE)]


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
    group_order: list[str | None] = (
        _group_first_seen_order(groups) if has_group_column else []
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
            i,
            verdict,
            group,
            enc,
            has_group_column=has_group_column,
            group_order=group_order,
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