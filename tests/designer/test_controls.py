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


def specs_for(section: str) -> dict[str, ControlSpec]:
    return {s.key: s for s in CONTROL_SPECS if s.section == section}


def test_every_plot_setting_has_a_control():
    """A setting with no control is a setting the designer silently cannot
    reach, which makes the saved config differ from what was on screen.

    `tolerances` has its own list panel, and `encoding` gets a dedicated panel
    in the data-sources Phase 3 work; neither is a plain control, so both are
    excluded here (a saved config still carries whatever the CLI or TOML set)."""
    plot_fields = {f.name for f in fields(PlotConfig)} - {"tolerances", "encoding"}
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


def test_every_spec_has_a_human_label():
    for spec in CONTROL_SPECS:
        assert spec.label and not spec.label.endswith("_")
        assert spec.help


def test_no_retired_spec_remains():
    """abstol/reltol/band_style/identity_line moved into the tolerance list;
    pointing a control at a deleted field would make the designer 500."""
    retired = {"abstol", "reltol", "band_style", "identity_line"}
    assert not {s.key for s in CONTROL_SPECS} & retired