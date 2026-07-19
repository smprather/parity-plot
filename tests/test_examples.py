from __future__ import annotations

import csv
import math

import pytest

from parity_plot.examples import ExampleSpec, SpecError, generate, write_all


def counts(records):
    paired = sum(1 for r in records if r.reference is not None and r.measured is not None)
    miss_y = sum(1 for r in records if r.reference is not None and r.measured is None)
    miss_x = sum(1 for r in records if r.reference is None and r.measured is not None)
    both = sum(1 for r in records if r.reference is None and r.measured is None)
    return paired, miss_y, miss_x, both


def test_null_counts_are_exact_and_disjoint():
    records = generate(n=100, n_missing_y=7, n_missing_x=5, n_both_null=3)
    assert counts(records) == (85, 7, 5, 3)


def test_same_seed_gives_identical_data():
    assert generate(n=50, seed=99) == generate(n=50, seed=99)


def test_different_seeds_give_different_data():
    assert generate(n=50, seed=1) != generate(n=50, seed=2)


def test_reference_values_land_mostly_inside_the_requested_range():
    """The bounds describe the central 95% of draws, not hard limits."""
    records = generate(n=2000, seed=4, x_min=10, x_max=1000,
                       n_missing_x=0, n_missing_y=0, n_both_null=0)
    values = [r.reference for r in records]

    inside = sum(1 for v in values if 10 <= v <= 1000)
    assert 0.90 < inside / len(values) < 1.0
    assert math.isclose(sorted(values)[len(values) // 2], 100, rel_tol=0.15)


def test_more_noise_widens_the_scatter():
    def spread(noise):
        recs = generate(n=500, seed=8, noise=noise, outlier_rate=0, bias=0,
                        n_missing_x=0, n_missing_y=0, n_both_null=0)
        return sum((r.measured - r.reference) ** 2 for r in recs)

    assert spread(0.30) > spread(0.02) * 10


def test_bias_shifts_measurements_upward():
    def mean_error(bias):
        recs = generate(n=500, seed=8, bias=bias, noise=0.01, outlier_rate=0,
                        n_missing_x=0, n_missing_y=0, n_both_null=0)
        return sum(r.measured - r.reference for r in recs) / len(recs)

    assert mean_error(0.0) < mean_error(0.05) < mean_error(0.20)


def test_zero_outlier_rate_produces_none():
    """With no outliers and tiny noise, nothing should sit far off the line."""
    recs = generate(n=1000, seed=11, noise=0.01, noise_floor=0.0, bias=0,
                    outlier_rate=0, n_missing_x=0, n_missing_y=0, n_both_null=0)
    worst = max(abs(r.measured - r.reference) / r.reference for r in recs)
    assert worst < 0.10


def test_outliers_appear_when_requested():
    # An outlier is `outlier_scale * noise` off the line: 9 * 0.02 = 18%, so a
    # 10% threshold separates them cleanly from the 2% ordinary scatter.
    recs = generate(n=1000, seed=11, noise=0.02, noise_floor=0.0, bias=0,
                    outlier_rate=0.05, n_missing_x=0, n_missing_y=0, n_both_null=0)
    far = [r for r in recs if abs(r.measured - r.reference) / r.reference > 0.10]
    assert 25 < len(far) < 80  # ~5% of 1000, allowing for sampling spread


def test_keyword_overrides_apply_to_a_spec():
    spec = ExampleSpec(n=10, noise=0.5)
    assert generate(spec, n=20) == generate(ExampleSpec(n=20, noise=0.5))


def test_none_overrides_are_ignored():
    """A CLI passes every flag, so unset ones arrive as None."""
    assert generate(ExampleSpec(n=10, seed=3), n=None, noise=None) == generate(n=10, seed=3)


def test_unknown_override_is_rejected():
    with pytest.raises(SpecError, match="unknown example option"):
        generate(n=10, sigma=0.5)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"n": 0}, "at least one record"),
        ({"x_min": 0}, "x_min must be positive"),
        ({"x_min": -1}, "x_min must be positive"),
        ({"x_min": 100, "x_max": 10}, "must be greater than"),
        ({"noise": -0.1}, "cannot be negative"),
        ({"noise_floor": -1}, "cannot be negative"),
        ({"outlier_rate": 1.5}, "fraction between 0 and 1"),
        ({"outlier_rate": -0.1}, "fraction between 0 and 1"),
        ({"n_missing_x": -1}, "cannot be negative"),
        ({"n": 5, "n_missing_y": 10}, "only 5 records exist"),
    ],
)
def test_impossible_specs_are_rejected(kwargs, message):
    with pytest.raises(SpecError, match=message):
        ExampleSpec(**kwargs)


def test_null_counts_scale_with_n_by_default():
    """Defaults sized for n=1000 must not make a small n impossible."""
    assert ExampleSpec(n=1000).n_missing_y == 15
    assert ExampleSpec(n=1000).n_missing_x == 12
    assert ExampleSpec(n=1000).n_both_null == 2

    small = ExampleSpec(n=10)
    assert small.n_nulls <= small.n
    assert counts(generate(n=10)) [0] > 0  # and it actually generates


def test_explicit_null_counts_are_left_alone():
    spec = ExampleSpec(n=1000, n_missing_y=0, n_missing_x=99)
    assert spec.n_missing_y == 0
    assert spec.n_missing_x == 99
    assert spec.n_both_null == 2  # unset, so still proportional


def test_log_parameters_bracket_the_requested_range():
    spec = ExampleSpec(x_min=10, x_max=1000)
    assert math.isclose(math.exp(spec.log_mu), 100)
    assert spec.log_sigma > 0


def test_write_all_emits_both_shapes_from_the_same_draws(tmp_path):
    written = write_all(tmp_path, n=100, seed=6, n_missing_y=4, n_missing_x=3, n_both_null=2)

    wide = list(csv.DictReader(written["wide"].open()))
    reference = list(csv.DictReader(written["reference"].open()))
    measured = list(csv.DictReader(written["measured"].open()))

    assert len(wide) == 100
    # A null is a blank cell in wide mode but an absent row in join mode.
    assert len(reference) == 100 - 3 - 2
    assert len(measured) == 100 - 4 - 2

    by_id = {r["id"]: r for r in wide}
    for row in reference:
        assert by_id[row["id"]]["reference"] == row["value"]
    for row in measured:
        assert by_id[row["id"]]["measured"] == row["value"]


def test_written_files_use_unix_line_endings(tmp_path):
    written = write_all(tmp_path, n=10, n_missing_y=1, n_missing_x=1, n_both_null=0)
    assert b"\r\n" not in written["wide"].read_bytes()
