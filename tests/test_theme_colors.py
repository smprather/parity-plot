# tests/test_theme_colors.py
from __future__ import annotations

import pytest

from parity_plot import themes

RESERVED = {
    "identity": "the y = x line",
    "marker": "the paired points",
    "rug": "unpaired record ticks",
}


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_every_token_resolves_in_every_theme(theme_name):
    theme = themes.get(theme_name)
    for token in themes.COLOR_TOKENS:
        assert theme.resolve_color(token).startswith("#")


def test_the_offered_tokens_are_the_curated_set():
    assert themes.COLOR_TOKENS == (
        "red", "yellow", "orange", "green", "blue", "purple", "magenta", "grey",
    )


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_no_token_duplicates_a_reserved_colour(theme_name):
    """green is the identity line, blue is the markers, amber is the rug. A
    tolerance drawn in exactly one of those shades would impersonate it."""
    theme = themes.get(theme_name)
    reserved = {theme.identity.lower(), theme.marker.lower(), theme.rug.lower()}
    for token in themes.COLOR_TOKENS:
        assert theme.resolve_color(token).lower() not in reserved


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_tokens_are_distinct_from_each_other(theme_name):
    theme = themes.get(theme_name)
    shades = [theme.resolve_color(t).lower() for t in themes.COLOR_TOKENS]
    assert len(set(shades)) == len(shades)


def test_dark_and_light_use_different_shades():
    """A colour tuned for a dark background is wrong on a light one."""
    dark, light = themes.get("dark"), themes.get("light")
    assert dark.resolve_color("red") != light.resolve_color("red")


def test_a_hex_value_passes_through_untouched():
    """The escape hatch: anything starting # is used verbatim."""
    theme = themes.get("dark")
    assert theme.resolve_color("#8844ff") == "#8844ff"
    assert theme.resolve_color("#ABC") == "#ABC"


def test_an_unknown_token_is_rejected_with_the_valid_list():
    theme = themes.get("dark")
    with pytest.raises(ValueError) as exc:
        theme.resolve_color("chartreuse")
    assert "chartreuse" in str(exc.value)
    assert "red" in str(exc.value)


def test_band_fill_is_the_same_hue_made_translucent():
    theme = themes.get("dark")
    fill = theme.band_fill_for("red")
    assert fill.startswith("rgba(")
    assert fill.endswith("0.1)")


def test_band_fill_works_for_a_hex_escape_hatch():
    assert themes.get("dark").band_fill_for("#8844ff").startswith("rgba(136, 68, 255")


def test_band_fill_alpha_is_adjustable():
    assert themes.get("dark").band_fill_for("red", alpha=0.5).endswith("0.5)")