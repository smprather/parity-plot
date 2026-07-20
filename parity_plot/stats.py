"""Agreement statistics for a parity plot.

Computed over paired records only -- an unpaired record has no difference to
measure, so folding it in would be meaningless. Its count is carried alongside
instead, since "how much data couldn't be compared" is itself a result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .data import ParityData
from .tolerances import NamedTolerance, pass_fail

METRIC_LABELS = {
    "n": "n",
    "r2": "R² (identity)",
    "pearson_r": "Pearson r",
    "rmse": "RMSE",
    "mae": "MAE",
    "bias": "bias",
    "max_abs_err": "max |err|",
}


@dataclass(frozen=True)
class Stats:
    n_paired: int = 0
    n_missing_x: int = 0
    n_missing_y: int = 0
    n_dropped: int = 0
    r2: float | None = None
    pearson_r: float | None = None
    rmse: float | None = None
    mae: float | None = None
    bias: float | None = None
    max_abs_err: float | None = None
    # Fraction of paired points inside each pass/fail tolerance envelope,
    # keyed by tolerance name. Informational entries are references, not
    # criteria -- reporting a "within" share for one would imply it was a
    # pass/fail threshold, so they are deliberately absent.
    within: dict[str, float] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return self.n_paired


def compute(
    data: ParityData, tolerances: Sequence[NamedTolerance] = ()
) -> Stats:
    """Summarise how well the two datasets agree.

    ``r2`` is measured about the identity line, not about a least-squares fit.
    That distinction is the whole point of a parity plot: data sitting on a
    tight line parallel to ``y = x`` has an excellent best-fit R² while
    agreeing with nothing, and only the identity-line form exposes that.
    """
    x, y = data.x, data.y
    counts = {
        "n_paired": len(x),
        "n_missing_x": len(data.missing_x),
        "n_missing_y": len(data.missing_y),
        "n_dropped": data.n_dropped,
    }
    if len(x) < 2:
        return Stats(**counts)

    residuals = [yi - xi for xi, yi in zip(x, y)]
    n = len(residuals)
    ss_res = sum(r * r for r in residuals)
    y_mean = sum(y) / n
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)

    return Stats(
        **counts,
        r2=None if ss_tot == 0 else 1.0 - ss_res / ss_tot,
        pearson_r=_pearson(x, y),
        rmse=math.sqrt(ss_res / n),
        mae=sum(abs(r) for r in residuals) / n,
        bias=sum(residuals) / n,
        max_abs_err=max(abs(r) for r in residuals),
        within={
            tol.name: _within(x, y, tol) for tol in pass_fail(tolerances)
        },
    )


def _pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    n = len(x)
    x_mean, y_mean = sum(x) / n, sum(y) / n
    dx = [xi - x_mean for xi in x]
    dy = [yi - y_mean for yi in y]
    denom = math.sqrt(sum(d * d for d in dx) * sum(d * d for d in dy))
    if denom == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denom


def _within(x: Sequence[float], y: Sequence[float], tol: NamedTolerance) -> float:
    """Fraction of paired points inside the tolerance envelope."""
    return sum(1 for xi, yi in zip(x, y) if tol.contains(xi, yi)) / len(x)


def format_lines(stats: Stats, metrics: Sequence[str]) -> list[str]:
    """Render selected metrics as ``label: value`` strings for the plot box."""
    lines = []
    for name in metrics:
        if name not in METRIC_LABELS:
            continue
        value = getattr(stats, name)
        lines.append(f"{METRIC_LABELS[name]}: {_fmt(value)}")
    for name, share in stats.within.items():
        lines.append(f"within {name}: {share:.1%}")
    return lines


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    if value != 0 and abs(value) < 1e-3:
        return f"{value:.2e}"
    return f"{value:,.4g}"


def summarize_nulls(stats: Stats, x_label: str, y_label: str) -> str:
    """One-line account of what could not be paired, for the plot subtitle."""
    parts = [f"{stats.n_paired:,} paired"]
    if stats.n_missing_y:
        parts.append(f"{stats.n_missing_y:,} missing {y_label}")
    if stats.n_missing_x:
        parts.append(f"{stats.n_missing_x:,} missing {x_label}")
    if stats.n_dropped:
        parts.append(f"{stats.n_dropped:,} with neither")
    return " · ".join(parts)
