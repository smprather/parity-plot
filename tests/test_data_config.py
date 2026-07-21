# tests/test_data_config.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ConfigError, DataConfig, ParityConfig


def test_defaults_are_empty():
    d = DataConfig()
    assert d.files == () and d.ref is None and d.test is None
    assert d.join is None and d.group is None


def test_parses_the_new_shape(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[data]\nfiles = ["meas.csv", "sim.csv"]\n'
        'ref = "meas.csv:voltage"\ntest = "sim.csv:voltage"\n'
        'join = "id"\ngroup = "meas.csv:batch"\n',
        encoding="utf-8",
    )
    d = ParityConfig.from_toml(p).data
    assert d.files == (Path("meas.csv"), Path("sim.csv"))
    assert d.ref == "meas.csv:voltage"
    assert d.test == "sim.csv:voltage"
    assert d.join == "id"
    assert d.group == "meas.csv:batch"


def test_join_and_group_are_optional(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text('[data]\nfiles = ["d.csv"]\nref = "d.csv:a"\ntest = "d.csv:b"\n', encoding="utf-8")
    d = ParityConfig.from_toml(p).data
    assert d.join is None and d.group is None


@pytest.mark.parametrize("key, value", [
    ("paths", '["d.csv"]'), ("x", '"reference"'), ("y", '"measured"'),
    ("key", '"id"'), ("value", '"value"'),
])
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