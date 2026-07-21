"""The designer's single source of truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import plotly.graph_objects as go

from ..config import ConfigError, ParityConfig
from ..data import DataError, ParityData, load
from ..plot import build_figure
from ..tolerances import NamedTolerance
from .filters import FilterSet
from .records import RecordView, find_record, record_views


@dataclass
class DesignerState:
    """Everything the UI reads from and writes to.

    Widgets never hold state of their own; they push edits in here and re-read
    the result, so the config on screen and the config that will be saved
    cannot disagree.
    """

    config: ParityConfig
    # None before any file is opened -- the designer starts empty and shows a
    # blank plot until files and ref/test are chosen.
    data: ParityData | None = None
    selection: str | None = None
    filters: FilterSet = field(default_factory=FilterSet)
    last_error: str | None = None
    _last_figure: go.Figure | None = field(default=None, repr=False)

    @property
    def has_data(self) -> bool:
        return self.data is not None

    def update(self, section: str, **values: Any) -> bool:
        """Apply settings to one config section. Returns whether it worked.

        Routed through ``ParityConfig.merge`` so the designer inherits exactly
        the validation and error text the TOML and CLI paths already use.
        """
        try:
            self.config = self.config.merge(**{section: values})
        except (ConfigError, ValueError) as exc:
            self.last_error = str(exc)
            return False
        self.last_error = None
        return True

    def set_data_source(self, **values: Any) -> bool:
        """Point at a different file or column mapping. Returns whether it worked.

        On failure the previously loaded dataset and the config are both left
        untouched: losing a working dataset because of a typo in a column name
        would be far worse than the error message.
        """
        try:
            candidate = self.config.merge(data=values)
            data = load(candidate.data)
        except (ConfigError, DataError, ValueError) as exc:
            self.last_error = str(exc)
            return False

        self.config = candidate
        self.data = data
        self.last_error = None
        if self.selection is not None and find_record(record_views(data), self.selection) is None:
            # The pinned record does not exist in the new dataset.
            self.selection = None
        return True

    def selected_record(
        self, tolerances: Sequence[NamedTolerance] = ()
    ) -> RecordView | None:
        """The pinned record, judged against ``tolerances`` if any are given."""
        if self.selection is None or self.data is None:
            return None
        return find_record(record_views(self.data, tolerances), self.selection)

    def tolerances(self) -> tuple[NamedTolerance, ...]:
        """The tolerance list the current config specifies."""
        return self.config.plot.tolerances

    def visible_data(self) -> ParityData:
        """The dataset after filtering. The plot and the table both read this.

        Empty (not None) before any file is opened, so consumers need no None
        guard of their own.
        """
        if self.data is None:
            return ParityData()
        return self.filters.apply(self.data, self.tolerances())

    def visible_records(self) -> list[RecordView]:
        """One row per visible record, judged against the current tolerances."""
        return record_views(self.visible_data(), self.tolerances())

    def counts(self) -> tuple[int, int]:
        """``(showing, total)`` records -- a filtered view that looks unfiltered
        is a trap, so the UI always states both."""
        if self.data is None:
            return 0, 0
        visible = self.visible_data()
        showing = visible.n_paired + visible.n_unpaired
        total = self.data.n_paired + self.data.n_unpaired
        return showing, total

    def figure(self) -> go.Figure:
        """Build the preview, keeping the last good one if this build fails.

        A rejected setting must not clear the screen -- losing the plot on a
        typo makes the tool feel broken and hides what you were comparing
        against.
        """
        try:
            figure = build_figure(self.visible_data(), self.config.plot, self.config.stats)
        except (ConfigError, ValueError) as exc:
            self.last_error = str(exc)
            if self._last_figure is None:
                raise
            return self._last_figure

        # Deliberately does NOT clear `last_error`. A failed `set_data_source`
        # leaves the previous dataset loaded, so the very next `figure()` call
        # succeeds -- and clearing here would wipe the explanation before the
        # error banner ever displayed it. Errors are cleared by whatever
        # succeeds next: `update` or `set_data_source`.
        self._last_figure = figure
        return figure