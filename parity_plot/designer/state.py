"""The designer's single source of truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import plotly.graph_objects as go

from ..config import ConfigError, ParityConfig
from ..data import ParityData
from ..plot import build_figure


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