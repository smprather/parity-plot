# tests/designer/test_serialize.py
from __future__ import annotations

from pathlib import Path

from parity_plot.config import ParityConfig
from parity_plot.designer.serialize import config_to_toml
from parity_plot.tolerances import PARITY_NAME, NamedTolerance

WITH_COMMENTS = """\
# my project's tolerance policy
[plot]
# dark reads better on the lab projector
theme = "dark"
[[plot.tolerances]]
name = "spec"
reltol = 0.10
"""


def test_round_trips_through_the_normal_loader(tmp_path: Path):
    config = ParityConfig.from_dict(
        {"plot": {"theme": "light", "tolerances": [{"name": "spec", "abstol": 2.0}]}}
    )

    text = config_to_toml(config)
    path = tmp_path / "out.toml"
    path.write_text(text, encoding="utf-8")

    assert ParityConfig.from_toml(path) == config


def test_comments_survive_a_save():
    """The config is meant to be hand-edited and committed; a save that eats
    the comments makes the designer unusable on a real project file."""
    config = ParityConfig.from_dict({"plot": {"theme": "light"}})

    text = config_to_toml(config, existing=WITH_COMMENTS)

    assert "# my project's tolerance policy" in text
    assert "# dark reads better on the lab projector" in text
    assert 'theme = "light"' in text


def test_untouched_values_keep_their_original_spelling():
    """`10pct` and `0.1` mean the same thing; rewriting one as the other is a
    gratuitous diff in a file under version control."""
    existing = '[plot]\n[[plot.tolerances]]\nname = "spec"\nreltol = "10pct"\n'
    config = ParityConfig.from_dict(
        {"plot": {"tolerances": [{"name": "spec", "reltol": "10pct"}]}}
    )

    text = config_to_toml(config, existing=existing)

    assert '"10pct"' in text


def test_changed_values_are_written():
    existing = '[plot]\n[[plot.tolerances]]\nname = "spec"\nreltol = "10pct"\n'
    config = ParityConfig.from_dict(
        {"plot": {"tolerances": [{"name": "spec", "reltol": 0.25}]}}
    )

    text = config_to_toml(config, existing=existing)

    assert "0.25" in text
    assert '"10pct"' not in text


def test_a_key_absent_from_the_file_is_written_even_at_its_default():
    """The skip-if-unchanged optimisation compares against a parsed config,
    which fills absent keys with defaults. Without a presence check, a missing
    key compares equal to the default and is never written -- so saving
    silently fails to record that setting."""
    existing = "[plot]\n# theme was deleted by someone else\n"
    config = ParityConfig()  # theme is "dark", which is also the default

    text = config_to_toml(config, existing=existing)

    assert 'theme = "dark"' in text
    assert "# theme was deleted by someone else" in text


def test_none_values_are_removed_not_written_as_null():
    # `abstol` lives on NamedTolerance now; a tolerance with only a reltol
    # writes no `abstol` key, and reloading fills it back to None.
    existing = '[plot]\n[[plot.tolerances]]\nname = "spec"\nabstol = 2.0\nreltol = 0.1\n'
    config = ParityConfig.from_dict(
        {"plot": {"tolerances": [{"name": "spec", "reltol": 0.1}]}}
    )

    text = config_to_toml(config, existing=existing)

    assert "abstol" not in text


def test_files_and_tuples_become_toml_types(tmp_path: Path):
    config = ParityConfig.from_dict(
        {"data": {"files": ["a.csv", "b.csv"]}, "stats": {"metrics": ["n", "rmse"]}}
    )

    text = config_to_toml(config)
    path = tmp_path / "out.toml"
    path.write_text(text, encoding="utf-8")
    loaded = ParityConfig.from_toml(path)

    assert loaded.data.files == (Path("a.csv"), Path("b.csv"))
    assert loaded.stats.metrics == ("n", "rmse")


def test_a_fresh_document_carries_the_example_comments():
    text = config_to_toml(ParityConfig())
    assert "#" in text  # generated from EXAMPLE_TOML, comments included


def test_the_default_parity_entry_is_omitted():
    """The unmodified built-in parity line is re-added by `with_parity` on
    load, so a config carrying only it need not write a tolerance block at all.
    """
    import tomlkit

    text = config_to_toml(ParityConfig())
    doc = tomlkit.parse(text)
    plot = doc["plot"]
    assert "tolerances" not in plot  # no [[plot.tolerances]] array-of-tables
    # And it still round-trips to an equal config.
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write(text)
    assert ParityConfig.from_toml(f.name) == ParityConfig()


def test_a_customised_parity_entry_is_written():
    """A parity entry the user changed (disabled, recoloured, ...) must be
    written, or the customisation is lost on reload."""
    disabled = NamedTolerance(
        name=PARITY_NAME, builtin=True, kind="info", enabled=False
    )
    config = ParityConfig.from_dict({"plot": {"tolerances": [disabled]}})

    text = config_to_toml(config)

    assert "tolerances" in text
    assert 'name = "parity"' in text
    assert "enabled = false" in text
    assert "builtin = true" in text  # loader rejects the reserved name without it

    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write(text)
    assert ParityConfig.from_toml(f.name) == config


def test_only_non_default_fields_are_written_per_entry():
    """A plain one-bound tolerance stays terse rather than emitting ten keys."""
    import tomlkit
    from tomlkit.items import AoT

    config = ParityConfig.from_dict(
        {"plot": {"tolerances": [{"name": "spec", "reltol": 0.1}]}}
    )

    text = config_to_toml(config)
    doc = tomlkit.parse(text)
    aot = doc["plot"]["tolerances"]
    assert isinstance(aot, AoT)
    assert len(aot) == 1
    assert set(aot[0].keys()) == {"name", "reltol"}