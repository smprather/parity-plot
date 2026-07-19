"""Tolerance envelopes.

Two specs, each carrying its own units:

- ``abstol`` is in the data's native units. It draws lines parallel to ``y = x``
  at a fixed offset -- the accuracy floor that does not scale with magnitude.
- ``reltol`` is dimensionless -- a true ratio, so ``0.1`` means a tenth. It
  draws a wedge through the origin, since a fixed proportion of a larger
  reading is a larger absolute error. Percent is accepted as an explicit
  suffix (``10pct``), never as a bare number.

Given both, the half-width at any point is the **looser** of the two, so the
envelope runs parallel near the origin (where the absolute floor dominates) and
flares once the relative term overtakes it. That crossover is a real kink, not a
smoothing artefact, and the drawn vertices include it exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def parse_reltol(value: float | str) -> float:
    """Read a relative tolerance, which is a ratio unless marked otherwise.

    ``0.1`` is a tenth. ``10pct`` (or ``10%``) is also a tenth. A bare ``10``
    is taken at face value -- ten times the reading -- rather than silently
    assumed to mean percent, because guessing the unit is exactly the kind of
    error a tolerance spec exists to prevent.
    """
    if isinstance(value, bool):
        raise ValueError(f"expected a relative tolerance, got {value!r}")
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()
    for suffix in ("pct", "%"):
        if text.endswith(suffix):
            number = text[: -len(suffix)].strip()
            try:
                return float(number) / 100.0
            except ValueError:
                raise ValueError(
                    f"could not read {value!r} as a percentage"
                ) from None
    try:
        return float(text)
    except ValueError:
        raise ValueError(
            f"could not read {value!r} as a relative tolerance; give a ratio "
            f"like 0.1, or a percentage like 10pct"
        ) from None


@dataclass(frozen=True)
class Tolerance:
    """A tolerance spec: absolute (in data units), relative (a ratio), or both."""

    abstol: float | None = None
    reltol: float | None = None

    def __bool__(self) -> bool:
        return self.abstol is not None or self.reltol is not None

    @property
    def reltol_pct(self) -> float | None:
        """The relative tolerance expressed as a percentage, for display."""
        return None if self.reltol is None else self.reltol * 100.0

    def half_width(self, x: float) -> float:
        """Permitted deviation from ``y = x`` at ``x``."""
        widths = []
        if self.abstol is not None:
            widths.append(self.abstol)
        if self.reltol is not None:
            widths.append(self.reltol * abs(x))
        return max(widths) if widths else 0.0

    def contains(self, x: float, y: float) -> bool:
        return abs(y - x) <= self.half_width(x)

    @property
    def crossover(self) -> float | None:
        """|x| where the two specs are equal, if they ever are.

        Below it the absolute floor governs, above it the relative term does.
        """
        if self.abstol is None or not self.reltol:
            return None
        return self.abstol / self.reltol

    def label(self) -> str:
        """Human-readable spec, units intact.

        The relative part is shown as a percentage because that is how a
        tolerance is normally quoted, even though it is stored as a ratio.
        """
        rel = None if self.reltol_pct is None else f"{_num(self.reltol_pct)}%"
        if self.abstol is not None and rel is not None:
            return f"±max({_num(self.abstol)}, {rel})"
        if self.abstol is not None:
            return f"±{_num(self.abstol)}"
        if rel is not None:
            return f"±{rel}"
        return ""

    def vertices(self, lo: float, hi: float) -> list[float]:
        """x positions needed to draw the envelope as straight segments.

        Includes every point where the slope changes -- the origin, and the
        crossover on each side -- so the kinks land exactly rather than being
        rounded off by a coarse sample.
        """
        points = {lo, hi}
        for candidate in (0.0, self.crossover, -(self.crossover or 0.0)):
            if candidate is not None and lo < candidate < hi:
                points.add(candidate)
        return sorted(points)

    def envelope(self, lo: float, hi: float) -> tuple[list[float], list[float], list[float]]:
        """``(x, upper, lower)`` polylines spanning ``lo`` to ``hi``."""
        xs = self.vertices(lo, hi)
        upper = [x + self.half_width(x) for x in xs]
        lower = [x - self.half_width(x) for x in xs]
        return xs, upper, lower

    def log_envelope(
        self, lo_exp: float, hi_exp: float, samples: int = 200
    ) -> tuple[list[float], list[float], list[float]]:
        """Envelope sampled in log space, for a logarithmic axis.

        Straight segments in linear space become curves once the axis is
        logarithmic, so this samples densely instead of drawing vertex to
        vertex. Points whose lower edge falls to zero or below are dropped --
        a log axis cannot render them.
        """
        step = (hi_exp - lo_exp) / max(samples - 1, 1)
        xs, upper, lower = [], [], []
        for i in range(samples):
            x = 10 ** (lo_exp + i * step)
            low = x - self.half_width(x)
            if low <= 0:
                continue
            xs.append(x)
            upper.append(x + self.half_width(x))
            lower.append(low)
        return xs, upper, lower


def _num(value: float) -> str:
    """Format a tolerance without trailing noise: 2 not 2.0, 0.5 not 0.50."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}" if not math.isnan(value) else "nan"
