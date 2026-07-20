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