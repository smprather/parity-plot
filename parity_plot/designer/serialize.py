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

from ..config import EXAMPLE_TOML, ParityConfig

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
            if value is None:
                # An unset option is an absent key, not an explicit null.
                if field.name in table:
                    del table[field.name]
                continue
            if _already_equals(current, name, field.name, value):
                # Leave the existing text alone so "10pct" is not rewritten as
                # 0.1 -- same value, gratuitous diff.
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