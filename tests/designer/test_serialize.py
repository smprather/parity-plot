# tests/designer/test_serialize.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import EXAMPLE_TOML, ParityConfig
from parity_plot.designer.serialize import config_to_toml

WITH_COMMENTS = """\
# my project's tolerance policy
[plot]
# dark reads better on the lab projector
theme = "dark"
reltol = 0.10
"""


def test_round_trips_through_the_normal_loader(tmp_path: Path):
    config = ParityConfig.from_dict({"plot": {"theme": "light", "abstol": 2.0}})

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
    existing = '[plot]\nreltol = "10pct"\n'
    config = ParityConfig.from_dict({"plot": {"reltol": "10pct", "theme": "light"}})

    text = config_to_toml(config, existing=existing)

    assert '"10pct"' in text


def test_changed_values_are_written():
    existing = '[plot]\nreltol = "10pct"\n'
    config = ParityConfig.from_dict({"plot": {"reltol": 0.25}})

    text = config_to_toml(config, existing=existing)

    assert "0.25" in text
    assert '"10pct"' not in text


def test_none_values_are_removed_not_written_as_null():
    existing = "[plot]\nabstol = 2.0\n"
    config = ParityConfig()  # abstol defaults to None

    text = config_to_toml(config, existing=existing)

    assert "abstol" not in text


def test_paths_and_tuples_become_toml_types(tmp_path: Path):
    config = ParityConfig.from_dict(
        {"data": {"paths": ["a.csv", "b.csv"]}, "stats": {"metrics": ["n", "rmse"]}}
    )

    text = config_to_toml(config)
    path = tmp_path / "out.toml"
    path.write_text(text, encoding="utf-8")
    loaded = ParityConfig.from_toml(path)

    assert loaded.data.paths == (Path("a.csv"), Path("b.csv"))
    assert loaded.stats.metrics == ("n", "rmse")


def test_a_fresh_document_carries_the_example_comments():
    text = config_to_toml(ParityConfig())
    assert "#" in text  # generated from EXAMPLE_TOML, comments included