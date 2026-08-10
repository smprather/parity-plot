from __future__ import annotations

from dataclasses import fields

from parity_plot.config import PlotConfig
from parity_plot.designer.panels.histogram import (
    HISTOGRAM_FIELDS,
    build_histogram_panel,  # noqa: F401 (import guard)
)


def test_histogram_panel_owns_every_histogram_setting():
    plot_fields = {f.name for f in fields(PlotConfig)}

    assert set(HISTOGRAM_FIELDS) <= plot_fields
    assert HISTOGRAM_FIELDS[0] == "delta_histogram"
