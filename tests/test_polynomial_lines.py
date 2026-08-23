from __future__ import annotations

import pytest

from parity_plot.config import ParityConfig, PlotConfig
from parity_plot.data import from_sequences
from parity_plot.designer.serialize import config_to_toml
from parity_plot.plot import build_figure
from parity_plot.polynomial_lines import PolynomialLine, PolynomialLineError
from parity_plot.themes import get as get_theme


def test_csv_coefficients_drive_value_and_equation_label():
    line = PolynomialLine.from_csv("2, -3, 0, 4")

    assert line.evaluate(2) == 8.0
    assert line.equation == "y = 2x^3 - 3x^2 + 4"


def test_equation_and_editor_csv_preserve_coefficient_precision():
    line = PolynomialLine((1.23456789, 0.0, -9.87654321))

    assert line.equation == "y = 1.23456789x^2 - 9.87654321"
    assert line.coefficients_csv == "1.23456789, 0, -9.87654321"


def test_line_style_is_limited_to_the_interface_choices():
    assert PolynomialLine((1, 0), color="red", style="dotted").style == "dotted"

    with pytest.raises(PolynomialLineError, match="style"):
        PolynomialLine((1, 0), style="dashdot")


def test_config_accepts_repeatable_polynomial_line_tables():
    config = ParityConfig.from_dict(
        {
            "plot": {
                "polynomial_lines": [
                    {
                        "coefficients": "2, -3, 0, 4",
                        "color": "orange",
                        "style": "dashed",
                    },
                    {"coefficients": [1, 0]},
                ]
            }
        }
    )

    assert [line.coefficients for line in config.plot.polynomial_lines] == [
        (2.0, -3.0, 0.0, 4.0),
        (1.0, 0.0),
    ]


def test_plot_draws_polynomial_with_equation_legend_color_and_style():
    line = PolynomialLine((2, 0, -1), color="orange", style="dotted")
    data = from_sequences([0, 1, 2], [0, 1, 2])

    figure = build_figure(data, PlotConfig(polynomial_lines=(line,)))
    trace = next(trace for trace in figure.data if trace.name == "y = 2x^2 - 1")

    assert trace.showlegend is True
    assert trace.line.color == get_theme("dark").resolve_color("orange")
    assert trace.line.dash == "dot"


def test_polynomial_lines_round_trip_through_designer_toml(tmp_path):
    config = ParityConfig.from_dict(
        {
            "plot": {
                "polynomial_lines": [
                    {
                        "coefficients": "2, 0, -1",
                        "color": "orange",
                        "style": "dashed",
                    }
                ]
            }
        }
    )
    path = tmp_path / "polynomials.toml"

    path.write_text(config_to_toml(config), encoding="utf-8")

    assert ParityConfig.from_toml(path) == config
