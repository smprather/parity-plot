# tests/designer/test_controls.py
from __future__ import annotations

from dataclasses import fields

import pytest

from parity_plot.config import (
    BAND_STYLES,
    LEGEND_POSITIONS,
    NULL_MODES,
    OUTPUT_FORMATS,
    THEMES,
    OutputConfig,
    PlotConfig,
    StatsConfig,
)
from parity_plot.designer.panels.controls import CONTROL_SPECS, ControlSpec


def specs_for(section: str) -> dict[str, ControlSpec]:
    return {s.key: s for s in CONTROL_SPECS if s.section == section}


def test_every_plot_setting_has_a_control():
    """A setting with no control is a setting the designer silently cannot
    reach, which makes the saved config differ from what was on screen."""
    assert specs_for("plot").keys() == {f.name for f in fields(PlotConfig)}


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
        ("plot", "band_style", BAND_STYLES),
        ("output", "format", OUTPUT_FORMATS),
    ],
)
def test_choice_controls_offer_exactly_the_valid_values(section, key, expected):
    spec = specs_for(section)[key]
    assert spec.kind == "choice"
    assert spec.choices == tuple(expected)


def test_relative_tolerance_is_a_text_control_not_a_percent_spinner():
    """`--reltol` takes a ratio or an explicit `10pct`; a percent-only spinner
    would reintroduce exactly the unit ambiguity that spelling prevents."""
    spec = specs_for("plot")["reltol"]
    assert spec.kind == "text"
    assert "pct" in spec.help


def test_booleans_are_switches():
    for key in ("log", "equal_axes", "identity_line"):
        assert specs_for("plot")[key].kind == "switch"
    assert specs_for("stats")["show"].kind == "switch"


def test_every_spec_has_a_human_label():
    for spec in CONTROL_SPECS:
        assert spec.label and not spec.label.endswith("_")
        assert spec.help