# tests/test_config_tolerances.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ConfigError, ParityConfig
from parity_plot.tolerances import PARITY_NAME, NamedTolerance


def test_no_tolerances_by_default():
    """Even an empty config carries the built-in y = x reference line."""
    assert [t.name for t in ParityConfig().plot.tolerances] == [PARITY_NAME]


def test_a_single_tolerance_round_trips(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\nname = "spec"\nreltol = 0.10\n', encoding="utf-8"
    )
    tols = ParityConfig.from_toml(path).plot.tolerances
    assert tols == (NamedTolerance(name=PARITY_NAME, builtin=True, kind="info", color="green", label="0% error (y = x)"),
                    NamedTolerance(name="spec", reltol=0.10))


def test_several_tolerances_keep_their_order(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\nname = "spec"\nreltol = 0.10\n\n'
        '[[plot.tolerances]]\nname = "tight"\nabstol = 2.0\n\n'
        '[[plot.tolerances]]\nname = "ref"\nreltol = 0.25\nkind = "info"\n',
        encoding="utf-8",
    )
    tols = ParityConfig.from_toml(path).plot.tolerances
    assert [t.name for t in tols] == [PARITY_NAME, "spec", "tight", "ref"]
    assert tols[3].kind == "info"


def test_every_attribute_parses(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\n'
        'name = "customer"\nlabel = "customer limit"\n'
        'abstol = 2.0\nreltol = 0.10\nkind = "pass"\n'
        'color = "purple"\nstyle = "shaded"\n',
        encoding="utf-8",
    )
    tol = ParityConfig.from_toml(path).plot.tolerances[1]
    assert tol == NamedTolerance(
        name="customer", label="customer limit", abstol=2.0, reltol=0.10,
        kind="pass", color="purple", style="shaded",
    )


def test_reltol_accepts_the_percent_spelling(tmp_path: Path):
    path = tmp_path / "p.toml"
    path.write_text(
        '[[plot.tolerances]]\nname = "spec"\nreltol = "10pct"\n', encoding="utf-8"
    )
    assert ParityConfig.from_toml(path).plot.tolerances[1].reltol == pytest.approx(0.10)


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
    deleting one from the designer could not be expressed. Parity is always
    re-added by the normalisation, so it survives a replace."""
    cfg = ParityConfig.from_dict(
        {"plot": {"tolerances": [{"name": "a", "reltol": 0.1}]}}
    )
    merged = cfg.merge(plot={"tolerances": (NamedTolerance(name="b", abstol=1.0),)})
    assert [t.name for t in merged.plot.tolerances] == [PARITY_NAME, "b"]


def test_an_empty_list_clears_the_user_entries_but_keeps_parity():
    cfg = ParityConfig.from_dict(
        {"plot": {"tolerances": [{"name": "a", "reltol": 0.1}]}}
    )
    assert [t.name for t in cfg.merge(plot={"tolerances": ()}).plot.tolerances] == [
        PARITY_NAME
    ]