"""Cross-field config validation for the designer.

Rules here are constraints that span sections and so cannot live on a single
config dataclass (each validates only itself). Browser-free and pure: rules read
the resolved config and never open files. `app.py` surfaces the result.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ParityConfig

__all__ = ["Problem", "problems"]


@dataclass(frozen=True)
class Problem:
    """One validation finding.

    ``field`` is a dotted id (e.g. ``"data.join"``) so the owning panel can mark
    the exact widget. ``severity`` is ``"error"`` (blocking: withholds auto-save,
    disables Save As, reddens the field) or ``"warning"`` (advisory: an amber
    note only, nothing blocked)."""

    message: str
    field: str
    severity: str = "error"


def _ref_file(ref: str | None) -> str | None:
    """The file part of a ``file:column`` ref, or None."""
    if not ref or ":" not in ref:
        return None
    return ref.split(":", 1)[0]


def problems(config: ParityConfig) -> list[Problem]:
    """Every cross-field problem in ``config``, in a stable order."""
    found: list[Problem] = []
    data = config.data

    # Redundant, not wrong: ref and test on the same row already pair by order,
    # so a join re-pairs the same rows to the same result. It even adds
    # duplicate-key checking. So this is advisory, never blocking.
    ref_file, test_file = _ref_file(data.ref), _ref_file(data.test)
    if data.join and ref_file is not None and ref_file == test_file:
        found.append(
            Problem(
                message=(
                    f"redundant join: ref and test are both from {ref_file}, so they "
                    f"already pair by row order; a join here only adds duplicate-key "
                    f"checking"
                ),
                field="data.join",
                severity="warning",
            )
        )

    return found