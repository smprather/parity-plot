# tests/designer/test_controls.py
from __future__ import annotations

from dataclasses import fields

import pytest

from parity_plot.config import (
    LEGEND_POSITIONS,
    NULL_MODES,
    OUTPUT_FORMATS,
    THEMES,
    OutputConfig,
    PlotConfig,
    StatsConfig,
)
from parity_plot.designer.panels.controls import CONTROL_SPECS, ControlSpec
from parity_plot.designer.panels.histogram import HISTOGRAM_FIELDS


def specs_for(section: str) -> dict[str, ControlSpec]:
    return {s.key: s for s in CONTROL_SPECS if s.section == section}


def test_every_plot_setting_has_a_control():
    """A setting with no control is a setting the designer silently cannot
    reach, which makes the saved config differ from what was on screen.

    `tolerances`, polynomial lines, `encoding`, and histogram settings have
    dedicated panels; none is a plain control, so they are excluded here."""
    plot_fields = {f.name for f in fields(PlotConfig)} - {
        "tolerances",
        "polynomial_lines",
        "encoding",
        *HISTOGRAM_FIELDS,
    }
    assert specs_for("plot").keys() == plot_fields


def test_every_stats_and_output_setting_has_a_control():
    assert specs_for("stats").keys() == {f.name for f in fields(StatsConfig)}
    assert specs_for("output").keys() == {f.name for f in fields(OutputConfig)}


def test_data_settings_are_not_editable_in_phase_1():
    """The dataset is fixed for the session; column mapping is Phase 2."""
    assert specs_for("data") == {}


@pytest.mark.parametrize(
    "section, key, expected",
    [
        ("plot", "theme", THEMES),
        ("plot", "legend", LEGEND_POSITIONS),
        ("plot", "nulls", NULL_MODES),
        ("output", "format", OUTPUT_FORMATS),
    ],
)
def test_choice_controls_offer_exactly_the_valid_values(section, key, expected):
    spec = specs_for(section)[key]
    assert spec.kind == "choice"
    assert spec.choices == tuple(expected)


def test_booleans_are_switches():
    for key in ("log", "equal_axes"):
        assert specs_for("plot")[key].kind == "switch"
    assert specs_for("stats")["show"].kind == "switch"


def test_viewport_origins_are_optional_number_controls():
    specs = specs_for("plot")

    assert specs["x_origin"].kind == "number"
    assert specs["x_origin"].label == "Viewport origin X"
    assert specs["y_origin"].kind == "number"
    assert specs["y_origin"].label == "Viewport origin Y"


def test_every_spec_has_a_human_label():
    for spec in CONTROL_SPECS:
        assert spec.label and not spec.label.endswith("_")
        assert spec.help


def test_no_retired_spec_remains():
    """abstol/reltol/band_style/identity_line moved into the tolerance list;
    pointing a control at a deleted field would make the designer 500."""
    retired = {"abstol", "reltol", "band_style", "identity_line"}
    assert not {s.key for s in CONTROL_SPECS} & retired


def test_placeholder_for_labels_is_the_column_name(tmp_path):
    from parity_plot.data import ParityData
    from parity_plot.designer.panels.controls import _placeholder

    data = ParityData(x=[1.0], y=[1.0], x_label="reference", y_label="measured")
    assert _placeholder(specs_for("plot")["x_label"], data) == "reference"
    assert _placeholder(specs_for("plot")["y_label"], data) == "measured"


def test_placeholder_for_labels_without_data_is_generic():
    from parity_plot.designer.panels.controls import _placeholder

    assert _placeholder(specs_for("plot")["x_label"], None) == "column name"


def test_placeholder_falls_back_to_a_static_default():
    from parity_plot.designer.panels.controls import _placeholder

    # title's dataclass default is "Parity Plot"
    assert _placeholder(specs_for("plot")["title"], None) == "Parity Plot"
