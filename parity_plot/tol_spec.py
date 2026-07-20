"""Parsing a --tol mini-spec into a NamedTolerance.

The CLI needs to express the same tolerance list the TOML and designer can, so
one repeatable flag takes a compact `key=value,key=value` spec. Kept pure and
click-free so it is unit-tested on its own.
"""

from __future__ import annotations

from .tolerance import parse_reltol
from .tolerances import KINDS, STYLES, NamedTolerance, ToleranceError

_KEYS = {"name", "label", "abstol", "reltol", "kind", "color", "style"}


class TolSpecError(ValueError):
    """Raised for a malformed --tol value."""


def parse_tol_spec(text: str, auto_name: str) -> NamedTolerance:
    """Turn 'abstol=2,reltol=10pct,kind=info' into a NamedTolerance.

    `auto_name` is used when the spec omits `name=`, so a bare
    '--tol reltol=10pct' still gets a stable identifier.
    """
    fields: dict[str, object] = {}
    for pair in text.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise TolSpecError(
                f"tolerance spec {pair!r} is not key=value (in {text!r})"
            )
        key, value = pair.split("=", 1)
        key, value = key.strip(), value.strip()
        if key not in _KEYS:
            raise TolSpecError(
                f"unknown tolerance key {key!r}; valid keys are {sorted(_KEYS)}"
            )
        fields[key] = value

    if "reltol" in fields:
        try:
            fields["reltol"] = parse_reltol(str(fields["reltol"]))
        except ValueError as exc:
            raise TolSpecError(str(exc)) from None
    if "abstol" in fields:
        try:
            fields["abstol"] = float(str(fields["abstol"]))
        except ValueError:
            raise TolSpecError(f"abstol must be a number, got {fields['abstol']!r}")
    fields.setdefault("name", auto_name)

    try:
        return NamedTolerance(**fields)  # type: ignore[arg-type]
    except ToleranceError as exc:
        raise TolSpecError(str(exc)) from None


def build_tolerances(
    tol_specs: tuple[str, ...],
    abstol: float | None,
    reltol: float | None,
    band_style: str | None,
) -> tuple[NamedTolerance, ...]:
    """Combine repeatable --tol specs with the --abstol/--reltol sugar.

    --tol entries come first, in order. If --abstol or --reltol was given, a
    single extra 'sugar' tolerance is appended -- the one-tolerance shorthand
    people reach for. Auto names are toleranceN across the whole set.
    """
    built: list[NamedTolerance] = []

    def next_name() -> str:
        n = 1
        taken = {t.name for t in built}
        while f"tolerance{n}" in taken:
            n += 1
        return f"tolerance{n}"

    for spec in tol_specs:
        built.append(parse_tol_spec(spec, next_name()))

    if abstol is not None or reltol is not None:
        try:
            built.append(NamedTolerance(
                name=next_name(), abstol=abstol, reltol=reltol,
                style=band_style or "lines",
            ))
        except ToleranceError as exc:
            raise TolSpecError(str(exc)) from None

    return tuple(built)