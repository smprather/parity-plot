# parity_plot/designer/filters.py
"""Narrowing what the plot and the table show.

Filters are exploration state. They never reach the saved config: a TOML that
encoded "only the failures" would render a different plot from the one the CLI
produces, and the designer's whole claim is that those two agree.

Each switch is independent and answers one question, so combinations behave the
way reading them aloud suggests.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from ..data import ParityData, Unpaired
from ..tolerances import NamedTolerance, failures, pass_fail


@dataclass(frozen=True)
class FilterSet:
    """Which records are currently worth looking at."""

    outside_tolerance_only: bool = False
    show_paired: bool = True
    show_unpaired: bool = True
    x_range: tuple[float, float] | None = None

    @property
    def is_active(self) -> bool:
        """Whether this differs from showing everything."""
        return (
            self.outside_tolerance_only
            or not self.show_paired
            or not self.show_unpaired
            or self.x_range is not None
        )

    def apply(
        self,
        data: ParityData,
        tolerances: Sequence[NamedTolerance] = (),
    ) -> ParityData:
        """Return the subset of ``data`` that passes every active filter.

        A default FilterSet returns an equal dataset, which the golden tests
        depend on: an unfiltered designer must render exactly what the CLI does.
        """
        paired = list(zip(data.keys, data.x, data.y))

        if not self.show_paired:
            paired = []
        else:
            if self.outside_tolerance_only and pass_fail(tolerances):
                # Keep paired records that fail ANY pass/fail tolerance.
                # Informational entries are never judged -- a point cannot fail
                # a reference band -- so only pass/fail criteria gate here.
                # An unpaired record has no verdict, so this switch says nothing
                # about it; show_unpaired governs those.
                paired = [
                    (k, x, y) for k, x, y in paired if failures(tolerances, x, y)
                ]
            if self.x_range is not None:
                paired = [(k, x, y) for k, x, y in paired if self._in_range(x)]

        missing_y = self._filter_unpaired(data.missing_y)
        missing_x = self._filter_unpaired(data.missing_x, has_x=False)

        return replace(
            data,
            keys=[k for k, _, _ in paired],
            x=[x for _, x, _ in paired],
            y=[y for _, _, y in paired],
            missing_y=missing_y,
            missing_x=missing_x,
        )

    def _filter_unpaired(self, unpaired: Unpaired, has_x: bool = True) -> Unpaired:
        if not self.show_unpaired:
            return Unpaired([], [])
        if self.x_range is None:
            return unpaired
        if not has_x:
            # These records have no x value, so no x window contains them.
            return Unpaired([], [])
        kept = [
            (k, v) for k, v in zip(unpaired.keys, unpaired.values) if self._in_range(v)
        ]
        return Unpaired([k for k, _ in kept], [v for _, v in kept])

    def _in_range(self, value: float) -> bool:
        assert self.x_range is not None
        low, high = self.x_range
        return low <= value <= high