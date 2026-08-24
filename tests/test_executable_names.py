from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKIP_DIRS = {".git", ".venv", "__pycache__"}


def test_console_scripts_are_kebab_case():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = data.get("project", {}).get("scripts", {})

    assert names
    assert [name for name in names if not KEBAB.fullmatch(name)] == []


def test_repo_executables_are_kebab_case():
    bad: list[str] = []
    for directory, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for filename in filenames:
            path = Path(directory, filename)
            if _is_executable_script(path) and not KEBAB.fullmatch(path.name):
                bad.append(path.relative_to(ROOT).as_posix())

    assert bad == []


def _is_executable_script(path: Path) -> bool:
    if os.access(path, os.X_OK):
        return True
    try:
        with path.open("rb") as file:
            return file.read(2) == b"#!"
    except OSError:
        return False
