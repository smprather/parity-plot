"""Dark and light themes, registered as Plotly templates.

Each theme carries its own trace colors rather than relying on a colorway, so
the identity line and the rug marks stay legible against their own background
instead of landing wherever the palette cycle happens to put them.
"""

from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go
import plotly.io as pio


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
    # Markers are translucent because at n=1000 an opaque cloud hides its own
    # density exactly where a parity plot is most interesting: near the line.
    marker_opacity: float = 0.65

    @property
    def template_name(self) -> str:
        return f"parity_{self.name}"


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
