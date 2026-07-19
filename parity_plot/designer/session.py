# parity_plot/designer/session.py
"""Where the designer's data and config came from, and where they go back to."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import ConfigError, ParityConfig
from ..data import ParityData, load
from .serialize import config_to_toml


class StaleFileError(RuntimeError):
    """The config file changed on disk after it was loaded."""


@dataclass
class Session:
    config_path: Path | None = None
    original_text: str | None = None
    disk_text: str | None = None
    saved_config: ParityConfig | None = None

    @classmethod
    def start(
        cls, data_paths: tuple[Path, ...], config_path: Path | None
    ) -> tuple[Session, ParityConfig, ParityData]:
        """Load config then data, with command-line paths winning.

        Same precedence as the CLI: an explicit path on the command line beats
        whatever the config file names.
        """
        if config_path is not None:
            text = Path(config_path).read_text(encoding="utf-8")
            config = ParityConfig.from_toml(config_path)
        else:
            text = None
            config = ParityConfig()

        if data_paths:
            config = config.merge(data={"paths": tuple(data_paths)})

        data = load(config.data)
        session = cls(
            config_path=Path(config_path) if config_path else None,
            original_text=text,
            disk_text=text,
            saved_config=config,
        )
        return session, config, data

    def is_dirty(self, config: ParityConfig) -> bool:
        return config != self.saved_config

    def is_stale(self) -> bool:
        """True when the file changed since we last read or wrote it."""
        if self.config_path is None or not self.config_path.exists():
            return False
        return self.config_path.read_text(encoding="utf-8") != self.disk_text

    def save(
        self, config: ParityConfig, path: Path | None = None, force: bool = False
    ) -> Path:
        target = Path(path) if path is not None else self.config_path
        if target is None:
            raise ValueError("no config path to save to; choose one with Save As")

        writing_in_place = path is None or Path(path) == self.config_path
        if writing_in_place and not force and self.is_stale():
            raise StaleFileError(
                f"{target} changed on disk since it was opened; "
                f"saving now would discard that edit"
            )

        existing = target.read_text(encoding="utf-8") if target.exists() else None
        text = config_to_toml(config, existing=existing)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

        self.config_path = target
        self.disk_text = text
        self.saved_config = config
        return target