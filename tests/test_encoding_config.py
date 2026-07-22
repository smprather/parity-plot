# tests/test_encoding_config.py
from __future__ import annotations

import pytest

from parity_plot.config import EXAMPLE_TOML, ConfigError, ParityConfig
from parity_plot.encoding import Encoding
from parity_plot import themes


def test_default_encoding_is_a_default_encoding():
    cfg = ParityConfig()
    assert cfg.plot.encoding == Encoding()


def test_encoding_table_parses_all_four_fields():
    cfg = ParityConfig.from_dict(
        {
            "plot": {
                "encoding": {
                    "color_by": "group",
                    "symbol_by": "pass-fail",
                    "color": "red",
                    "symbol": "diamond",
                }
            }
        }
    )
    enc = cfg.plot.encoding
    assert enc.color_by == "group"
    assert enc.symbol_by == "pass-fail"
    assert enc.color == "red"
    assert enc.symbol == "diamond"


def test_invalid_channel_value_raises_config_error():
    with pytest.raises(ConfigError):
        ParityConfig.from_dict(
            {"plot": {"encoding": {"color_by": "hue"}}}
        )


def test_symbol_sequence_parses_from_a_toml_list_into_a_tuple():
    cfg = ParityConfig.from_dict(
        {
            "plot": {
                "encoding": {
                    "color_by": "pass-fail",
                    "symbol_by": "group",
                    "symbol_sequence": ["circle", "square", "diamond"],
                }
            }
        }
    )
    assert cfg.plot.encoding.symbol_sequence == ("circle", "square", "diamond")


def test_unknown_symbol_in_sequence_raises_config_error():
    with pytest.raises(ConfigError, match="unknown symbol"):
        ParityConfig.from_dict(
            {"plot": {"encoding": {"symbol_sequence": ["crcle"]}}}
        )


def test_unknown_encoding_key_raises_config_error():
    with pytest.raises(ConfigError, match="unknown key"):
        ParityConfig.from_dict(
            {"plot": {"encoding": {"shape": "circle"}}}
        )


def test_merge_with_an_encoding_object_works():
    cfg = ParityConfig()
    enc = Encoding(color_by="pass-fail", symbol_by="pass-fail")
    merged = cfg.merge(plot={"encoding": enc})
    assert merged.plot.encoding is enc
    assert merged.plot.encoding.color_by == "pass-fail"


def test_example_toml_has_an_encoding_block():
    cfg = ParityConfig.from_dict(
        __import__("tomllib").loads(EXAMPLE_TOML)
    )
    assert cfg.plot.encoding == Encoding()


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_every_group_palette_token_resolves(theme_name):
    theme = themes.get(theme_name)
    for token in themes.GROUP_PALETTE:
        assert theme.resolve_color(token).startswith("#")


def test_symbol_cycle_has_at_least_six_entries():
    from parity_plot.encoding import DEFAULT_SYMBOLS

    assert len(DEFAULT_SYMBOLS) >= 6


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_pass_and_fail_colours_differ_from_identity(theme_name):
    theme = themes.get(theme_name)
    assert theme.pass_color.lower() != theme.identity.lower()
    assert theme.fail_color.lower() != theme.identity.lower()