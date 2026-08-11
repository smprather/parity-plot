from __future__ import annotations

from dataclasses import fields

from parity_plot.config import ParityConfig, PlotConfig
from parity_plot.data import from_sequences
from parity_plot.designer.panels.histogram import (
    HISTOGRAM_FIELDS,
    _bucket_field_value,
    _displayed_auto_bucket_count,
    build_histogram_panel,  # noqa: F401 (import guard)
)
from parity_plot.designer.state import DesignerState


def test_histogram_panel_owns_every_histogram_setting():
    plot_fields = {f.name for f in fields(PlotConfig)}

    assert set(HISTOGRAM_FIELDS) <= plot_fields
    assert HISTOGRAM_FIELDS[0] == "delta_histogram"


def test_manual_bucket_prefill_uses_the_current_auto_count():
    data = from_sequences(x=[1, 2, 3, 4, 5], y=[2, 3, 4, 5, 6])
    state = DesignerState(config=ParityConfig(), data=data)

    assert _displayed_auto_bucket_count(state) == 3
    assert _bucket_field_value(state) == 3


def test_auto_bucket_count_is_rounded_up_to_an_odd_count():
    data = from_sequences(x=range(10), y=range(10))
    state = DesignerState(config=ParityConfig(), data=data)

    assert _displayed_auto_bucket_count(state) == 5


def test_manual_bucket_field_keeps_manual_count_when_auto_is_off():
    data = from_sequences(x=[1, 2, 3, 4, 5], y=[2, 3, 4, 5, 6])
    config = ParityConfig().merge(
        plot={"delta_histogram_bins_auto": False, "delta_histogram_bins": 9}
    )
    state = DesignerState(config=config, data=data)

    assert _bucket_field_value(state) == 9


def test_auto_prefill_ignores_stale_manual_count():
    data = from_sequences(x=[1, 2, 3, 4, 5], y=[2, 3, 4, 5, 6])
    config = ParityConfig().merge(
        plot={"delta_histogram_bins_auto": True, "delta_histogram_bins": 9}
    )
    state = DesignerState(config=config, data=data)

    assert _bucket_field_value(state) == 3
