"""Configuration: dataclass defaults, TOML loading, and CLI override merging.

Precedence is CLI flag > TOML value > dataclass default. Unknown TOML keys raise
rather than being ignored, since a misspelled key would otherwise silently render
the default and look like a bug in the plot.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from .tolerance import parse_reltol
from .tolerances import (
    NamedTolerance,
    ToleranceError,
    default_name,
    parity,
    require_unique_names,
    with_parity,
)
from .encoding import Encoding, EncodingError

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

    An arbitrary set of files; the two plotted series are `file:column` refs.
    A join column aligns rows across files; without one, rows pair by order.
    """

    files: tuple[Path, ...] = ()
    ref: str | None = None       # "file:column", a numeric column
    test: str | None = None      # "file:column", a numeric column
    join: str | None = None      # column name in both files, or None -> pair by order
    group: str | None = None     # "file:column", any column, or None
    na_values: tuple[str, ...] = DEFAULT_NA_VALUES


@dataclass(frozen=True)
class PlotConfig:
    title: str = "Parity Plot"
    x_label: str | None = None
    y_label: str | None = None
    theme: str = "dark"
    log: bool = False
    equal_axes: bool = True
    # A plot may carry several specifications at once. Order is meaningful: it
    # drives legend order and the order names appear in a failure list. Parity
    # (the y = x line) is guaranteed first; disabling it replaces the old
    # identity_line = false.
    tolerances: tuple[NamedTolerance, ...] = field(default_factory=lambda: (parity(),))
    nulls: str = "rug"
    legend: str = "right"
    # How marker colour/symbol are driven from the data (single | pass-fail |
    # group). Default is the behaviour-preserving one-trace plot.
    encoding: Encoding = field(default_factory=Encoding)


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
    # default_factory, not a shared instance: a bare `PlotConfig()` default is
    # one object shared by every ParityConfig ever built. That is safe only
    # while nothing writes to it, and anything that forces a value past frozen
    # (tests do) then corrupts the default for the whole process.
    data: DataConfig = field(default_factory=DataConfig)
    plot: PlotConfig = field(default_factory=PlotConfig)
    stats: StatsConfig = field(default_factory=StatsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

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
    if cls is PlotConfig:
        retired = [key for key in RETIRED_PLOT_KEYS if key in raw]
        if retired:
            raise ConfigError(
                f"{source}: {', '.join(retired)} moved into a tolerance list in 0.2.0. "
                f"Replace with:\n"
                f"  [[plot.tolerances]]\n"
                f'  name = "tolerance1"\n'
                f"  abstol = 2.0        # and/or reltol\n"
                f'  kind = "pass"       # pass | info\n'
                f"  enabled = false     # replaces identity_line for the parity entry\n"
            )
    if cls is DataConfig:
        retired = [k for k in RETIRED_DATA_KEYS if k in raw]
        if retired:
            raise ConfigError(
                f"{source}: {', '.join(retired)} were replaced in 0.3.0. Use:\n"
                f"  [data]\n"
                f'  files = ["meas.csv", "sim.csv"]\n'
                f'  ref   = "meas.csv:voltage"    # file:column\n'
                f'  test  = "sim.csv:voltage"\n'
                f'  join  = "id"                  # optional; omit to pair by order\n'
            )
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(
            f"{source}: unknown key(s) {sorted(unknown)}; "
            f"valid keys are {sorted(known)}"
        )
    coerced = {k: _coerce(cls, k, v, source) for k, v in raw.items()}
    return replace(base, **coerced) if base is not None else cls(**coerced)


_TUPLE_OF_PATH = {"files"}
_TUPLE_OF_STR = {"na_values", "metrics"}
_PATH = {"path"}
_POSITIVE_FLOAT: set[str] = set()
_RELTOL = {"reltol"}
_CHOICES = {
    "theme": THEMES,
    "nulls": NULL_MODES,
    "format": OUTPUT_FORMATS,
    "legend": LEGEND_POSITIONS,
}

RETIRED_PLOT_KEYS = ("abstol", "reltol", "band_style", "identity_line")
RETIRED_DATA_KEYS = ("paths", "x", "y", "key", "value")


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
    if key == "tolerances":
        return _coerce_tolerances(value, where)
    if key == "encoding":
        return _coerce_encoding(value, where)
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
    if key in {"log", "equal_axes", "show"}:
        if not isinstance(value, bool):
            raise ConfigError(f"{where}: expected true or false, got {value!r}")
        return value
    return value


def _as_sequence(value: Any, where: str) -> list[Any]:
    if isinstance(value, str) or not hasattr(value, "__iter__"):
        raise ConfigError(f"{where}: expected a list, got {value!r}")
    return list(value)


def _coerce_tolerances(value: Any, where: str) -> tuple[NamedTolerance, ...]:
    """Build the tolerance list from TOML tables or ready-made objects.

    The designer hands over NamedTolerance instances directly; TOML hands over
    dicts. Both arrive here so validation happens in exactly one place.
    """
    if isinstance(value, NamedTolerance):
        value = [value]
    if isinstance(value, str) or not hasattr(value, "__iter__"):
        raise ConfigError(f"{where}: expected a list of tolerance tables")

    built: list[NamedTolerance] = []
    known = set(NamedTolerance.__dataclass_fields__)
    for index, entry in enumerate(value, start=1):
        if isinstance(entry, NamedTolerance):
            built.append(entry)
            continue
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}[{index}]: expected a table, got {entry!r}")

        unknown = set(entry) - known
        if unknown:
            raise ConfigError(
                f"{where}[{index}]: unknown key(s) {sorted(unknown)}; "
                f"valid keys are {sorted(known)}"
            )
        fields = dict(entry)
        if "reltol" in fields and fields["reltol"] is not None:
            try:
                fields["reltol"] = parse_reltol(fields["reltol"])
            except ValueError as exc:
                raise ConfigError(f"{where}[{index}]: {exc}") from None
        # A builtin entry is forced to "info"; the dataclass default is "pass",
        # so a TOML table that only sets ``builtin = true`` needs kind injected
        # rather than failing the post-init check.
        if fields.get("builtin") and "kind" not in fields:
            fields["kind"] = "info"
        if "name" not in fields:
            fields["name"] = default_name([t.name for t in built])
        try:
            built.append(NamedTolerance(**fields))
        except ToleranceError as exc:
            raise ConfigError(f"{where}[{index}]: {exc}") from None

    try:
        require_unique_names(built)
    except ToleranceError as exc:
        raise ConfigError(f"{where}: {exc}") from None
    return with_parity(tuple(built))


def _coerce_encoding(value: Any, where: str) -> Encoding:
    """Build an :class:`Encoding` from a TOML table or a ready-made object.

    The designer hands over an ``Encoding`` directly; TOML hands over a dict.
    Both arrive here so validation happens in exactly one place.
    """
    if isinstance(value, Encoding):
        return value
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected a table, got {value!r}")
    known = set(Encoding.__dataclass_fields__)
    unknown = set(value) - known
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {sorted(unknown)}; "
            f"valid keys are {sorted(known)}"
        )
    try:
        return Encoding(**value)
    except EncodingError as exc:
        raise ConfigError(f"{where}: {exc}") from None


def _register_tomlkit_encoding_encoder() -> None:
    """Teach tomlkit to render an :class:`Encoding` as a `[plot.encoding]` table.

    The designer's serializer (``designer/serialize.py``) walks ``PlotConfig``
    fields and hands each value to tomlkit; without an encoder for the new
    ``encoding`` field, tomlkit raises ``ConvertError`` on the frozen dataclass.
    Registering here keeps the encoder alongside the type it knows about, and
    runs once at import so the designer (which imports this module) picks it up.
    """
    from tomlkit.items import CUSTOM_ENCODERS, Table, Trivia
    from tomlkit.container import Container

    def _encode_encoding(value: object, **_: object) -> Table:
        if not isinstance(value, Encoding):
            raise TypeError
        table = Table(Container(), Trivia(), False)
        table["color_by"] = value.color_by
        table["symbol_by"] = value.symbol_by
        table["color"] = value.color
        table["symbol"] = value.symbol
        # Only emit a symbol_sequence when set, so an unused default does not
        # litter every config with `symbol_sequence = []`.
        if value.symbol_sequence:
            table["symbol_sequence"] = list(value.symbol_sequence)
        return table

    if not any(
        getattr(enc, "__name__", None) == "_encode_encoding"
        for enc in CUSTOM_ENCODERS
    ):
        CUSTOM_ENCODERS.append(_encode_encoding)


_register_tomlkit_encoding_encoder()


EXAMPLE_TOML = """\
# parity-plot configuration
# Every key here can also be overridden by the matching CLI flag.

[data]
# An arbitrary set of CSV files; the two plotted series are `file:column` refs.
# A join column aligns rows across files; omit it to pair rows by order.
files = ["data/example.csv"]
ref = "data/example.csv:reference"    # file:column, a numeric column
test = "data/example.csv:measured"    # file:column, a numeric column
# join = "id"                         # optional; column name in both files
# group = "data/example.csv:batch"    # optional; any column, or file:column
na_values = ["", "NA", "N/A", "null", "none", "nan", "-"]

[plot]
title = "Parity Plot"
# x_label / y_label default to the column (or file) names.
theme = "dark"          # dark | light
log = false
equal_axes = true
nulls = "rug"           # rug | drop
legend = "right"        # right | bottom | none

# A plot may carry several specifications at once. Each is one
# [[plot.tolerances]] table; order drives legend order and the order
# names appear in a failure list.
#   name           identifier (no whitespace); appears in the failure list
#   abstol         absolute tolerance, in the data's own units (lines parallel to y = x)
#   reltol         relative tolerance, a ratio or "10pct" for percent (wedge through origin)
#   kind           "pass" (graded) | "info" (drawn for reference, never judged)
#   color          a token (red, yellow, ...) or a hex value; defaulted by kind
#   style          "lines" | "shaded"
#   label          legend text; defaults to the spec ("±10%", "±max(2, 10%)")
#   enabled        false hides the entry without deleting it
#   show_in_legend false keeps the entry drawn but out of the legend
#   builtin        true for the built-in parity line (no bounds; forced "info")
# The built-in y = x line is added automatically; to disable it:
#   [[plot.tolerances]]
#   name = "parity"
#   builtin = true
#   enabled = false
[[plot.tolerances]]
name = "spec"
reltol = 0.10           # a ratio; write "10pct" if you prefer percent

# Marker colour and symbol can each be driven from the data:
#   color_by   = "single"     # one colour for all points (see `color` below)
#              | "pass-fail"  # overall verdict: pass → green, fail → red
#              | "group"      # the point's group column → a qualitative palette
#   symbol_by  = "single"     # one symbol for all points (see `symbol` below)
#              | "pass-fail"  # pass → circle, fail → x
#              | "group"      # the group column → a symbol cycle
#   color      = "blue"       # token or hex; used when color_by = "single"
#   symbol     = "circle"     # Plotly symbol name; used when symbol_by = "single"
#   symbol_sequence = [...]   # symbols the groups cycle through when
#                             # symbol_by = "group"; empty = a built-in default.
#                             # e.g. colour by pass/fail, shape by group:
#                             #   color_by = "pass-fail", symbol_by = "group"
# The default reproduces today's one-trace plot, so nothing changes unless set.
[plot.encoding]
color_by = "single"
symbol_by = "single"
color = "blue"
symbol = "circle"
# symbol_sequence = ["circle", "square", "diamond", "triangle-up", "x"]

[stats]
show = true
metrics = ["n", "r2", "rmse", "mae", "bias"]

[output]
path = "parity.html"
format = "html"         # html | png | svg | pdf (non-html needs parity-plot[static])
width = 900
height = 900
"""
