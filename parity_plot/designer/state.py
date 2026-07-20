"""The designer's single source of truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import plotly.graph_objects as go

from ..config import ConfigError, ParityConfig
from ..data import DataError, ParityData, load
from ..plot import build_figure
from ..tolerance import Tolerance
from .records import RecordView, find_record, record_views


@dataclass
class DesignerState:
    """Everything the UI reads from and writes to.

    Widgets never hold state of their own; they push edits in here and re-read
    the result, so the config on screen and the config that will be saved
    cannot disagree.
    """

    config: ParityConfig
    data: ParityData
    selection: str | None = None
    last_error: str | None = None
    _last_figure: go.Figure | None = field(default=None, repr=False)

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

    def selected_record(self, tol: Tolerance | None = None) -> RecordView | None:
        """The pinned record, judged against ``tol`` if one is given."""
        if self.selection is None:
            return None
        return find_record(record_views(self.data, tol), self.selection)

    def figure(self) -> go.Figure:
        """Build the preview, keeping the last good one if this build fails.

        A rejected setting must not clear the screen -- losing the plot on a
        typo makes the tool feel broken and hides what you were comparing
        against.
        """
        try:
            figure = build_figure(self.data, self.config.plot, self.config.stats)
        except (ConfigError, ValueError) as exc:
            self.last_error = str(exc)
            if self._last_figure is None:
                raise
            return self._last_figure

        self.last_error = None
        self._last_figure = figure
        return figure