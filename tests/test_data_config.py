# tests/test_data_config.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ConfigError, DataConfig, ParityConfig


def test_defaults_are_empty():
    d = DataConfig()
    assert d.files == () and d.ref is None and d.test is None
    assert d.join is None and d.group == () and d.color_column is None


def test_group_defaults_to_empty_tuple():
    d = DataConfig()
    assert d.join is None and d.group == () and d.color_column is None


def test_group_string_normalises_to_one_tuple():
    d = DataConfig(group="batch")
    assert d.group == ("batch",)


def test_group_list_normalises_to_tuple():
    d = DataConfig(group=["package", "vendor"])
    assert d.group == ("package", "vendor")


def test_color_column_is_a_plain_ref():
    d = DataConfig(color_column="d.csv:temperature")
    assert d.color_column == "d.csv:temperature"


def test_parses_the_new_shape(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[data]\nfiles = ["meas.csv", "sim.csv"]\n'
        'ref = "meas.csv:voltage"\ntest = "sim.csv:voltage"\n'
        'join = "id"\ngroup = "batch"\n',
        encoding="utf-8",
    )
    d = ParityConfig.from_toml(p).data
    assert d.files == (Path("meas.csv"), Path("sim.csv"))
    assert d.ref == "meas.csv:voltage"
    assert d.test == "sim.csv:voltage"
    assert d.join == "id"
    assert d.group == ("batch",)


def test_join_and_group_are_optional(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[data]\nfiles = ["d.csv"]\nref = "d.csv:a"\ntest = "d.csv:b"\n',
        encoding="utf-8",
    )
    d = ParityConfig.from_toml(p).data
    assert d.join is None and d.group == ()


@pytest.mark.parametrize(
    "key, value",
    [
        ("paths", '["d.csv"]'),
        ("x", '"reference"'),
        ("y", '"measured"'),
        ("key", '"id"'),
        ("value", '"value"'),
    ],
)
def test_retired_data_keys_error_with_guidance(tmp_path: Path, key, value):
    p = tmp_path / "c.toml"
    p.write_text(f"[data]\n{key} = {value}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        ParityConfig.from_toml(p)
    assert key in str(exc.value)
    assert "files" in str(exc.value)  # points at the new shape


def test_unknown_data_key_is_rejected(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text('[data]\nfiles = ["d.csv"]\nreff = "d.csv:a"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="reff"):
        ParityConfig.from_toml(p)


def test_merge_overrides_data_fields():
    cfg = ParityConfig.from_dict({"data": {"files": ["a.csv"], "ref": "a.csv:x"}})
    merged = cfg.merge(data={"ref": "a.csv:y"})
    assert merged.data.ref == "a.csv:y"
    assert merged.data.files == (Path("a.csv"),)


# --- hover_columns tri-state ---


def test_hover_columns_absent_defaults_to_none():
    d = DataConfig()
    assert d.hover_columns is None


def test_hover_columns_empty_list_becomes_empty_tuple(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[data]\nfiles = ["d.csv"]\nhover_columns = []\n', encoding="utf-8")
    d = ParityConfig.from_toml(p).data
    assert d.hover_columns == ()


def test_hover_columns_list_becomes_tuple_of_str(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[data]\nfiles = ["d.csv"]\nhover_columns = ["d.csv:a", "d.csv:b"]\n',
        encoding="utf-8",
    )
    d = ParityConfig.from_toml(p).data
    assert d.hover_columns == ("d.csv:a", "d.csv:b")


def test_hover_columns_bare_string_raises(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[data]\nfiles = ["d.csv"]\nhover_columns = "package"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="expected a list"):
        ParityConfig.from_toml(p)


def test_hover_columns_absent_in_toml_is_none(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[data]\nfiles = ["d.csv"]\n', encoding="utf-8")
    assert ParityConfig.from_toml(p).data.hover_columns is None
