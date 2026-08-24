from parity_plot.designer.panels.polynomial_lines import COEFFICIENTS_INPUT_LABEL


def test_coefficients_input_label_explains_highest_degree_first():
    assert COEFFICIENTS_INPUT_LABEL == (
        "Coefficients: Highest Degree First (Comma-Separated)"
    )
