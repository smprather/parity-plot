from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_check_tier_scripts_are_executable_valid_shell():
    for name in ("check-tier-1", "check-tier-2"):
        path = ROOT / name
        assert os.access(path, os.X_OK)
        subprocess.run(["bash", "-n", path], check=True)


def test_tier_1_contains_static_checks_and_representative_smokes():
    script = (ROOT / "check-tier-1").read_text(encoding="utf-8")

    for command in (
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run ty check parity_plot",
        "tests/test_config.py::test_round_trip_of_the_shipped_example",
        "tests/test_cli.py::test_plot_reads_a_toml_and_writes",
        "tests/designer/test_state.py::test_figure_comes_from_the_cli_code_path",
    ):
        assert command in script


def test_tier_2_contains_the_release_checks():
    script = (ROOT / "check-tier-2").read_text(encoding="utf-8")

    for command in (
        '"$ROOT/check-tier-1"',
        "uv run pytest -q",
        "uv build --out-dir",
        "uv run --isolated --no-project --with",
        "uv run examples/tabbed-report/build-report",
    ):
        assert command in script


def test_ci_runs_tier_2_only_for_release_tags_or_manual_request():
    workflow = (ROOT / ".github" / "workflows" / "checks.yml").read_text(
        encoding="utf-8"
    )

    assert 'tags: ["v*"]' in workflow
    assert "workflow_dispatch:" in workflow
    assert "startsWith(github.ref, 'refs/tags/v')" in workflow
    assert "inputs.tier == 'tier-2'" in workflow
    assert "needs: tier-1" in workflow
    assert "./check-tier-1" in workflow
    assert "./check-tier-2" in workflow
