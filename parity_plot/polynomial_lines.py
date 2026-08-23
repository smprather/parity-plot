"""Polynomial reference lines drawn over a parity plot."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

LINE_STYLES = ("solid", "dashed", "dotted")


class PolynomialLineError(ValueError):
    """Raised for a polynomial line that cannot be rendered."""


@dataclass(frozen=True)
class PolynomialLine:
    """One polynomial, with coefficients ordered from highest degree to constant."""

    coefficients: tuple[float, ...]
    color: str = "purple"
    style: str = "solid"

    def __post_init__(self) -> None:
        coefficients = _parse_coefficients(self.coefficients)
        object.__setattr__(self, "coefficients", coefficients)
        if not isinstance(self.color, str) or not self.color.strip():
            raise PolynomialLineError("a polynomial line needs a color")
        if self.style not in LINE_STYLES:
            raise PolynomialLineError(
                f"polynomial line style {self.style!r} is not one of {list(LINE_STYLES)}"
            )

    @classmethod
    def from_csv(
        cls, coefficients: str, *, color: str = "purple", style: str = "solid"
    ) -> PolynomialLine:
        """Build from comma-separated coefficients supplied by an interface."""
        return cls(_parse_coefficients(coefficients), color=color, style=style)

    def evaluate(self, x: float) -> float:
        result = 0.0
        for coefficient in self.coefficients:
            result = result * x + coefficient
        return result

    @property
    def coefficients_csv(self) -> str:
        """Round-trippable comma-separated coefficients for text interfaces."""
        return ", ".join(_format_number(value) for value in self.coefficients)

    @property
    def equation(self) -> str:
        degree = len(self.coefficients) - 1
        terms: list[tuple[str, str]] = []
        for index, coefficient in enumerate(self.coefficients):
            if coefficient == 0:
                continue
            exponent = degree - index
            sign = "-" if coefficient < 0 else "+"
            magnitude = abs(coefficient)
            number = (
                "" if magnitude == 1 and exponent > 0 else _format_number(magnitude)
            )
            variable = (
                "" if exponent == 0 else "x" if exponent == 1 else f"x^{exponent}"
            )
            terms.append((sign, number + variable))

        if not terms:
            return "y = 0"
        first_sign, first_term = terms[0]
        expression = ("-" if first_sign == "-" else "") + first_term
        expression += "".join(f" {sign} {term}" for sign, term in terms[1:])
        return f"y = {expression}"


def _format_number(value: float) -> str:
    """Shortest float spelling that round-trips without losing precision."""
    if value == 0:
        return "0"
    text = repr(value)
    return text[:-2] if text.endswith(".0") else text


def _parse_coefficients(
    value: tuple[float, ...] | str | Iterable[float],
) -> tuple[float, ...]:
    raw: Iterable[object]
    if isinstance(value, str):
        parts = value.split(",")
        if any(not part.strip() for part in parts):
            raise PolynomialLineError(
                "coefficients must be comma-separated numbers with no blank entries"
            )
        raw = parts
    else:
        raw = value

    try:
        coefficients = tuple(float(item) for item in raw)
    except TypeError, ValueError:
        raise PolynomialLineError(
            f"coefficients must be comma-separated numbers, got {value!r}"
        ) from None
    if not coefficients:
        raise PolynomialLineError("a polynomial line needs at least one coefficient")
    if not all(math.isfinite(coefficient) for coefficient in coefficients):
        raise PolynomialLineError("polynomial coefficients must be finite")
    return coefficients
