from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import (
    EXAMPLE_TOML,
    ConfigError,
    OutputConfig,
    ParityConfig,
    PlotConfig,
)


def test_defaults_are_usable_without_any_toml():
    cfg = ParityConfig()
    assert cfg.plot.theme == "dark"  # dark by default, per the design
    assert cfg.plot.nulls == "rug"
    # format is unset by default and resolves from the path's extension.
    assert cfg.output.resolved_format == "html"
    assert cfg.data.files == ()


def test_round_trip_of_the_shipped_example(tmp_path: Path):
    path = tmp_path / "parity.toml"
    path.write_text(EXAMPLE_TOML, encoding="utf-8")

    cfg = ParityConfig.from_toml(path)

    assert cfg.data.files == (Path("data/example.csv"),)
    assert cfg.data.ref == "data/example.csv:reference"
    assert cfg.data.test == "data/example.csv:measured"
    assert cfg.plot.theme == "dark"
    assert cfg.plot.delta_histogram is False
    assert cfg.plot.delta_histogram_bins_auto is True
    assert cfg.plot.delta_histogram_bins is None
    assert cfg.plot.delta_histogram_bucket_labels is False
    assert cfg.plot.delta_histogram_sigma_lines is False
    assert cfg.plot.delta_histogram_log_y is False
    tols = cfg.plot.tolerances
    # The built-in y = x line is guaranteed first; the shipped example adds "spec".
    assert len(tols) == 2
    assert tols[0].name == "parity"
    assert tols[1].name == "spec"
    assert tols[1].reltol == pytest.approx(0.10)
    assert tols[1].abstol is None  # commented out in the shipped example
    assert tols[1].style == "lines"  # the default
    assert cfg.stats.metrics == ("n", "r2", "rmse", "mae", "bias", "std", "max_abs_err")
    assert cfg.output.width == 900


def test_delta_histogram_can_be_enabled_from_toml():
    cfg = ParityConfig.from_dict(
        {
            "plot": {
                "delta_histogram": True,
                "delta_histogram_bins_auto": False,
                "delta_histogram_bins": 25,
                "delta_histogram_bucket_labels": True,
                "delta_histogram_sigma_lines": True,
                "delta_histogram_log_y": True,
            }
        }
    )
    assert cfg.plot.delta_histogram is True
    assert cfg.plot.delta_histogram_bins_auto is False
    assert cfg.plot.delta_histogram_bins == 25
    assert cfg.plot.delta_histogram_bucket_labels is True
    assert cfg.plot.delta_histogram_sigma_lines is True
    assert cfg.plot.delta_histogram_log_y is True


def test_viewport_origins_load_as_optional_finite_numbers():
    cfg = ParityConfig.from_dict({"plot": {"x_origin": "0", "y_origin": -2.5}})

    assert cfg.plot.x_origin == 0.0
    assert cfg.plot.y_origin == -2.5


@pytest.mark.parametrize("key", ["x_origin", "y_origin"])
@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf"), "not-a-number", True]
)
def test_viewport_origins_must_be_finite(key, value):
    with pytest.raises(ConfigError, match="finite number"):
        ParityConfig.from_dict({"plot": {key: value}})


@pytest.mark.parametrize("key", ["x_origin", "y_origin"])
def test_log_viewport_origins_must_be_positive(key):
    with pytest.raises(ConfigError, match="positive on log axes"):
        ParityConfig.from_dict({"plot": {"log": True, key: 0}})


def test_unknown_key_is_rejected_with_the_valid_names():
    """A silently ignored typo would render the default and look like a bug."""
    with pytest.raises(ConfigError) as exc:
        ParityConfig.from_dict({"plot": {"thmee": "light"}})
    assert "thmee" in str(exc.value)
    assert "theme" in str(exc.value)


def test_unknown_section_is_rejected():
    with pytest.raises(ConfigError, match="unknown section"):
        ParityConfig.from_dict({"plotting": {}})


def test_invalid_choices_are_rejected():
    with pytest.raises(ConfigError, match="not one of"):
        ParityConfig.from_dict({"plot": {"theme": "solarized"}})
    with pytest.raises(ConfigError, match="not one of"):
        ParityConfig.from_dict({"plot": {"nulls": "hide"}})
    with pytest.raises(ConfigError, match="not one of"):
        ParityConfig.from_dict({"output": {"format": "jpeg"}})


def test_invalid_scalars_are_rejected():
    with pytest.raises(ConfigError, match="positive"):
        ParityConfig.from_dict({"output": {"width": 0}})
    # The retired v0.1.0 scalar tolerance keys are rejected with a teaching
    # message pointing at [[plot.tolerances]] (see test_config_tolerances.py).
    with pytest.raises(ConfigError, match="moved into a tolerance list"):
        ParityConfig.from_dict({"plot": {"abstol": -0.2}})
    with pytest.raises(ConfigError, match="moved into a tolerance list"):
        ParityConfig.from_dict({"plot": {"reltol": 0}})
    with pytest.raises(ConfigError, match="true or false"):
        ParityConfig.from_dict({"plot": {"log": "yes"}})
    with pytest.raises(ConfigError, match="positive"):
        ParityConfig.from_dict({"plot": {"delta_histogram_bins": 0}})
    with pytest.raises(ConfigError, match="odd"):
        ParityConfig.from_dict({"plot": {"delta_histogram_bins": 24}})
    with pytest.raises(ConfigError, match="odd"):
        ParityConfig().merge(plot={"delta_histogram_bins": 24})
    with pytest.raises(ConfigError, match="odd"):
        PlotConfig(delta_histogram_bins=24)


@pytest.mark.parametrize("value", [True, 640.9])
def test_integer_config_fields_reject_booleans_and_fractions(value):
    with pytest.raises(ConfigError, match="integer"):
        ParityConfig.from_dict({"output": {"width": value}})
    with pytest.raises(ConfigError, match="integer"):
        OutputConfig(width=value)
    with pytest.raises(ConfigError, match="integer"):
        PlotConfig(delta_histogram_bins=value)


def test_overrides_beat_the_file_but_none_is_ignored():
    cfg = ParityConfig.from_dict({"plot": {"theme": "light", "title": "From file"}})

    merged = cfg.merge(plot={"theme": "dark", "title": None})

    assert merged.plot.theme == "dark"  # the override won
    assert merged.plot.title == "From file"  # the None did not clobber it


def test_merge_leaves_untouched_sections_alone():
    cfg = ParityConfig.from_dict({"output": {"width": 640}})
    merged = cfg.merge(plot={"theme": "light"})
    assert merged.output.width == 640
    assert merged.plot.theme == "light"


def test_merge_validates_like_the_file_does():
    with pytest.raises(ConfigError, match="not one of"):
        ParityConfig().merge(plot={"theme": "neon"})
    with pytest.raises(ConfigError, match="unknown key"):
        ParityConfig().merge(plot={"nope": 1})
    with pytest.raises(ConfigError, match="unknown config section"):
        ParityConfig().merge(nope={"a": 1})


def test_empty_overrides_return_the_same_config():
    cfg = ParityConfig()
    assert cfg.merge(plot={}, data=None) is cfg


def test_missing_and_malformed_files_are_reported(tmp_path: Path):
    with pytest.raises(ConfigError, match="not found"):
        ParityConfig.from_toml(tmp_path / "nope.toml")

    bad = tmp_path / "bad.toml"
    bad.write_text("this is not = = toml", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        ParityConfig.from_toml(bad)
