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


def test_stale_when_the_file_changed_underneath(csv, tmp_path: Path):
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text('[plot]\ntheme = "dark"\n', encoding="utf-8")
    session, config, _ = Session.start((csv,), cfg_path)

    assert not session.is_stale()
    cfg_path.write_text('[plot]\ntheme = "light"\n', encoding="utf-8")
    assert session.is_stale()


def test_saving_over_a_changed_file_refuses_until_forced(csv, tmp_path: Path):
    """Silently clobbering an edit made in another window loses work."""
    cfg_path = tmp_path / "parity.toml"
    cfg_path.write_text('[plot]\ntheme = "dark"\n', encoding="utf-8")
    session, config, _ = Session.start((csv,), cfg_path)
    cfg_path.write_text("[plot]\n# edited elsewhere\n", encoding="utf-8")

    with pytest.raises(StaleFileError):
        session.save(config)

    session.save(config, force=True)
    assert "dark" in cfg_path.read_text(encoding="utf-8")