"""Synthetic example data.

Produces a dataset that exercises every path in the tool: gaussian disparity,
a real bias, outliers, and records missing from each side. Seeded, so the same
spec always yields the same numbers.

Every knob is on :class:`ExampleSpec`, so the shape of the data can be dialled
from the CLI -- turn the noise up to watch the tolerance band empty out, or the
bias down to see the cloud settle onto the identity line.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass, replace
from pathlib import Path

# Draws land inside [x_min, x_max] this often; the rest form the long tail.
_CENTRAL_MASS_Z = 1.96


class SpecError(ValueError):
    """Raised when the requested example data is not physically possible."""


@dataclass(frozen=True)
class ExampleSpec:
    """How the synthetic dataset should be shaped.

    ``bias``, ``noise`` and ``outlier_rate`` are fractions rather than
    percentages, matching ``--tolerance`` on the plot command.
    """

    n: int = 1000
    seed: int = 17

    # Reference values are log-normal: a dense low cluster with a long tail,
    # which is what measurement data tends to look like. The bounds describe
    # the central 95% of draws, not hard limits.
    x_min: float = 10.0
    x_max: float = 100.0

    # A deliberate positive slope bias, so `bias` and the tolerance band have
    # something real to report -- data centred perfectly on y = x makes the
    # tool look like it isn't measuring anything.
    bias: float = 0.015
    # Scatter proportional to the value, then a floor that dominates near zero.
    noise: float = 0.06
    noise_floor: float = 0.4
    outlier_rate: float = 0.01
    outlier_scale: float = 9.0

    # Null counts default to a fraction of n rather than a fixed number, so
    # `generate(n=10)` works instead of failing on defaults meant for n=1000.
    # At the default size these still resolve to 15 / 12 / 2.
    n_missing_y: int | None = None
    n_missing_x: int | None = None
    n_both_null: int | None = None

    _MISSING_Y_SHARE = 0.015
    _MISSING_X_SHARE = 0.012
    _BOTH_NULL_SHARE = 0.002

    def __post_init__(self) -> None:
        if self.n < 1:
            raise SpecError(f"need at least one record, got n={self.n}")

        # Resolve the proportional defaults, leaving explicit counts alone.
        # After construction these fields are always plain ints.
        for name, share in (
            ("n_missing_y", self._MISSING_Y_SHARE),
            ("n_missing_x", self._MISSING_X_SHARE),
            ("n_both_null", self._BOTH_NULL_SHARE),
        ):
            if getattr(self, name) is None:
                object.__setattr__(self, name, round(self.n * share))

        if self.x_min <= 0:
            raise SpecError(f"x_min must be positive, got {self.x_min}")
        if self.x_max <= self.x_min:
            raise SpecError(
                f"x_max ({self.x_max}) must be greater than x_min ({self.x_min})"
            )
        for name in ("noise", "noise_floor", "outlier_scale"):
            if getattr(self, name) < 0:
                raise SpecError(f"{name} cannot be negative, got {getattr(self, name)}")
        if not 0.0 <= self.outlier_rate <= 1.0:
            raise SpecError(
                f"outlier_rate is a fraction between 0 and 1, got {self.outlier_rate}"
            )
        for name in ("n_missing_x", "n_missing_y", "n_both_null"):
            if getattr(self, name) < 0:
                raise SpecError(f"{name} cannot be negative, got {getattr(self, name)}")
        if self.n_nulls > self.n:
            raise SpecError(
                f"requested {self.n_nulls} null records but only {self.n} records "
                f"exist; lower --missing-x/--missing-y/--both-null or raise -n"
            )

    @property
    def n_nulls(self) -> int:
        return self.n_missing_x + self.n_missing_y + self.n_both_null

    @property
    def log_mu(self) -> float:
        """Log-space mean placing the median midway between the bounds."""
        return (math.log(self.x_min) + math.log(self.x_max)) / 2

    @property
    def log_sigma(self) -> float:
        """Log-space spread putting ~95% of draws inside the bounds."""
        return (math.log(self.x_max) - math.log(self.x_min)) / (2 * _CENTRAL_MASS_Z)


@dataclass(frozen=True)
class Record:
    key: str
    reference: float | None
    measured: float | None


def generate(spec: ExampleSpec | None = None, **overrides) -> list[Record]:
    """Build records with gaussian disparity and some unpaired holes.

    Accepts either a prepared :class:`ExampleSpec` or its fields as keywords::

        generate(n=500, noise=0.2, bias=0.0)
    """
    spec = _resolve(spec, overrides)
    rng = random.Random(spec.seed)

    records = []
    for i in range(spec.n):
        x = math.exp(rng.gauss(spec.log_mu, spec.log_sigma))
        y = x * (1 + spec.bias + rng.gauss(0, spec.noise))
        y += rng.gauss(0, spec.noise_floor)
        if spec.outlier_rate and rng.random() < spec.outlier_rate:
            y += rng.choice((-1, 1)) * spec.outlier_scale * spec.noise * x
        records.append(Record(key=f"S{i:04d}", reference=x, measured=y))

    # Carve the null records out of disjoint index sets so each case is
    # reachable independently.
    holes = rng.sample(range(spec.n), spec.n_nulls)
    drop_y = holes[: spec.n_missing_y]
    drop_x = holes[spec.n_missing_y : spec.n_missing_y + spec.n_missing_x]
    drop_both = holes[spec.n_missing_y + spec.n_missing_x :]

    for i in drop_y:
        records[i] = Record(records[i].key, records[i].reference, None)
    for i in drop_x:
        records[i] = Record(records[i].key, None, records[i].measured)
    for i in drop_both:
        records[i] = Record(records[i].key, None, None)

    return records


def _resolve(spec: ExampleSpec | None, overrides: dict) -> ExampleSpec:
    """Apply keyword overrides, ignoring the ``None``s a CLI passes for unset flags."""
    applied = {k: v for k, v in overrides.items() if v is not None}
    unknown = set(applied) - set(ExampleSpec.__dataclass_fields__)
    if unknown:
        raise SpecError(f"unknown example option(s): {sorted(unknown)}")

    # Built from scratch rather than by replacing fields on a default spec:
    # a default spec has already resolved its null counts against n=1000, and
    # replacing n alone would carry those counts onto a much smaller dataset.
    if spec is None:
        return ExampleSpec(**applied)
    return replace(spec, **applied) if applied else spec


def write_wide(records: list[Record], path: str | Path) -> Path:
    """Write one file with both columns; a null is an empty cell."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["id", "reference", "measured"])
        for rec in records:
            writer.writerow([rec.key, _fmt(rec.reference), _fmt(rec.measured)])
    return path


def write_pair(
    records: list[Record], x_path: str | Path, y_path: str | Path
) -> tuple[Path, Path]:
    """Write one file per dataset; a null is an *absent row*.

    This is the distinction join mode exists for: the record simply was never
    measured on that side, so there is no row for it at all.
    """
    x_path, y_path = Path(x_path), Path(y_path)
    for path, attr in ((x_path, "reference"), (y_path, "measured")):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(["id", "value"])
            for rec in records:
                value = getattr(rec, attr)
                if value is not None:
                    writer.writerow([rec.key, _fmt(value)])
    return x_path, y_path


def write_all(
    out_dir: str | Path = "data", spec: ExampleSpec | None = None, **overrides
) -> dict[str, Path]:
    """Generate once and write both input shapes from the same draws.

    Both loader paths then have example data that must agree, which is what
    makes the wide-vs-join comparison a real end-to-end check.
    """
    out_dir = Path(out_dir)
    records = generate(spec, **overrides)
    wide = write_wide(records, out_dir / "example.csv")
    reference, measured = write_pair(
        records, out_dir / "reference.csv", out_dir / "measured.csv"
    )
    return {"wide": wide, "reference": reference, "measured": measured}


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"
