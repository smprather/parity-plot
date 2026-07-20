# parity_plot/designer/inspector_helpers.py
"""Formatting a record for display. Pure, so it can be tested without a browser."""

from __future__ import annotations

from .records import RecordView


def describe(view: RecordView | None) -> list[tuple[str, str]]:
    """Label/value pairs describing one record."""
    if view is None:
        return [("", "Click a point to inspect it")]

    fields = [
        ("Record", view.key),
        ("Reference", _num(view.x)),
        ("Measured", _num(view.y)),
        ("Error", _signed(view.error)),
    ]
    if view.rel_error is not None:
        fields.append(("Relative error", _signed(view.rel_error * 100, suffix="%")))
    fields.append(("Status", view.status))
    if view.within is not None:
        fields.append(("Tolerance", "within" if view.within else "OUT"))
    return fields


def _num(value: float | None) -> str:
    return "missing" if value is None else f"{value:,.6g}"


def _signed(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:+,.6g}{suffix}"