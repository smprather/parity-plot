"""Writing a ParityConfig back to TOML.

`tomllib` is read-only, so saving needs its own writer. The naive approach --
regenerate the file from the config -- destroys every comment in it, which is
unacceptable for a file meant to be hand-edited and committed. `tomlkit` parses
into a document that remembers its own formatting, so values can be updated in
place and everything around them survives.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import AoT

from ..config import EXAMPLE_TOML, ParityConfig
from ..tolerance import parse_reltol
from ..tolerances import PARITY_NAME, NamedTolerance, parity

SECTIONS = ("data", "plot", "stats", "output")


def config_to_toml(config: ParityConfig, existing: str | None = None) -> str:
    """Render ``config`` as TOML, updating ``existing`` in place if given.

    Without ``existing``, a fresh document is generated from the documented
    example so a first save still arrives with its comments.
    """
    doc = tomlkit.parse(existing if existing is not None else EXAMPLE_TOML)
    current = _safe_load(doc)

    for name in SECTIONS:
        section = getattr(config, name)
        table = doc.get(name)
        if table is None:
            table = tomlkit.table()
            doc[name] = table

        for field in fields(section):
            value = getattr(section, field.name)
            if field.name == "tolerances" and name == "plot":
                _write_tolerances(table, value, current)
                continue
            if value is None:
                # An unset option is an absent key, not an explicit null.
                if field.name in table:
                    del table[field.name]
                continue
            if field.name in table and _already_equals(current, name, field.name, value):
                # Leave the existing text alone so "10pct" is not rewritten as
                # 0.1 -- same value, gratuitous diff.
                #
                # The `in table` guard matters: a parsed config fills absent
                # keys with their defaults, so without it a key missing from
                # the file compares equal to the default and is never written.
                # Saving would then silently fail to record that setting.
                continue
            table[field.name] = _to_toml_value(value)

    return tomlkit.dumps(doc)


def _safe_load(doc: Any) -> ParityConfig | None:
    """The existing document as a config, or None if it does not parse.

    A malformed file on disk must not stop a save; it just means nothing can be
    treated as already-equal.
    """
    try:
        return ParityConfig.from_dict(_plain(doc))
    except Exception:
        return None


def _already_equals(current: ParityConfig | None, section: str, key: str, value: Any) -> bool:
    if current is None:
        return False
    return getattr(getattr(current, section), key) == value


def _plain(value: Any) -> Any:
    """Strip tomlkit's wrapper types so ParityConfig sees plain Python."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, str):
        return str(value)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return value


def _to_toml_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [_to_toml_value(v) for v in value]
    return value


def _write_tolerances(
    plot_table: Any,
    tolerances: tuple[NamedTolerance, ...],
    current: ParityConfig | None,
) -> None:
    """Replace ``plot.tolerances`` with an array-of-tables for the list.

    Only non-default fields are written per entry (plus ``name`` always), so a
    plain one-bound tolerance stays terse. The unmodified built-in parity entry
    is omitted entirely -- ``with_parity`` re-adds it on load -- but a
    customised parity (disabled, recoloured, ...) is written so the
    customisation survives the round trip.

    An entry whose parsed value already equals the new one keeps its existing
    raw table, so a hand-typed ``reltol = "10pct"`` is not rewritten as ``0.1``.
    """
    to_write = [t for t in tolerances if not _is_default_parity(t)]

    existing = plot_table.get("tolerances")
    by_name: dict[str, Any] = {}
    if isinstance(existing, AoT):
        for raw in existing:
            name = str(raw.get("name", ""))
            if name:
                by_name[name] = raw

    if not to_write:
        if "tolerances" in plot_table:
            del plot_table["tolerances"]
        return

    aot = tomlkit.aot()
    for tol in to_write:
        raw = by_name.get(tol.name)
        if raw is not None and _raw_matches(raw, tol):
            # Reuse the existing table verbatim to preserve spelling.
            aot.append(raw)
        else:
            aot.append(_fresh_tolerance_table(tol))
    plot_table["tolerances"] = aot


def _is_default_parity(tol: NamedTolerance) -> bool:
    return tol.name == PARITY_NAME and tol == parity()


def _raw_matches(raw: Any, tol: NamedTolerance) -> bool:
    """Whether the existing raw table parses back into ``tol``.

    The raw table may carry only the non-default keys (that is what a previous
    save wrote), so missing keys are filled from the ``NamedTolerance``
    dataclass defaults before comparison -- the same fill the loader does.
    ``reltol`` accepts either a ratio or a ``"10pct"`` string, parsed the same
    way ``config._coerce_tolerances`` does.
    """
    fields_dict: dict[str, Any] = {"name": tol.name}
    for f in fields(NamedTolerance):
        if f.name == "name":
            continue
        fields_dict[f.name] = f.default
    for key in raw:
        value = raw[key]
        if key == "reltol" and value is not None:
            try:
                fields_dict[key] = parse_reltol(str(value))
            except ValueError:
                return False
        else:
            fields_dict[key] = _plain(value)
    if fields_dict.get("builtin") and "kind" not in raw:
        # A builtin entry is forced to "info"; mirror the loader's injection so
        # a bare ``builtin = true`` table compares equal to the default parity.
        fields_dict["kind"] = "info"
    try:
        parsed = NamedTolerance(**fields_dict)
    except Exception:
        return False
    return parsed == tol


def _fresh_tolerance_table(tol: NamedTolerance) -> Any:
    """A new ``[[plot.tolerances]]`` table carrying only non-default fields.

    Comparison is against the ``NamedTolerance`` dataclass defaults, because
    that is what the loader fills for absent keys -- so a field that differs
    from the dataclass default but happens to match ``parity()`` (e.g. the
    parity line's ``color = "green"``) must still be written, or the reloaded
    entry would silently lose it. ``builtin`` is always written for a parity
    entry: the loader rejects the reserved name ``parity`` unless that flag is
    present, so omitting it would make the saved file unloadable.
    """
    table = tomlkit.table()
    table["name"] = tol.name
    is_parity = tol.name == PARITY_NAME
    for f in fields(NamedTolerance):
        if f.name == "name":
            continue
        value = getattr(tol, f.name)
        if f.name == "builtin" and is_parity:
            table[f.name] = _to_toml_value(value)
            continue
        if value != f.default:
            table[f.name] = _to_toml_value(value)
    return table