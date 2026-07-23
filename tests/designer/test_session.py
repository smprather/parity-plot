# tests/designer/test_session.py
from __future__ import annotations

from pathlib import Path

import pytest

from parity_plot.config import ParityConfig
from parity_plot.designer.session import Session, StaleFileError

WIDE = """\
id,reference,test
A1,10.0,11.0
A2,20.0,
A3,30.0,29.0
"""


@pytest.fixture
def csv(tmp_path: Path) -> Path:
    path = tmp_path / "wide.csv"
    path.write_text(WIDE, encoding="utf-8")
    return path


def test_start_loads_data_from_paths(csv):
    session, config, data = Session.start((csv,), None)

    assert data.n_paired == 2
    assert len(data.missing_y) == 1
    assert config == ParityConfig().merge(
        data={"files": (csv,), "ref": "wide.csv:reference", "test": "wide.csv:test"}
    )


def test_start_loads_config_and_its_paths(csv, tmp_path: Path):
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text(
        f'[data]\nfiles = ["{csv.as_posix()}"]\nref = "wide.csv:reference"\n'
        f'test = "wide.csv:test"\n\n[plot]\ntheme = "light"\n',
        encoding="utf-8",
    )

    session, config, data = Session.start((), cfg_path)

    assert config.plot.theme == "light"
    assert data.n_paired == 2


def test_command_line_paths_win_over_the_config_file(csv, tmp_path: Path):
    other = tmp_path / "other.csv"
    other.write_text(WIDE, encoding="utf-8")
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text(
        f'[data]\nfiles = ["{other.as_posix()}"]\nref = "other.csv:reference"\n'
        f'test = "other.csv:test"\n',
        encoding="utf-8",
    )

    _, config, _ = Session.start((csv,), cfg_path)

    assert config.data.files == (csv,)


def test_dirty_only_once_the_config_changes(csv):
    session, config, _ = Session.start((csv,), None)

    assert not session.is_dirty(config)
    assert session.is_dirty(config.merge(plot={"theme": "light"}))


def test_save_writes_and_clears_dirty(csv, tmp_path: Path):
    session, config, _ = Session.start((csv,), None)
    edited = config.merge(plot={"theme": "light"})
    out = tmp_path / "saved.toml"

    written = session.save(edited, out)

    assert written == out
    assert ParityConfig.from_toml(out).plot.theme == "light"
    assert not session.is_dirty(edited)


def test_save_without_a_path_needs_one_from_somewhere(csv):
    session, config, _ = Session.start((csv,), None)
    with pytest.raises(ValueError, match="no config path"):
        session.save(config)


def test_save_reuses_the_loaded_path(csv, tmp_path: Path):
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text('[plot]\ntheme = "dark"\n', encoding="utf-8")
    session, config, _ = Session.start((csv,), cfg_path)

    written = session.save(config.merge(plot={"theme": "light"}))

    assert written == cfg_path
    assert ParityConfig.from_toml(cfg_path).plot.theme == "light"


def test_config_choices_returns_only_valid_parity_configs(tmp_path):
    from parity_plot.designer.session import config_choices

    (tmp_path / "good.toml").write_text(
        '[data]\nfiles = ["d.csv"]\nref = "d.csv:a"\ntest = "d.csv:b"\n', encoding="utf-8"
    )
    # parses but names no files -> not a parity-plot config
    (tmp_path / "nofiles.toml").write_text('[plot]\ntheme = "light"\n', encoding="utf-8")
    # not even valid TOML
    (tmp_path / "broken.toml").write_text("this = = nonsense\n", encoding="utf-8")
    # unrelated extension
    (tmp_path / "data.csv").write_text("id\n1\n", encoding="utf-8")

    names = [p.name for p in config_choices(tmp_path)]
    assert names == ["good.toml"]


def test_config_choices_empty_dir_is_empty(tmp_path):
    from parity_plot.designer.session import config_choices

    assert config_choices(tmp_path) == []


def test_autosave_writes_when_bound(csv, tmp_path):
    out = tmp_path / "bound.toml"
    out.write_text(
        f'[data]\nfiles = ["{csv.as_posix()}"]\n'
        f'ref = "wide.csv:reference"\ntest = "wide.csv:test"\n',
        encoding="utf-8",
    )
    session, config, _ = Session.start((), out)

    edited = config.merge(plot={"theme": "light"})
    written = session.autosave(edited)

    assert written == out
    from parity_plot.config import ParityConfig
    assert ParityConfig.from_toml(out).plot.theme == "light"
    assert not session.is_dirty(edited)  # disk now matches


def test_autosave_is_a_noop_when_unbound(csv):
    session, config, _ = Session.start((), None)   # no file bound
    assert session.autosave(config.merge(plot={"theme": "light"})) is None


def test_save_over_a_changed_file_no_longer_refuses(csv, tmp_path):
    out = tmp_path / "c.toml"
    session, config, _ = Session.start((), None)
    session.save(config, out)
    out.write_text(out.read_text() + "\n# edited externally\n", encoding="utf-8")
    # No StaleFileError any more: the designer owns the file.
    assert session.save(config.merge(plot={"theme": "light"}), out) == out