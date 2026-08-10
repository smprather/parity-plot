"""Dedicated controls for the delta histogram panel."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from ...plot import delta_histogram_bin_count
from ..state import DesignerState
from .section import section

HISTOGRAM_FIELDS = (
    "delta_histogram",
    "delta_histogram_bins_auto",
    "delta_histogram_bins",
    "delta_histogram_bucket_labels",
    "delta_histogram_sigma_lines",
)


def _displayed_auto_bucket_count(state: DesignerState) -> int | None:
    data = state.visible_data()
    deltas = [yi - xi for xi, yi in zip(data.x, data.y)]
    if not deltas:
        return None
    plot = replace(state.config.plot, delta_histogram_bins_auto=True)
    return delta_histogram_bin_count(deltas, plot)


def _bucket_field_value(state: DesignerState) -> int | None:
    if state.config.plot.delta_histogram_bins_auto:
        return _displayed_auto_bucket_count(state)
    return state.config.plot.delta_histogram_bins


def build_histogram_panel(state: DesignerState, on_change: Callable[[], None]) -> None:
    """Histogram settings, with dependent controls disabled when inactive."""
    from nicegui import ui

    plot = state.config.plot

    with section("Histogram"):
        enabled = ui.switch("Enable", value=plot.delta_histogram)

        auto_bins = ui.switch(
            "Auto buckets", value=plot.delta_histogram_bins_auto
        ).tooltip("Choose the bucket count from the visible paired data.")
        buckets = ui.number(
            "Buckets",
            value=_bucket_field_value(state),
            min=1,
            step=1,
            precision=0,
            placeholder="",
        ).classes("w-full")
        bucket_labels = ui.switch(
            "Bucket centre labels", value=plot.delta_histogram_bucket_labels
        ).tooltip("Show vertical x-axis tick labels at the bucket centres.")
        sigma_lines = ui.switch(
            "±1σ lines", value=plot.delta_histogram_sigma_lines
        ).tooltip(
            "Show dashed vertical lines at plus and minus one standard deviation."
        )

        def sync_enabled() -> None:
            active = bool(enabled.value)
            auto = bool(auto_bins.value)
            auto_bins.set_enabled(active)
            buckets.set_enabled(active and not auto)
            bucket_labels.set_enabled(active)
            sigma_lines.set_enabled(active)

        def bucket_value() -> int | None:
            if buckets.value in (None, ""):
                return None
            return int(buckets.value)

        def prefill_manual_buckets() -> None:
            if auto_bins.value:
                return
            count = _displayed_auto_bucket_count(state)
            if count is None:
                return
            buckets.value = count
            buckets.update()

        def commit() -> None:
            value = bucket_value()
            if auto_bins.value or value is None:
                state.reset_fields("plot", "delta_histogram_bins")
                state.update(
                    "plot",
                    delta_histogram=bool(enabled.value),
                    delta_histogram_bins_auto=bool(auto_bins.value),
                    delta_histogram_bucket_labels=bool(bucket_labels.value),
                    delta_histogram_sigma_lines=bool(sigma_lines.value),
                )
            else:
                state.update(
                    "plot",
                    delta_histogram=bool(enabled.value),
                    delta_histogram_bins_auto=bool(auto_bins.value),
                    delta_histogram_bins=value,
                    delta_histogram_bucket_labels=bool(bucket_labels.value),
                    delta_histogram_sigma_lines=bool(sigma_lines.value),
                )
            sync_enabled()
            on_change()

        def changed() -> None:
            sync_enabled()
            commit()

        def auto_changed() -> None:
            prefill_manual_buckets()
            changed()

        enabled.on_value_change(lambda _: changed())
        auto_bins.on_value_change(lambda _: auto_changed())
        buckets.on_value_change(lambda _: changed())
        bucket_labels.on_value_change(lambda _: changed())
        sigma_lines.on_value_change(lambda _: changed())

        sync_enabled()
