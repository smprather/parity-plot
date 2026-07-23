"""Dark and light themes, registered as Plotly templates.

Each theme carries its own trace colors rather than relying on a colorway, so
the identity line and the rug marks stay legible against their own background
instead of landing wherever the palette cycle happens to put them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import plotly.graph_objects as go
import plotly.io as pio

# Tolerance colours are chosen to sit clearly apart from the three shades that
# already carry meaning here: `identity` (the y = x line), `marker` (the paired
# points) and `rug` (unpaired ticks). `green` and `blue` are offered, but as an
# olive and a true blue rather than the mint and cyan those reserved roles use.
COLOR_TOKENS = ("red", "yellow", "orange", "green", "blue", "purple", "magenta", "grey")

# Marker symbols are not theme data (a symbol is the same on light and dark), so
# the symbol cycle and catalog live in ``encoding`` alongside the rest of the
# marker-encoding logic. See ``encoding.DEFAULT_SYMBOLS`` / ``SYMBOL_CATALOG``.

# Qualitative colour tokens cycled for group colours. Reuse COLOR_TOKENS: they
# already resolve per theme and sit apart from the reserved identity/marker/rug
# shades (test_theme_colors.py guards that), so a group colour never impersonates
# another on-plot element.
GROUP_PALETTE: tuple[str, ...] = COLOR_TOKENS


@dataclass(frozen=True)
class Theme:
    name: str
    paper_bg: str
    plot_bg: str
    grid: str
    axis_line: str
    font: str
    font_muted: str
    marker: str
    marker_line: str
    identity: str
    rug: str
    tolerance: str
    band_fill: str
    box_bg: str
    box_border: str
    tolerance_colors: dict[str, str] = field(default_factory=dict)
    # Markers are translucent because at n=1000 an opaque cloud hides its own
    # density exactly where a parity plot is most interesting: near the line.
    marker_opacity: float = 0.65
    # pass/fail colours for the pass-fail marker channel. pass must be distinct
    # from `identity` (the y = x line) or a passing point would be lost in it.
    pass_color: str = ""
    fail_color: str = ""

    @property
    def template_name(self) -> str:
        return f"parity_{self.name}"

    def resolve_color(self, token: str) -> str:
        """A token, or a hex value passed through untouched."""
        if token.startswith("#"):
            return token
        try:
            return self.tolerance_colors[token]
        except KeyError:
            raise ValueError(
                f"unknown colour {token!r}; use one of {list(COLOR_TOKENS)} "
                f"or a hex value like '#8844ff'"
            ) from None

    def band_fill_for(self, token: str, alpha: float = 0.10) -> str:
        """The same colour, translucent, for a shaded band."""
        red, green, blue = _hex_to_rgb(self.resolve_color(token))
        return f"rgba({red}, {green}, {blue}, {alpha})"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    if len(text) == 3:  # short form, #abc
        text = "".join(character * 2 for character in text)
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


DARK = Theme(
    name="dark",
    paper_bg="#111418",
    plot_bg="#171b21",
    grid="#2a2f36",
    axis_line="#3a414a",
    font="#e6e6e6",
    font_muted="#9aa4b0",
    marker="#4cc9f0",
    marker_line="#1b6f8c",
    identity="#2fd48a",
    rug="#ffb703",
    tolerance="#ff4d5a",
    band_fill="rgba(255, 77, 90, 0.10)",
    box_bg="rgba(23, 27, 33, 0.85)",
    box_border="#3a414a",
    pass_color="#8aff80",
    fail_color="#ff4d5a",
    tolerance_colors={
        "red": "#ff4d5a",
        "yellow": "#ffd23f",
        "orange": "#ff8c42",
        "green": "#9ccc65",     # olive, not the identity line's mint
        "blue": "#5b8dee",      # true blue, not the markers' cyan
        "purple": "#b18cff",
        "magenta": "#ff6ec7",
        "grey": "#9aa4b0",
    },
)

LIGHT = Theme(
    name="light",
    paper_bg="#ffffff",
    plot_bg="#fbfbfd",
    grid="#e3e6ea",
    axis_line="#c2c8d0",
    font="#1a1a1a",
    font_muted="#5b6472",
    marker="#0077b6",
    marker_line="#004b73",
    identity="#0a8f4a",
    rug="#e07a00",
    tolerance="#d00000",
    band_fill="rgba(208, 0, 0, 0.08)",
    box_bg="rgba(255, 255, 255, 0.88)",
    box_border="#c2c8d0",
    pass_color="#2e8b57",
    fail_color="#d00000",
    tolerance_colors={
        "red": "#d00000",
        "yellow": "#b38600",
        "orange": "#b35309",
        "green": "#6a8f00",     # olive, not the identity line's emerald
        "blue": "#3b5bdb",      # true blue, not the markers' teal
        "purple": "#7048e8",
        "magenta": "#c2255c",
        "grey": "#6b7280",
    },
)

THEMES = {DARK.name: DARK, LIGHT.name: LIGHT}


def get(name: str) -> Theme:
    try:
        return THEMES[name]
    except KeyError:
        raise ValueError(
            f"unknown theme {name!r}; available themes are {sorted(THEMES)}"
        ) from None


def _template(theme: Theme) -> go.layout.Template:
    axis = dict(
        gridcolor=theme.grid,
        zerolinecolor=theme.grid,
        linecolor=theme.axis_line,
        tickcolor=theme.axis_line,
        tickfont=dict(color=theme.font_muted),
        title=dict(font=dict(color=theme.font)),
        showline=True,
        mirror=True,
        ticks="outside",
    )
    return go.layout.Template(
        layout=go.Layout(
            paper_bgcolor=theme.paper_bg,
            plot_bgcolor=theme.plot_bg,
            font=dict(color=theme.font, family="Inter, Segoe UI, Helvetica, sans-serif"),
            title=dict(font=dict(color=theme.font, size=20)),
            xaxis=axis,
            yaxis=axis,
            # Only the legend's styling lives here; where it sits is a per-plot
            # choice, applied in plot.py alongside the matching margins.
            legend=dict(
                bgcolor="rgba(0,0,0,0)",
                font=dict(color=theme.font_muted),
            ),
        )
    )


def register() -> None:
    """Install ``parity_dark`` / ``parity_light`` into Plotly's template registry."""
    for theme in THEMES.values():
        pio.templates[theme.template_name] = _template(theme)


register()
