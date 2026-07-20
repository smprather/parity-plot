"""Pure list operations for the designer's tolerance panel.

The UI is thin: it renders the list and forwards edits here. Everything that
decides *what the list becomes* lives in this module, so it can be tested
without a browser -- the same split as the rest of the designer.

Every operation returns a new tuple; nothing mutates in place, matching the
frozen config the list ends up in.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from ..tolerances import (
    NamedTolerance,
    PARITY_NAME,
    default_name,
    with_parity,
)


def add(tolerances: Sequence[NamedTolerance]) -> tuple[NamedTolerance, ...]:
    """Append a fresh pass/fail tolerance with an auto name and a default bound.

    A new entry needs *some* bound to be valid, so it starts at reltol 10% --
    a visible band the user then edits, rather than an error.
    """
    name = default_name([t.name for t in tolerances])
    fresh = NamedTolerance(name=name, reltol=0.10)
    return (*tolerances, fresh)


def delete(
    tolerances: Sequence[NamedTolerance], name: str
) -> tuple[NamedTolerance, ...]:
    """Remove the named tolerance. The parity entry cannot be deleted."""
    if name == PARITY_NAME:
        # The reference line is built in; refuse rather than silently no-op so
        # the UI can hide the control instead of pretending it worked.
        raise ValueError("the parity line cannot be deleted")
    return tuple(t for t in tolerances if t.name != name)


def update(
    tolerances: Sequence[NamedTolerance], name: str, edited: NamedTolerance
) -> tuple[NamedTolerance, ...]:
    """Replace the entry named ``name`` with ``edited``, keeping its position.

    Editing by position rather than by the edited object's name means a rename
    still lands in the right slot.
    """
    return tuple(edited if t.name == name else t for t in tolerances)


def set_enabled(
    tolerances: Sequence[NamedTolerance], name: str, enabled: bool
) -> tuple[NamedTolerance, ...]:
    """Toggle one entry's enabled flag. Works for parity too -- disabling it is
    how the reference line is hidden."""
    return tuple(
        replace(t, enabled=enabled) if t.name == name else t for t in tolerances
    )


def rename_is_free(
    tolerances: Sequence[NamedTolerance], current: str, proposed: str
) -> bool:
    """Whether ``proposed`` is available -- unused, or the entry's own name.

    A duplicate name would make a failure list ambiguous, so the editor blocks
    it before it reaches config validation.
    """
    if proposed == current:
        return True
    return proposed not in {t.name for t in tolerances}


def normalise(tolerances: Sequence[NamedTolerance]) -> tuple[NamedTolerance, ...]:
    """Guarantee the parity entry leads the list after any operation."""
    return with_parity(tuple(tolerances))
