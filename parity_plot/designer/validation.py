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
    """One validation failure. ``field`` is a dotted id (e.g. ``"data.join"``)
    so the owning panel can mark the exact widget."""

    message: str
    field: str


def _ref_file(ref: str | None) -> str | None:
    """The file part of a ``file:column`` ref, or None."""
    if not ref or ":" not in ref:
        return None
    return ref.split(":", 1)[0]


def problems(config: ParityConfig) -> list[Problem]:
    """Every cross-field problem in ``config``, in a stable order."""
    found: list[Problem] = []
    data = config.data

    ref_file, test_file = _ref_file(data.ref), _ref_file(data.test)
    if data.join and ref_file is not None and ref_file == test_file:
        found.append(
            Problem(
                message=(
                    f"ref and test are both from {ref_file}; a join is meaningless "
                    f"there — clear the join to pair by row order, or point ref/test "
                    f"at different files"
                ),
                field="data.join",
            )
        )

    return found