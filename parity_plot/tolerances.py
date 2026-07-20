# parity_plot/tolerances.py
"""Named tolerances.

A plot may carry several specifications at once -- a customer limit, a tighter
internal target, a reference band nobody is graded against. Each is a
`NamedTolerance`: a `Tolerance` (which owns all the geometry) plus the identity
and presentation needed to tell several of them apart.

`name` and `label` are deliberately different things. The name is an
identifier: it appears in configs, in CLI flags, and in the comma-separated
failure list shown per record, so it must be stable and space-free. The label
is display text for the legend, may contain spaces, and may follow the spec
automatically -- nothing keys off it, so it is free to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .tolerance import Tolerance

KINDS = ("pass", "info")
STYLES = ("lines", "shaded")
AUTO_LABEL = "auto"

# Pass/fail limits are a warning; informational bands are not.
DEFAULT_COLORS = {"pass": "red", "info": "yellow"}


class ToleranceError(ValueError):
    """Raised for a tolerance that cannot mean anything."""


@dataclass(frozen=True)
class NamedTolerance:
    """One specification, named and drawable."""

    name: str
    abstol: float | None = None
    reltol: float | None = None
    kind: str = "pass"
    color: str | None = None
    style: str = "lines"
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ToleranceError("a tolerance needs a name")
        if any(character.isspace() for character in self.name):
            raise ToleranceError(
                f"tolerance name {self.name!r} may not contain whitespace; it is an "
                f"identifier and appears in comma-separated failure lists"
            )
        if self.abstol is None and self.reltol is None:
            raise ToleranceError(
                f"tolerance {self.name!r} needs abstol or reltol (or both)"
            )
        for field_name in ("abstol", "reltol"):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise ToleranceError(
                    f"tolerance {self.name!r}: {field_name} must be positive, got {value}"
                )
        if self.kind not in KINDS:
            raise ToleranceError(
                f"tolerance {self.name!r}: kind {self.kind!r} is not one of {list(KINDS)}"
            )
        if self.style not in STYLES:
            raise ToleranceError(
                f"tolerance {self.name!r}: style {self.style!r} is not one of {list(STYLES)}"
            )

    @property
    def tolerance(self) -> Tolerance:
        """The geometry. Every calculation lives there, not here."""
        return Tolerance(abstol=self.abstol, reltol=self.reltol)

    @property
    def display_label(self) -> str:
        """Legend text: the manual label, or one derived from the spec."""
        if self.label and self.label != AUTO_LABEL:
            return self.label
        return self.tolerance.label()

    @property
    def is_pass_fail(self) -> bool:
        return self.kind == "pass"

    @property
    def color_token(self) -> str:
        """The colour token, defaulted by kind. Resolved to a shade by the theme."""
        return self.color or DEFAULT_COLORS[self.kind]

    def contains(self, x: float, y: float) -> bool:
        return self.tolerance.contains(x, y)


def default_name(existing: Sequence[str]) -> str:
    """The next free ``toleranceN``, skipping names already taken."""
    taken = set(existing)
    index = 1
    while f"tolerance{index}" in taken:
        index += 1
    return f"tolerance{index}"


def require_unique_names(tolerances: Sequence[NamedTolerance]) -> None:
    """Reject repeated names.

    A record's verdict is a list of failed names; two tolerances sharing one
    would make that list impossible to read back.
    """
    seen: set[str] = set()
    duplicates: list[str] = []
    for tol in tolerances:
        if tol.name in seen and tol.name not in duplicates:
            duplicates.append(tol.name)
        seen.add(tol.name)
    if duplicates:
        raise ToleranceError(f"duplicate tolerance name(s): {', '.join(duplicates)}")


def pass_fail(tolerances: Sequence[NamedTolerance]) -> tuple[NamedTolerance, ...]:
    """Only the entries a point can actually fail."""
    return tuple(tol for tol in tolerances if tol.is_pass_fail)


def failures(
    tolerances: Sequence[NamedTolerance], x: float, y: float
) -> tuple[str, ...]:
    """Names of every pass/fail tolerance this point breaks, in declared order.

    Informational entries are never judged -- they are drawn for reference, and
    reporting a point as failing one would invent a criterion.
    """
    return tuple(tol.name for tol in pass_fail(tolerances) if not tol.contains(x, y))


def verdict_text(failed: Sequence[str]) -> str:
    """How a verdict reads in the table and the hover."""
    return ", ".join(failed) if failed else "pass"