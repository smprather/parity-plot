# Tolerances Phase 1 (Model & Config) Implementation Plan

> **For agentic workers:** Implement one task only, as fenced in your prompt. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A named-tolerance model and the config that carries a list of them. Nothing renders yet; every piece is unit-tested without a browser.

**Architecture:** `NamedTolerance` wraps the existing `Tolerance` value object — all geometry stays where it is. `PlotConfig` gains a tuple of them and loses the three scalars. Themes gain a colour-token table.

**Tech Stack:** Python ≥3.14, Plotly 6.9, pytest 9.

## Addendum — the parity entry (decided mid-phase, implemented as Task 4)

The `y = x` line becomes the first entry in the tolerance list rather than a separate
feature. A zero tolerance *is* the identity line — `Tolerance(abstol=0).half_width()` is
zero everywhere, so its envelope collapses onto the diagonal — which means `_add_identity`
can be deleted and parity renders through the same path as everything else.

| Decision | Choice |
| --- | --- |
| Modelling | `builtin: bool = False`. Parity sets it True: bounds optional, `kind` forced to `info`, undeletable and partly locked in the UI |
| Validation | The "at least one positive bound" rule applies only when `not builtin`, so a zero-width *user* tolerance stays rejected |
| Z-order | List position governs legend order and the UI; parity is **drawn last** so no shaded band can bury the reference |
| `show_in_legend` | Defaults on for parity, matching how it renders today |

Two further attributes join every tolerance:

- `enabled: bool = True` — a checkbox column in the list. This **replaces**
  `PlotConfig.identity_line`, which retires alongside the other scalars.
- `show_in_legend: bool = True` — keeps the legend readable once several tolerances exist.

`identity_line` therefore joins `abstol`/`reltol`/`band_style` in the retired-key error.

## Global Constraints

- **Never reimplement tolerance geometry.** `NamedTolerance.tolerance` returns a `Tolerance`; `half_width`, `contains`, `label`, `envelope`, `log_envelope` and the `max(abstol, reltol·|x|)` rule all stay in `tolerance.py`.
- **Relative tolerance is a ratio**, with percent stated explicitly (`10pct`). Parse with the existing `tolerance.parse_reltol`.
- **`name` is an identifier, `label` is display text.** A name never auto-changes; a label may. Nothing may key off a label.
- **Clean break from v0.1.0.** Scalar `abstol`/`reltol`/`band_style` in `[plot]` must raise a `ConfigError` naming the new form, not be silently migrated.
- **No numpy or pandas.** Standard library only.
- **Pure modules must not import nicegui or plotly.**
- **Frozen dataclasses.** Never `object.__setattr__`; use `dataclasses.replace`.
- Run tests with `.venv/bin/python -m pytest`. **Baseline is 368 passing.** Phase 1 will break existing tests that reference the removed scalars — that is expected and Task 3 owns fixing them.

---

### Task 1: `tolerances.py` — the named model

**Files:**
- Create: `parity_plot/tolerances.py`
- Test: `tests/test_tolerances.py`

**Interfaces produced:**
- `NamedTolerance(name, abstol, reltol, kind, color, style, label)`
- `.tolerance -> Tolerance` · `.display_label -> str` · `.is_pass_fail -> bool` · `.color_token -> str` · `.contains(x, y) -> bool`
- `default_name(existing) -> str` · `require_unique_names(tolerances)` · `pass_fail(tolerances)` · `failures(tolerances, x, y) -> tuple[str, ...]` · `verdict_text(failed) -> str`
- `ToleranceError(ValueError)` · `KINDS` · `STYLES`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tolerances.py
from __future__ import annotations

import pytest

from parity_plot.tolerance import Tolerance
from parity_plot.tolerances import (
    NamedTolerance,
    ToleranceError,
    default_name,
    failures,
    pass_fail,
    require_unique_names,
    verdict_text,
)


def test_geometry_is_delegated_not_reimplemented():
    """All the math already exists in Tolerance; this only names it."""
    named = NamedTolerance(name="t1", abstol=2.0, reltol=0.1)
    assert named.tolerance == Tolerance(abstol=2.0, reltol=0.1)
    assert named.contains(100.0, 105.0) is named.tolerance.contains(100.0, 105.0)


def test_at_least_one_bound_is_required():
    with pytest.raises(ToleranceError, match="abstol or reltol"):
        NamedTolerance(name="t1")


@pytest.mark.parametrize("kwargs", [{"abstol": 2.0}, {"reltol": 0.1}, {"abstol": 2.0, "reltol": 0.1}])
def test_either_bound_alone_is_enough(kwargs):
    assert NamedTolerance(name="t1", **kwargs)


@pytest.mark.parametrize("name", ["has space", "tab\there", "line\nbreak", " leading", "trailing "])
def test_names_may_not_contain_whitespace(name):
    """The name is an identifier: it appears in configs, CLI flags and the
    table's comma-separated failure list, where a space would be ambiguous."""
    with pytest.raises(ToleranceError, match="whitespace"):
        NamedTolerance(name=name, abstol=1.0)


def test_names_may_not_be_empty():
    with pytest.raises(ToleranceError, match="name"):
        NamedTolerance(name="", abstol=1.0)


@pytest.mark.parametrize("kwargs", [{"abstol": 0}, {"abstol": -1}, {"reltol": 0}, {"reltol": -0.5}])
def test_bounds_must_be_positive(kwargs):
    with pytest.raises(ToleranceError, match="positive"):
        NamedTolerance(name="t1", **kwargs)


def test_kind_and_style_are_checked():
    with pytest.raises(ToleranceError, match="kind"):
        NamedTolerance(name="t1", abstol=1.0, kind="maybe")
    with pytest.raises(ToleranceError, match="style"):
        NamedTolerance(name="t1", abstol=1.0, style="dotted")


def test_label_defaults_to_the_spec():
    assert NamedTolerance(name="t1", reltol=0.1).display_label == "±10%"
    assert NamedTolerance(name="t1", abstol=2.0, reltol=0.1).display_label == "±max(2, 10%)"


def test_the_literal_string_auto_also_means_derive_it():
    assert NamedTolerance(name="t1", reltol=0.1, label="auto").display_label == "±10%"


def test_a_manual_label_is_used_verbatim():
    named = NamedTolerance(name="t1", reltol=0.1, label="customer limit")
    assert named.display_label == "customer limit"


def test_a_manual_label_may_contain_spaces():
    """Unlike the name, a label is display text and is never parsed."""
    assert NamedTolerance(name="t1", abstol=1.0, label="upper spec limit").display_label


def test_editing_a_bound_does_not_change_the_name():
    """The table lists failed *names*; a name that drifted would silently
    re-point at a different threshold."""
    from dataclasses import replace

    original = NamedTolerance(name="tolerance1", reltol=0.1)
    edited = replace(original, reltol=0.25)
    assert edited.name == "tolerance1"
    assert edited.display_label == "±25%"  # the label follows, the name does not


def test_pass_is_the_default_kind():
    assert NamedTolerance(name="t1", abstol=1.0).is_pass_fail
    assert not NamedTolerance(name="t1", abstol=1.0, kind="info").is_pass_fail


def test_colour_defaults_by_kind():
    assert NamedTolerance(name="t1", abstol=1.0).color_token == "red"
    assert NamedTolerance(name="t1", abstol=1.0, kind="info").color_token == "yellow"
    assert NamedTolerance(name="t1", abstol=1.0, color="purple").color_token == "purple"


def test_default_name_counts_up_past_taken_ones():
    assert default_name([]) == "tolerance1"
    assert default_name(["tolerance1"]) == "tolerance2"
    assert default_name(["tolerance1", "tolerance3"]) == "tolerance2"
    assert default_name(["spec", "tight"]) == "tolerance1"


def test_duplicate_names_are_rejected():
    """Two tolerances called the same thing make the failure list meaningless."""
    tols = [NamedTolerance(name="t1", abstol=1.0), NamedTolerance(name="t1", reltol=0.1)]
    with pytest.raises(ToleranceError, match="duplicate"):
        require_unique_names(tols)


def test_unique_names_pass():
    require_unique_names([NamedTolerance(name="a", abstol=1.0), NamedTolerance(name="b", abstol=2.0)])


def test_pass_fail_selects_only_criteria():
    tols = [
        NamedTolerance(name="spec", reltol=0.1),
        NamedTolerance(name="ref", reltol=0.25, kind="info"),
        NamedTolerance(name="tight", abstol=1.0),
    ]
    assert [t.name for t in pass_fail(tols)] == ["spec", "tight"]


def test_failures_names_every_criterion_the_point_breaks():
    tols = [
        NamedTolerance(name="spec", reltol=0.10),
        NamedTolerance(name="tight", reltol=0.01),
        NamedTolerance(name="ref", reltol=0.001, kind="info"),
    ]
    # 5% off: passes spec, fails tight; ref is info and never judged.
    assert failures(tols, 100.0, 105.0) == ("tight",)
    # 50% off: fails both criteria.
    assert failures(tols, 100.0, 150.0) == ("spec", "tight")
    # exact: fails nothing.
    assert failures(tols, 100.0, 100.0) == ()


def test_failures_preserves_declaration_order():
    tols = [
        NamedTolerance(name="zebra", reltol=0.01),
        NamedTolerance(name="alpha", reltol=0.01),
    ]
    assert failures(tols, 100.0, 200.0) == ("zebra", "alpha")


def test_failures_with_no_criteria_is_empty():
    assert failures([NamedTolerance(name="ref", reltol=0.1, kind="info")], 1.0, 99.0) == ()
    assert failures([], 1.0, 99.0) == ()


def test_verdict_text_reads_as_the_table_column_does():
    assert verdict_text(()) == "pass"
    assert verdict_text(("spec",)) == "spec"
    assert verdict_text(("spec", "tight")) == "spec, tight"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tolerances.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parity_plot.tolerances'`

- [ ] **Step 3: Write the implementation**

```python
# parity_plot/tolerances.py
"""Named tolerances.

A plot may carry several specifications at once -- a customer limit, a tighter
internal target, a reference band nobody is graded against. Each is a
`NamedTolerance`: a `Tolerance` (which owns all the geometry) plus the identity
and presentation needed to tell several of them apart.

`name` and `label` are deliberately different things. The name is an
identifier: it appears in configs, in CLI flags, and in the comma-separated
failure list shown per record, so it must be stable and space-free. The label
is display text for the legend, may contain spaces, and may follow the spec
automatically -- nothing keys off it, so it is free to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .tolerance import Tolerance

KINDS = ("pass", "info")
STYLES = ("lines", "shaded")
AUTO_LABEL = "auto"

# Pass/fail limits are a warning; informational bands are not.
DEFAULT_COLORS = {"pass": "red", "info": "yellow"}


class ToleranceError(ValueError):
    """Raised for a tolerance that cannot mean anything."""


@dataclass(frozen=True)
class NamedTolerance:
    """One specification, named and drawable."""

    name: str
    abstol: float | None = None
    reltol: float | None = None
    kind: str = "pass"
    color: str | None = None
    style: str = "lines"
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ToleranceError("a tolerance needs a name")
        if any(character.isspace() for character in self.name):
            raise ToleranceError(
                f"tolerance name {self.name!r} may not contain whitespace; it is an "
                f"identifier and appears in comma-separated failure lists"
            )
        if self.abstol is None and self.reltol is None:
            raise ToleranceError(
                f"tolerance {self.name!r} needs abstol or reltol (or both)"
            )
        for field_name in ("abstol", "reltol"):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise ToleranceError(
                    f"tolerance {self.name!r}: {field_name} must be positive, got {value}"
                )
        if self.kind not in KINDS:
            raise ToleranceError(
                f"tolerance {self.name!r}: kind {self.kind!r} is not one of {list(KINDS)}"
            )
        if self.style not in STYLES:
            raise ToleranceError(
                f"tolerance {self.name!r}: style {self.style!r} is not one of {list(STYLES)}"
            )

    @property
    def tolerance(self) -> Tolerance:
        """The geometry. Every calculation lives there, not here."""
        return Tolerance(abstol=self.abstol, reltol=self.reltol)

    @property
    def display_label(self) -> str:
        """Legend text: the manual label, or one derived from the spec."""
        if self.label and self.label != AUTO_LABEL:
            return self.label
        return self.tolerance.label()

    @property
    def is_pass_fail(self) -> bool:
        return self.kind == "pass"

    @property
    def color_token(self) -> str:
        """The colour token, defaulted by kind. Resolved to a shade by the theme."""
        return self.color or DEFAULT_COLORS[self.kind]

    def contains(self, x: float, y: float) -> bool:
        return self.tolerance.contains(x, y)


def default_name(existing: Sequence[str]) -> str:
    """The next free ``toleranceN``, skipping names already taken."""
    taken = set(existing)
    index = 1
    while f"tolerance{index}" in taken:
        index += 1
    return f"tolerance{index}"


def require_unique_names(tolerances: Sequence[NamedTolerance]) -> None:
    """Reject repeated names.

    A record's verdict is a list of failed names; two tolerances sharing one
    would make that list impossible to read back.
    """
    seen: set[str] = set()
    duplicates: list[str] = []
    for tol in tolerances:
        if tol.name in seen and tol.name not in duplicates:
            duplicates.append(tol.name)
        seen.add(tol.name)
    if duplicates:
        raise ToleranceError(f"duplicate tolerance name(s): {', '.join(duplicates)}")


def pass_fail(tolerances: Sequence[NamedTolerance]) -> tuple[NamedTolerance, ...]:
    """Only the entries a point can actually fail."""
    return tuple(tol for tol in tolerances if tol.is_pass_fail)


def failures(
    tolerances: Sequence[NamedTolerance], x: float, y: float
) -> tuple[str, ...]:
    """Names of every pass/fail tolerance this point breaks, in declared order.

    Informational entries are never judged -- they are drawn for reference, and
    reporting a point as failing one would invent a criterion.
    """
    return tuple(tol.name for tol in pass_fail(tolerances) if not tol.contains(x, y))


def verdict_text(failed: Sequence[str]) -> str:
    """How a verdict reads in the table and the hover."""
    return ", ".join(failed) if failed else "pass"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tolerances.py -v`
Expected: PASS, 24 tests

- [ ] **Step 5: Stop. Do not commit.**

---

### Task 2: Theme colour tokens

**Files:**
- Modify: `parity_plot/themes.py` (additively — do not remove `tolerance`/`band_fill` yet; Phase 2 retires them)
- Test: `tests/test_theme_colors.py`

**Interfaces produced:**
- `Theme.tolerance_colors: dict[str, str]`
- `Theme.resolve_color(token: str) -> str`
- `Theme.band_fill_for(token: str, alpha: float = 0.10) -> str`
- `themes.COLOR_TOKENS: tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_theme_colors.py
from __future__ import annotations

import pytest

from parity_plot import themes

RESERVED = {
    "identity": "the y = x line",
    "marker": "the paired points",
    "rug": "unpaired record ticks",
}


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_every_token_resolves_in_every_theme(theme_name):
    theme = themes.get(theme_name)
    for token in themes.COLOR_TOKENS:
        assert theme.resolve_color(token).startswith("#")


def test_the_offered_tokens_are_the_curated_set():
    assert themes.COLOR_TOKENS == (
        "red", "yellow", "orange", "green", "blue", "purple", "magenta", "grey",
    )


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_no_token_duplicates_a_reserved_colour(theme_name):
    """green is the identity line, blue is the markers, amber is the rug. A
    tolerance drawn in exactly one of those shades would impersonate it."""
    theme = themes.get(theme_name)
    reserved = {theme.identity.lower(), theme.marker.lower(), theme.rug.lower()}
    for token in themes.COLOR_TOKENS:
        assert theme.resolve_color(token).lower() not in reserved


@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_tokens_are_distinct_from_each_other(theme_name):
    theme = themes.get(theme_name)
    shades = [theme.resolve_color(t).lower() for t in themes.COLOR_TOKENS]
    assert len(set(shades)) == len(shades)


def test_dark_and_light_use_different_shades():
    """A colour tuned for a dark background is wrong on a light one."""
    dark, light = themes.get("dark"), themes.get("light")
    assert dark.resolve_color("red") != light.resolve_color("red")


def test_a_hex_value_passes_through_untouched():
    """The escape hatch: anything starting # is used verbatim."""
    theme = themes.get("dark")
    assert theme.resolve_color("#8844ff") == "#8844ff"
    assert theme.resolve_color("#ABC") == "#ABC"


def test_an_unknown_token_is_rejected_with_the_valid_list():
    theme = themes.get("dark")
    with pytest.raises(ValueError) as exc:
        theme.resolve_color("chartreuse")
    assert "chartreuse" in str(exc.value)
    assert "red" in str(exc.value)


def test_band_fill_is_the_same_hue_made_translucent():
    theme = themes.get("dark")
    fill = theme.band_fill_for("red")
    assert fill.startswith("rgba(")
    assert fill.endswith("0.1)")


def test_band_fill_works_for_a_hex_escape_hatch():
    assert themes.get("dark").band_fill_for("#8844ff").startswith("rgba(136, 68, 255")


def test_band_fill_alpha_is_adjustable():
    assert themes.get("dark").band_fill_for("red", alpha=0.5).endswith("0.5)")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_theme_colors.py -v`
Expected: FAIL — `AttributeError: 'Theme' object has no attribute 'resolve_color'`

- [ ] **Step 3: Modify `parity_plot/themes.py`**

Add near the top, after the imports:

```python
# Tolerance colours are chosen to sit clearly apart from the three shades that
# already carry meaning here: `identity` (the y = x line), `marker` (the paired
# points) and `rug` (unpaired ticks). `green` and `blue` are offered, but as an
# olive and a true blue rather than the mint and cyan those reserved roles use.
COLOR_TOKENS = ("red", "yellow", "orange", "green", "blue", "purple", "magenta", "grey")
```

Add the field to the `Theme` dataclass, after `band_fill`:

```python
    tolerance_colors: dict[str, str] = field(default_factory=dict)
```

(`field` is already imported by `dataclasses` in this module; add it to the import if not.)

Add these methods to `Theme`:

```python
    def resolve_color(self, token: str) -> str:
        """A token, or a hex value passed through untouched."""
        if token.startswith("#"):
            return token
        try:
            return self.tolerance_colors[token]
        except KeyError:
            raise ValueError(
                f"unknown colour {token!r}; use one of {list(COLOR_TOKENS)} "
                f"or a hex value like '#8844ff'"
            ) from None

    def band_fill_for(self, token: str, alpha: float = 0.10) -> str:
        """The same colour, translucent, for a shaded band."""
        red, green, blue = _hex_to_rgb(self.resolve_color(token))
        return f"rgba({red}, {green}, {blue}, {alpha})"
```

Add this helper at module level:

```python
def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    if len(text) == 3:  # short form, #abc
        text = "".join(character * 2 for character in text)
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
```

Give `DARK` these colours:

```python
    tolerance_colors={
        "red": "#ff4d5a",
        "yellow": "#ffd23f",
        "orange": "#ff8c42",
        "green": "#9ccc65",     # olive, not the identity line's mint
        "blue": "#5b8dee",      # true blue, not the markers' cyan
        "purple": "#b18cff",
        "magenta": "#ff6ec7",
        "grey": "#9aa4b0",
    },
```

and `LIGHT` these:

```python
    tolerance_colors={
        "red": "#d00000",
        "yellow": "#b38600",
        "orange": "#b35309",
        "green": "#6a8f00",     # olive, not the identity line's emerald
        "blue": "#3b5bdb",      # true blue, not the markers' teal
        "purple": "#7048e8",
        "magenta": "#c2255c",
        "grey": "#6b7280",
    },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_theme_colors.py -v`
Expected: PASS, 11 tests. The rest of the suite must be unaffected — this task is purely additive.

- [ ] **Step 5: Stop. Do not commit.**

---

### Task 3: `PlotConfig.tolerances` and the array-of-tables

The breaking change. Removes three scalars, adds a list, and updates every existing test that referenced the old shape.

**Files:**
- Modify: `parity_plot/config.py`
- Modify: existing tests that reference `abstol` / `reltol` / `band_style` on `PlotConfig`
- Test: `tests/test_config_tolerances.py`

**Interfaces produced:**
- `PlotConfig.tolerances: tuple[NamedTolerance, ...] = ()`
- `[[plot.tolerances]]` parsing, with `ConfigError` for the retired scalars

Task 1 must be complete first; this imports `NamedTolerance`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_tolerances.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ConfigError, ParityConfig
from parity_plot.tolerances import NamedTolerance


def test_no_tolerances_by_default():
    assert ParityConfig().plot.tolerances == ()


def test_a_single_tolerance_round_trips(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\nname = "spec"\nreltol = 0.10\n', encoding="utf-8"
    )
    tols = ParityConfig.from_toml(path).plot.tolerances
    assert tols == (NamedTolerance(name="spec", reltol=0.10),)


def test_several_tolerances_keep_their_order(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\nname = "spec"\nreltol = 0.10\n\n'
        '[[plot.tolerances]]\nname = "tight"\nabstol = 2.0\n\n'
        '[[plot.tolerances]]\nname = "ref"\nreltol = 0.25\nkind = "info"\n',
        encoding="utf-8",
    )
    tols = ParityConfig.from_toml(path).plot.tolerances
    assert [t.name for t in tols] == ["spec", "tight", "ref"]
    assert tols[2].kind == "info"


def test_every_attribute_parses(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\n'
        'name = "customer"\nlabel = "customer limit"\n'
        'abstol = 2.0\nreltol = 0.10\nkind = "pass"\n'
        'color = "purple"\nstyle = "shaded"\n',
        encoding="utf-8",
    )
    tol = ParityConfig.from_toml(path).plot.tolerances[0]
    assert tol == NamedTolerance(
        name="customer", label="customer limit", abstol=2.0, reltol=0.10,
        kind="pass", color="purple", style="shaded",
    )


def test_reltol_accepts_the_percent_spelling(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\nname = "spec"\nreltol = "10pct"\n', encoding="utf-8"
    )
    assert ParityConfig.from_toml(path).plot.tolerances[0].reltol == pytest.approx(0.10)


def test_duplicate_names_are_rejected(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\nname = "spec"\nreltol = 0.1\n\n'
        '[[plot.tolerances]]\nname = "spec"\nabstol = 2.0\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate"):
        ParityConfig.from_toml(path)


def test_a_tolerance_with_no_bound_is_rejected(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text('[[plot.tolerances]]\nname = "spec"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="abstol or reltol"):
        ParityConfig.from_toml(path)


def test_an_unknown_tolerance_key_is_rejected(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\nname = "spec"\nreltol = 0.1\ncolour = "red"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="colour"):
        ParityConfig.from_toml(path)


@pytest.mark.parametrize("key, value", [
    ("abstol", "2.0"), ("reltol", "0.10"), ("band_style", '"lines"'),
])
def test_the_v0_1_0_scalar_keys_are_a_clear_error(tmp_path: Path, key, value):
    """A clean break, but the message has to teach the new shape."""
    path = tmp_path / "p.toml"
    path.write_text(f"[plot]\n{key} = {value}\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        ParityConfig.from_toml(path)

    message = str(exc.value)
    assert key in message
    assert "[[plot.tolerances]]" in message


def test_merge_replaces_the_whole_list():
    """Tolerances are edited as a set, not merged element-wise -- otherwise
    deleting one from the designer could not be expressed."""
    cfg = ParityConfig.from_dict(
        {"plot": {"tolerances": [{"name": "a", "reltol": 0.1}]}}
    )
    merged = cfg.merge(plot={"tolerances": (NamedTolerance(name="b", abstol=1.0),)})
    assert [t.name for t in merged.plot.tolerances] == ["b"]


def test_an_empty_list_clears_them():
    cfg = ParityConfig.from_dict(
        {"plot": {"tolerances": [{"name": "a", "reltol": 0.1}]}}
    )
    assert cfg.merge(plot={"tolerances": ()}).plot.tolerances == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_config_tolerances.py -v`
Expected: FAIL — `TypeError` on the unknown `tolerances` key.

- [ ] **Step 3: Modify `parity_plot/config.py`**

Import at the top:

```python
from .tolerances import NamedTolerance, ToleranceError, require_unique_names
```

In `PlotConfig`, delete `abstol`, `reltol` and `band_style`, and add:

```python
    # A plot may carry several specifications at once. Order is meaningful: it
    # drives legend order and the order names appear in a failure list.
    tolerances: tuple[NamedTolerance, ...] = ()
```

Remove `"band_style"` from `_CHOICES`, and `"abstol"` from `_POSITIVE_FLOAT`; keep
`_RELTOL` — the per-tolerance parser reuses it.

Add to the retired-key check. In `_build`, before the unknown-key check, add:

```python
RETIRED_PLOT_KEYS = ("abstol", "reltol", "band_style")
```

at module level, and inside `_build`:

```python
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
            )
```

Add the coercion branch in `_coerce`, before the `_CHOICES` check:

```python
    if key == "tolerances":
        return _coerce_tolerances(value, where)
```

and the builder at module level:

```python
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
    return tuple(built)
```

Import `default_name` alongside the others.

Update `EXAMPLE_TOML`: remove the `abstol`/`reltol`/`band_style` lines from `[plot]` and
append a documented `[[plot.tolerances]]` block.

- [ ] **Step 4: Fix the existing tests that used the old shape**

Run the full suite and update every failure that references `abstol=`, `reltol=`,
`band_style=` on `PlotConfig`, or `plot.abstol` / `plot.reltol`. The mechanical
substitution is:

```python
# before
PlotConfig(reltol=0.10)
PlotConfig(abstol=2.0, reltol=0.10, band_style="shaded")

# after
PlotConfig(tolerances=(NamedTolerance(name="t1", reltol=0.10),))
PlotConfig(tolerances=(NamedTolerance(name="t1", abstol=2.0, reltol=0.10, style="shaded"),))
```

Files known to need this: `tests/test_config.py`, `tests/test_plot.py`,
`tests/test_stats.py`, `tests/test_cli.py`, and several under `tests/designer/`.

**Tests asserting rendering behaviour (`tests/test_plot.py`, the designer's golden
suite) will still fail after this substitution**, because `plot.py` has not been taught
to read the list yet — that is Phase 2's job. Mark those with
`@pytest.mark.xfail(reason="plot reads the tolerance list in Phase 2", strict=False)`
rather than deleting them, and report which ones you marked.

- [ ] **Step 5: Run the suite**

Run: `.venv/bin/python -m pytest -q`
Expected: green, with the Phase 2 renderers xfailed. Report the xfail count.

- [ ] **Step 6: Stop. Do not commit.**

---

### Task 4: The parity entry, `enabled`, and `show_in_legend`

Layers the addendum onto Tasks 1 and 3. Adds three attributes, makes the parity entry a
guaranteed first element, and retires `PlotConfig.identity_line`.

**Files:**
- Modify: `parity_plot/tolerances.py` (add fields, branch validation, add `PARITY`/`with_parity`)
- Modify: `parity_plot/config.py` (retire `identity_line`; guarantee parity leads the list)
- Test: `tests/test_parity_entry.py`

**Interfaces produced:**
- `NamedTolerance.builtin: bool = False` · `.enabled: bool = True` · `.show_in_legend: bool = True`
- `tolerances.PARITY_NAME = "parity"` · `tolerances.parity() -> NamedTolerance`
- `tolerances.with_parity(tolerances) -> tuple[NamedTolerance, ...]` — parity first, exactly once
- `tolerances.draw_order(tolerances) -> tuple[NamedTolerance, ...]` — enabled only, parity last

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_parity_entry.py
from __future__ import annotations

from dataclasses import replace

import pytest

from parity_plot.config import ConfigError, ParityConfig
from parity_plot.tolerances import (
    PARITY_NAME,
    NamedTolerance,
    ToleranceError,
    draw_order,
    failures,
    parity,
    with_parity,
)


def test_parity_needs_no_bounds():
    """A zero tolerance is the identity line; requiring a bound would be absurd."""
    entry = parity()
    assert entry.name == PARITY_NAME
    assert entry.builtin
    assert entry.abstol is None and entry.reltol is None


def test_a_normal_tolerance_still_needs_a_bound():
    """Relaxing the rule for parity must not relax it for everyone."""
    with pytest.raises(ToleranceError, match="abstol or reltol"):
        NamedTolerance(name="oops")


def test_parity_is_informational_and_never_judged():
    assert parity().kind == "info"
    assert not parity().is_pass_fail
    assert failures([parity()], 1.0, 999.0) == ()


def test_parity_is_green_by_default():
    assert parity().color_token == "green"


def test_parity_shows_in_the_legend_by_default():
    assert parity().show_in_legend


def test_tolerances_are_enabled_by_default():
    assert parity().enabled
    assert NamedTolerance(name="t1", abstol=1.0).enabled


def test_with_parity_prepends_it_when_absent():
    tols = (NamedTolerance(name="spec", reltol=0.1),)
    assert [t.name for t in with_parity(tols)] == [PARITY_NAME, "spec"]


def test_with_parity_does_not_duplicate_an_existing_one():
    tols = (parity(), NamedTolerance(name="spec", reltol=0.1))
    assert [t.name for t in with_parity(tols)] == [PARITY_NAME, "spec"]


def test_with_parity_moves_a_stray_parity_entry_to_the_front():
    tols = (NamedTolerance(name="spec", reltol=0.1), parity())
    assert [t.name for t in with_parity(tols)] == [PARITY_NAME, "spec"]


def test_with_parity_preserves_a_customised_parity_entry():
    """Disabling it, or recolouring it, must survive the normalisation."""
    custom = replace(parity(), enabled=False, color="grey")
    result = with_parity((NamedTolerance(name="spec", reltol=0.1), custom))
    assert result[0].enabled is False
    assert result[0].color_token == "grey"


def test_draw_order_puts_parity_last_so_nothing_buries_it():
    """List position drives the legend; z-order is separate."""
    tols = with_parity((
        NamedTolerance(name="spec", reltol=0.1, style="shaded"),
        NamedTolerance(name="tight", abstol=1.0),
    ))
    assert [t.name for t in tols] == [PARITY_NAME, "spec", "tight"]
    assert [t.name for t in draw_order(tols)] == ["spec", "tight", PARITY_NAME]


def test_draw_order_omits_disabled_entries():
    tols = (
        replace(parity(), enabled=False),
        NamedTolerance(name="spec", reltol=0.1),
        NamedTolerance(name="off", abstol=1.0, enabled=False),
    )
    assert [t.name for t in draw_order(tols)] == ["spec"]


def test_a_user_tolerance_may_not_claim_the_parity_name():
    with pytest.raises(ToleranceError, match="reserved"):
        NamedTolerance(name=PARITY_NAME, abstol=1.0)


def test_a_builtin_entry_is_forced_informational():
    with pytest.raises(ToleranceError, match="info"):
        NamedTolerance(name=PARITY_NAME, builtin=True, kind="pass")


def test_config_gains_parity_automatically(tmp_path):
    """Even a config that never mentions it gets the reference line."""
    path = tmp_path / "p.toml"
    path.write_text('[[plot.tolerances]]\nname = "spec"\nreltol = 0.1\n', encoding="utf-8")
    tols = ParityConfig.from_toml(path).plot.tolerances
    assert [t.name for t in tols] == [PARITY_NAME, "spec"]


def test_an_empty_config_still_has_parity():
    assert [t.name for t in ParityConfig().plot.tolerances] == [PARITY_NAME]


def test_parity_can_be_disabled_from_config(tmp_path):
    """This is what replaces the old identity_line = false."""
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\nname = "parity"\nbuiltin = true\nenabled = false\n',
        encoding="utf-8",
    )
    tols = ParityConfig.from_toml(path).plot.tolerances
    assert tols[0].name == PARITY_NAME
    assert tols[0].enabled is False


def test_identity_line_is_a_retired_key(tmp_path):
    path = tmp_path / "p.toml"
    path.write_text("[plot]\nidentity_line = false\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        ParityConfig.from_toml(path)
    assert "identity_line" in str(exc.value)
    assert "enabled" in str(exc.value)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_parity_entry.py -v`
Expected: FAIL — `ImportError: cannot import name 'PARITY_NAME'`

- [ ] **Step 3: Extend `parity_plot/tolerances.py`**

Add the three fields to `NamedTolerance`, after `label`:

```python
    enabled: bool = True
    show_in_legend: bool = True
    builtin: bool = False
```

Add near the constants:

```python
PARITY_NAME = "parity"
```

Rework `__post_init__`'s bound checks so the requirement is conditional, and add the two
new rules. Replace the "at least one bound" block with:

```python
        if self.builtin:
            # The parity line is a zero tolerance: requiring a bound would be
            # absurd, and it is a reference rather than a criterion.
            if self.kind != "info":
                raise ToleranceError(
                    f"builtin tolerance {self.name!r} must be kind 'info', got {self.kind!r}"
                )
        else:
            if self.name == PARITY_NAME:
                raise ToleranceError(
                    f"{PARITY_NAME!r} is a reserved name for the built-in y = x line"
                )
            if self.abstol is None and self.reltol is None:
                raise ToleranceError(
                    f"tolerance {self.name!r} needs abstol or reltol (or both)"
                )
```

Keep the positive-value loop as it is — it only fires on values that were supplied.

Add at module level:

```python
def parity() -> NamedTolerance:
    """The built-in y = x reference line.

    It is a tolerance of zero: `Tolerance().half_width()` is zero everywhere, so
    its envelope collapses onto the diagonal and it renders through the same
    path as every other entry.
    """
    return NamedTolerance(
        name=PARITY_NAME,
        builtin=True,
        kind="info",
        color="green",
        label="0% error (y = x)",
    )


def with_parity(tolerances: Sequence[NamedTolerance]) -> tuple[NamedTolerance, ...]:
    """Guarantee exactly one parity entry, first, preserving any customisation."""
    existing = next((t for t in tolerances if t.name == PARITY_NAME), None)
    rest = [t for t in tolerances if t.name != PARITY_NAME]
    return (existing or parity(), *rest)


def draw_order(tolerances: Sequence[NamedTolerance]) -> tuple[NamedTolerance, ...]:
    """Enabled entries in paint order: parity last, so nothing buries it.

    List position drives the legend and the UI; this is deliberately separate,
    because a shaded band later in the list would otherwise cover the reference.
    """
    live = [t for t in tolerances if t.enabled]
    return (
        *[t for t in live if t.name != PARITY_NAME],
        *[t for t in live if t.name == PARITY_NAME],
    )
```

- [ ] **Step 4: Extend `parity_plot/config.py`**

Add `"identity_line"` to `RETIRED_PLOT_KEYS`, and extend that error's guidance:

```python
                f"  enabled = false     # replaces identity_line for the parity entry\n"
```

At the end of `_coerce_tolerances`, before returning, normalise:

```python
    return with_parity(tuple(built))
```

importing `with_parity` alongside the others. Also make `PlotConfig.tolerances` default to
the parity entry rather than an empty tuple:

```python
    tolerances: tuple[NamedTolerance, ...] = field(default_factory=lambda: (parity(),))
```

- [ ] **Step 5: Run and reconcile**

Run: `.venv/bin/python -m pytest tests/test_parity_entry.py -v` → all pass.
Then `.venv/bin/python -m pytest -q`. Task 3's config tests asserting an empty default or
an exact tolerance tuple now see the parity entry — update those expectations, and report
which you changed.

- [ ] **Step 6: Stop. Do not commit.**
