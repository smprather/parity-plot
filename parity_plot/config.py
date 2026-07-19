"""Configuration: dataclass defaults, TOML loading, and CLI override merging.

Precedence is CLI flag > TOML value > dataclass default. Unknown TOML keys raise
rather than being ignored, since a misspelled key would otherwise silently render
the default and look like a bug in the plot.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from .tolerance import parse_reltol

DEFAULT_NA_VALUES: tuple[str, ...] = (
    "",
    "NA",
    "N/A",
    "null",
    "none",
    "nan",
    "-",
)

THEMES = ("dark", "light")
NULL_MODES = ("rug", "drop")
OUTPUT_FORMATS = ("html", "png", "svg", "pdf")
# "top" is deliberately absent: the title carries a subtitle, and a legend
# above the axes lands on top of it.
LEGEND_POSITIONS = ("right", "bottom", "none")
BAND_STYLES = ("lines", "shaded")


class ConfigError(ValueError):
    """Raised for malformed or invalid configuration."""


@dataclass(frozen=True)
class DataConfig:
    """Where the numbers come from.

    One path is wide mode (a single file with both value columns); two paths is
    join mode (one file per dataset, outer-joined on ``key``).
    """

    paths: tuple[Path, ...] = ()
    x: str = "reference"
    y: str = "measured"
    key: str | None = "id"
    value: str = "value"
    na_values: tuple[str, ...] = DEFAULT_NA_VALUES


@dataclass(frozen=True)
class PlotConfig:
    title: str = "Parity Plot"
    x_label: str | None = None
    y_label: str | None = None
    theme: str = "dark"
    log: bool = False
    equal_axes: bool = True
    identity_line: bool = True
    # Tolerances carry units. `abstol` is in the data's own units and draws
    # lines parallel to y = x; `reltol` is a dimensionless ratio and draws a
    # wedge through the origin. Given both, the envelope is the looser of the
    # two at each point, which flares from parallel into a funnel.
    abstol: float | None = None
    reltol: float | None = None
    band_style: str = "lines"
    nulls: str = "rug"
    legend: str = "right"


@dataclass(frozen=True)
class StatsConfig:
    show: bool = True
    metrics: tuple[str, ...] = ("n", "r2", "rmse", "mae", "bias")


@dataclass(frozen=True)
class OutputConfig:
    path: Path = Path("parity.html")
    format: str = "html"
    width: int = 900
    height: int = 900


@dataclass(frozen=True)
class ParityConfig:
    data: DataConfig = DataConfig()
    plot: PlotConfig = PlotConfig()
    stats: StatsConfig = StatsConfig()
    output: OutputConfig = OutputConfig()

    @classmethod
    def from_toml(cls, path: str | Path) -> ParityConfig:
        path = Path(path)
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ConfigError(f"config file not found: {path}") from None
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: invalid TOML: {exc}") from None
        return cls.from_dict(raw, source=str(path))

    @classmethod
    def from_dict(cls, raw: dict[str, Any], source: str = "config") -> ParityConfig:
        sections = {f.name: f.type for f in fields(cls)}
        unknown = set(raw) - set(sections)
        if unknown:
            raise ConfigError(
                f"{source}: unknown section(s) {sorted(unknown)}; "
                f"valid sections are {sorted(sections)}"
            )
        return cls(
            data=_build(DataConfig, raw.get("data", {}), f"{source} [data]"),
            plot=_build(PlotConfig, raw.get("plot", {}), f"{source} [plot]"),
            stats=_build(StatsConfig, raw.get("stats", {}), f"{source} [stats]"),
            output=_build(OutputConfig, raw.get("output", {}), f"{source} [output]"),
        )

    def merge(self, **sections: dict[str, Any] | None) -> ParityConfig:
        """Return a copy with the given per-section overrides applied.

        Values that are ``None`` are dropped, so a CLI can pass every flag
        unconditionally and only the ones the user actually set take effect.
        """
        unknown = set(sections) - {f.name for f in fields(self)}
        if unknown:
            raise ConfigError(f"unknown config section(s): {sorted(unknown)}")

        updated: dict[str, Any] = {}
        for name, overrides in sections.items():
            if not overrides:
                continue
            current = getattr(self, name)
            applied = {k: v for k, v in overrides.items() if v is not None}
            if applied:
                updated[name] = _build(
                    type(current),
                    applied,
                    f"override [{name}]",
                    base=current,
                )
        return replace(self, **updated) if updated else self


def _build(cls: type, raw: dict[str, Any], source: str, base: Any = None) -> Any:
    """Validate and coerce ``raw`` into an instance of ``cls``.

    ``base`` supplies the starting values when applying a partial override;
    without it the dataclass defaults are used.
    """
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(
            f"{source}: unknown key(s) {sorted(unknown)}; "
            f"valid keys are {sorted(known)}"
        )
    coerced = {k: _coerce(cls, k, v, source) for k, v in raw.items()}
    return replace(base, **coerced) if base is not None else cls(**coerced)


_TUPLE_OF_PATH = {"paths"}
_TUPLE_OF_STR = {"na_values", "metrics"}
_PATH = {"path"}
_POSITIVE_FLOAT = {"abstol"}
_RELTOL = {"reltol"}
_CHOICES = {
    "theme": THEMES,
    "nulls": NULL_MODES,
    "format": OUTPUT_FORMATS,
    "legend": LEGEND_POSITIONS,
    "band_style": BAND_STYLES,
}


def _coerce(cls: type, key: str, value: Any, source: str) -> Any:
    where = f"{source}: '{key}'"

    if key in _TUPLE_OF_PATH:
        return tuple(Path(p) for p in _as_sequence(value, where))
    if key in _TUPLE_OF_STR:
        return tuple(str(v) for v in _as_sequence(value, where))
    if key in _POSITIVE_FLOAT:
        number = float(value)
        if number <= 0:
            raise ConfigError(f"{where}: must be positive, got {number}")
        return number
    if key in _RELTOL:
        # A ratio by default; "10pct" states the percentage explicitly.
        try:
            number = parse_reltol(value)
        except ValueError as exc:
            raise ConfigError(f"{where}: {exc}") from None
        if number <= 0:
            raise ConfigError(f"{where}: must be positive, got {number}")
        return number
    if key in _PATH:
        return Path(value)
    if key in _CHOICES:
        if value not in _CHOICES[key]:
            raise ConfigError(
                f"{where}: {value!r} is not one of {list(_CHOICES[key])}"
            )
        return value
    if key in {"width", "height"}:
        size = int(value)
        if size <= 0:
            raise ConfigError(f"{where}: must be positive, got {size}")
        return size
    if key in {"log", "equal_axes", "identity_line", "show"}:
        if not isinstance(value, bool):
            raise ConfigError(f"{where}: expected true or false, got {value!r}")
        return value
    return value


def _as_sequence(value: Any, where: str) -> list[Any]:
    if isinstance(value, str) or not hasattr(value, "__iter__"):
        raise ConfigError(f"{where}: expected a list, got {value!r}")
    return list(value)


EXAMPLE_TOML = """\
# parity-plot configuration
# Every key here can also be overridden by the matching CLI flag.

[data]
# One path = wide mode (both value columns in one file).
# Two paths = join mode (one file per dataset, outer-joined on `key`).
paths = ["data/example.csv"]
x = "reference"
y = "measured"
key = "id"
# In join mode, the value column to read from each file.
value = "value"
na_values = ["", "NA", "N/A", "null", "none", "nan", "-"]

[plot]
title = "Parity Plot"
# x_label / y_label default to the column (or file) names.
theme = "dark"          # dark | light
log = false
equal_axes = true
identity_line = true
# Tolerances carry units. Give either, or both for a funnel.
# abstol is in the data's own units and draws lines parallel to y = x.
# reltol_pct is a percentage and draws a wedge through the origin.
# With both, the envelope is the looser of the two at each point.
# abstol = 2.0
reltol = 0.10           # a ratio; write "10pct" if you prefer percent
band_style = "lines"    # lines | shaded
nulls = "rug"           # rug | drop
legend = "right"        # right | bottom | none

[stats]
show = true
metrics = ["n", "r2", "rmse", "mae", "bias"]

[output]
path = "parity.html"
format = "html"         # html | png | svg | pdf (non-html needs parity-plot[static])
width = 900
height = 900
"""
