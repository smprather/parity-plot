# parity_plot/designer/panels/section.py
"""The collapsible section wrapper every settings panel opens with.

Its only job is that the section headers -- Data, Tolerances, Encoding,
Appearance -- are styled in exactly one place. Quasar's expansion header is a
`q-item` whose default type scale is body text, which reads as another row of
settings rather than as the heading of a group; `header-class` lifts it without
touching the panel contents.
"""

from __future__ import annotations

from typing import Any

# Quasar applies these to the header row only, so the controls inside a section
# keep the default type scale.
HEADER_CLASS = "text-lg font-semibold"


def section(title: str, *, value: bool = True) -> Any:
    """A `ui.expansion` with the shared header styling, as a context manager."""
    from nicegui import ui

    return (
        ui.expansion(title, value=value)
        .classes("w-full")
        .props(f'header-class="{HEADER_CLASS}"')
    )
