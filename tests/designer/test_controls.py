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
    ParityConfig,
    PlotConfig,
    StatsConfig,
)
from parity_plot.data import from_sequences
from parity_plot.designer.panels.controls import (
    CONTROL_SPECS,
    VIEWPORT_ORIGIN_FIELDS,
    VIEWPORT_ORIGIN_FORMAT,
    VIEWPORT_ORIGIN_METHODS,
    ControlSpec,
    apply_viewport_origin_method,
    current_viewport_origins,
    viewport_origin_method,
)
from parity_plot.designer.panels.histogram import HISTOGRAM_FIELDS
from parity_plot.designer.state import DesignerState


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
        *VIEWPORT_ORIGIN_FIELDS,
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


def test_viewport_origins_have_a_dedicated_three_method_control():
    assert VIEWPORT_ORIGIN_METHODS == ("Auto", "0,0", "Custom")
    assert VIEWPORT_ORIGIN_FORMAT == "%.12g"
    assert not VIEWPORT_ORIGIN_FIELDS & specs_for("plot").keys()


def test_viewport_origin_method_matches_stored_values():
    assert viewport_origin_method(PlotConfig()) == "Auto"
    assert viewport_origin_method(PlotConfig(x_origin=0, y_origin=0)) == "0,0"
    assert viewport_origin_method(PlotConfig(x_origin=2, y_origin=-3)) == "Custom"


def test_custom_inputs_start_with_current_automatic_plot_bounds():
    state = DesignerState(
        config=ParityConfig(),
        data=from_sequences([10, 20, 30], [11, 21, 31]),
    )
    figure = state.figure()

    assert current_viewport_origins(state) == pytest.approx(
        (figure.layout.xaxis.range[0], figure.layout.yaxis.range[0])
    )


def test_current_log_viewport_origins_are_returned_in_data_units():
    state = DesignerState(
        config=ParityConfig.from_dict({"plot": {"log": True}}),
        data=from_sequences([10, 100], [20, 200]),
    )
    figure = state.figure()

    assert current_viewport_origins(state) == pytest.approx(
        (10 ** figure.layout.xaxis.range[0], 10 ** figure.layout.yaxis.range[0])
    )


def test_viewport_method_updates_both_config_fields():
    state = DesignerState(config=ParityConfig())

    assert apply_viewport_origin_method(state, "0,0")
    assert (state.config.plot.x_origin, state.config.plot.y_origin) == (0.0, 0.0)

    assert apply_viewport_origin_method(state, "Custom", 2.5, -3.5)
    assert (state.config.plot.x_origin, state.config.plot.y_origin) == (2.5, -3.5)

    assert apply_viewport_origin_method(state, "Auto")
    assert (state.config.plot.x_origin, state.config.plot.y_origin) == (None, None)


def test_custom_viewport_method_requires_both_values():
    state = DesignerState(config=ParityConfig())

    assert not apply_viewport_origin_method(state, "Custom", 1.0, None)
    assert state.config.plot.x_origin is None
    assert state.config.plot.y_origin is None
    assert "both X and Y" in state.last_error


def test_zero_origin_method_is_rejected_for_log_axes():
    state = DesignerState(
        config=ParityConfig.from_dict({"plot": {"log": True}}),
    )

    assert not apply_viewport_origin_method(state, "0,0")
    assert state.config.plot.x_origin is None
    assert state.config.plot.y_origin is None
    assert "positive on log axes" in state.last_error


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
