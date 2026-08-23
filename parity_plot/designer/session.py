# parity_plot/designer/session.py
"""Where the designer's data and config came from, and where they go back to."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import ConfigError, ParityConfig
from ..data import ParityData, load
from .serialize import config_to_toml


def config_choices(directory: Path) -> list[Path]:
    """The parity-plot configs in ``directory``.

    Touchstone: the file parses as a ``ParityConfig`` and names at least one
    input file (``data.files``). A ``.toml`` that is malformed or unrelated is
    skipped, so the picker only offers files the designer can actually open.
    """
    out: list[Path] = []
    for path in sorted(Path(directory).glob("*.toml")):
        try:
            config = ParityConfig.from_toml(path)
        except ConfigError, ValueError, OSError:
            continue
        if config.data.files:
            out.append(path)
    return out


def config_choice_names(directory: Path, current: Path | None) -> list[str]:
    """Picker names, including a bound config outside the scanned directory."""
    names = [path.name for path in config_choices(directory)]
    if current is not None and current.name not in names:
        names.insert(0, current.name)
    return names


@dataclass
class Session:
    config_path: Path | None = None
    original_text: str | None = None
    disk_text: str | None = None
    saved_config: ParityConfig | None = None

    @classmethod
    def start(
        cls, data_paths: tuple[Path, ...], config_path: Path | None
    ) -> tuple[Session, ParityConfig, ParityData | None]:
        """Load config then data, with command-line paths winning.

        Same precedence as the CLI: an explicit path on the command line beats
        whatever the config file names. With no files anywhere, `data` is None
        and the designer starts empty.
        """
        if config_path is not None:
            text = Path(config_path).read_text(encoding="utf-8")
            config = ParityConfig.from_toml(config_path)
        else:
            text = None
            config = ParityConfig()

        if data_paths:
            overrides: dict = {"files": tuple(data_paths)}
            # Command-line paths win over the config file's files, so any ref/test
            # pointing at the old files no longer resolves. Re-derive them for a
            # single file (the first two numeric columns); for two files the user
            # must supply a config that names the right columns.
            if len(data_paths) == 1:
                from ..sources import open_sources

                cols = open_sources(data_paths, config.data.na_values).numeric_columns(
                    config.data.na_values
                )
                if len(cols) < 2:
                    from ..data import DataError

                    raise DataError(
                        f"{data_paths[0].name}: need at least two numeric columns "
                        f"for ref/test; found {len(cols)} ({cols})"
                    )
                overrides["ref"] = cols[0]
                overrides["test"] = cols[1]
            config = config.merge(data=overrides)

        # No files chosen yet -> start empty rather than erroring; the file
        # browser fills this in.
        data = load(config.data) if config.data.files else None
        session = cls(
            config_path=Path(config_path) if config_path else None,
            original_text=text,
            disk_text=text,
            saved_config=config,
        )
        return session, config, data

    def is_dirty(self, config: ParityConfig) -> bool:
        return config != self.saved_config

    def save(self, config: ParityConfig, path: Path | None = None) -> Path:
        target = Path(path) if path is not None else self.config_path
        if target is None:
            raise ValueError("no config path to save to; choose one with Save As")

        existing = target.read_text(encoding="utf-8") if target.exists() else None
        text = config_to_toml(config, existing=existing)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

        self.config_path = target
        self.disk_text = text
        self.saved_config = config
        return target

    def autosave(self, config: ParityConfig) -> Path | None:
        """Write ``config`` to the bound file, or nothing when unbound.

        The auto-save path: `app.refresh()` calls this after every change that
        leaves the config valid. Unbound (no file yet) is a no-op — a New Design
        or data-only launch has nowhere to write until Save As binds a name.
        """
        if self.config_path is None:
            return None
        return self.save(config, self.config_path)
