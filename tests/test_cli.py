from __future__ import annotations

import csv
from pathlib import Path

import pytest
from click.testing import CliRunner

from parity_plot.cli import cli


@pytest.fixture
def run(tmp_path: Path):
    runner = CliRunner()

    def _run(*args, **kwargs):
        return runner.invoke(cli, [str(a) for a in args], **kwargs)

    return _run


def _write_config(path: Path, wide_csv: Path, extra: str = "") -> Path:
    path.write_text(
        f'[data]\nfiles = ["{wide_csv.as_posix()}"]\n'
        f'ref = "{wide_csv.name}:reference"\ntest = "{wide_csv.name}:test"\n'
        f'join = "id"\n{extra}',
        encoding="utf-8",
    )
    return path


# --- example: the generator (kept) ---


def test_example_writes_both_input_shapes(run, tmp_path):
    out = tmp_path / "data"
    result = run(
        "example",
        "--out-dir",
        out,
        "-n",
        "50",
        "--missing-y",
        "3",
        "--missing-x",
        "2",
        "--both-null",
        "1",
        "--no-plot",
    )

    assert result.exit_code == 0, result.output
    wide = out / "example.csv"
    assert (
        wide.exists()
        and (out / "reference.csv").exists()
        and (out / "measured.csv").exists()
    )

    rows = list(csv.DictReader(wide.open()))
    assert len(rows) == 50
    assert sum(1 for r in rows if not r["test"] and r["reference"]) == 3
    assert sum(1 for r in rows if not r["reference"] and r["test"]) == 2
    assert sum(1 for r in rows if not r["reference"] and not r["test"]) == 1


def test_example_is_reproducible_for_a_seed(run, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    args = (
        "-n",
        "20",
        "--seed",
        "5",
        "--missing-y",
        "2",
        "--missing-x",
        "2",
        "--both-null",
        "1",
        "--no-plot",
    )
    assert run("example", "--out-dir", a, *args).exit_code == 0
    assert run("example", "--out-dir", b, *args).exit_code == 0
    assert (a / "example.csv").read_text() == (b / "example.csv").read_text()


def test_example_plots_by_default(run, tmp_path):
    """Running `example` should show you something."""
    out = tmp_path / "parity.html"
    result = run(
        "example",
        "--out-dir",
        tmp_path / "d",
        "-n",
        "30",
        "--missing-y",
        "2",
        "--missing-x",
        "2",
        "--both-null",
        "0",
        "-o",
        out,
    )

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "plot" in result.output


def test_example_can_skip_the_plot(run, tmp_path):
    out = tmp_path / "parity.html"
    result = run(
        "example",
        "--out-dir",
        tmp_path / "d",
        "-n",
        "30",
        "--missing-y",
        "2",
        "--missing-x",
        "2",
        "--both-null",
        "0",
        "-o",
        out,
        "--no-plot",
    )

    assert result.exit_code == 0, result.output
    assert not out.exists()


def test_example_opens_browser_by_default(run, tmp_path, no_real_browser):
    out = tmp_path / "p.html"
    assert (
        run(
            "example",
            "--out-dir",
            tmp_path / "d",
            "-n",
            "30",
            "--missing-y",
            "1",
            "--missing-x",
            "1",
            "--both-null",
            "0",
            "-o",
            out,
        ).exit_code
        == 0
    )
    assert no_real_browser == [out.resolve().as_uri()]


def test_example_no_open_browser_suppresses_launch(run, tmp_path, no_real_browser):
    out = tmp_path / "p.html"
    assert (
        run(
            "example",
            "--out-dir",
            tmp_path / "d",
            "-n",
            "30",
            "--missing-y",
            "1",
            "--missing-x",
            "1",
            "--both-null",
            "0",
            "-o",
            out,
            "--no-open-browser",
        ).exit_code
        == 0
    )
    assert out.exists()
    assert no_real_browser == []


def test_no_plot_means_no_browser(run, tmp_path, no_real_browser):
    result = run(
        "example",
        "--out-dir",
        tmp_path / "d",
        "-n",
        "30",
        "--missing-y",
        "1",
        "--missing-x",
        "1",
        "--both-null",
        "0",
        "--no-plot",
    )
    assert result.exit_code == 0
    assert no_real_browser == []


def test_example_output_suffix_is_never_ignored(run, tmp_path):
    out = tmp_path / "p.svg"
    result = run(
        "example",
        "--out-dir",
        tmp_path / "d",
        "-n",
        "30",
        "--missing-y",
        "1",
        "--missing-x",
        "1",
        "--both-null",
        "0",
        "-o",
        out,
    )
    if result.exit_code != 0:
        assert "svg" in result.output
    else:
        assert out.read_bytes().lstrip()[:4] != b"<htm"


def test_example_shape_flags_change_the_data(run, tmp_path):
    """The knobs must actually reach the generator, not just parse."""
    from parity_plot import compute_stats
    from parity_plot.config import DataConfig
    from parity_plot.data import load

    def stats_for(name, *flags):
        d = tmp_path / name
        assert (
            run(
                "example",
                "--out-dir",
                d,
                "-n",
                "300",
                "--seed",
                "3",
                "--missing-y",
                "0",
                "--missing-x",
                "0",
                "--both-null",
                "0",
                "--no-plot",
                *flags,
            ).exit_code
            == 0
        )
        wide = d / "example.csv"
        return compute_stats(
            load(
                DataConfig(
                    files=(wide,), ref="example.csv:reference", test="example.csv:test"
                )
            )
        )

    tight = stats_for("tight", "--noise", "0.01", "--outliers", "0", "--bias", "0")
    loose = stats_for("loose", "--noise", "0.30", "--outliers", "0", "--bias", "0")
    assert loose.rmse > tight.rmse * 5

    unbiased = stats_for(
        "unbiased", "--bias", "0", "--noise", "0.02", "--outliers", "0"
    )
    skewed = stats_for("skewed", "--bias", "0.25", "--noise", "0.02", "--outliers", "0")
    assert skewed.bias > unbiased.bias * 10


def test_example_reports_the_shape_it_used(run, tmp_path):
    result = run(
        "example",
        "--out-dir",
        tmp_path / "d",
        "-n",
        "20",
        "--missing-y",
        "1",
        "--missing-x",
        "1",
        "--both-null",
        "0",
        "--no-plot",
        "--bias",
        "0.1",
        "--noise",
        "0.2",
    )
    assert "+10.0% bias" in result.output
    assert "20.0% noise" in result.output


@pytest.mark.parametrize(
    "flags, expected",
    [
        (("--x-min", "0"), "x_min must be positive"),
        (("--x-max", "1", "--x-min", "10"), "must be greater than"),
        (("--noise", "-1"), "cannot be negative"),
        (("--outliers", "5"), "fraction between 0 and 1"),
        (("-n", "0"), "at least one record"),
    ],
)
def test_example_rejects_impossible_shapes(run, tmp_path, flags, expected):
    result = run("example", "--out-dir", tmp_path / "d", "--no-plot", *flags)
    assert result.exit_code != 0
    assert expected in result.output.replace("\n", " ").replace("│", "")


def test_example_rejects_more_holes_than_records(run, tmp_path):
    result = run("example", "--out-dir", tmp_path / "d", "-n", "5", "--missing-y", "10")
    assert result.exit_code != 0
    assert "null records" in result.output
    assert "Traceback" not in result.output


def test_example_help_drops_appearance_flags(run):
    result = run("example", "--help")
    assert result.exit_code == 0
    assert "--noise" in result.output and "--bias" in result.output
    for gone in (
        "--theme",
        "--legend",
        "--abstol",
        "--reltol",
        "--band-style",
        "--width",
        "--height",
        "--tol",
    ):
        assert gone not in result.output


# --- plot: TOML-driven (new surface) ---


def test_plot_reads_a_toml_and_writes(run, wide_csv, tmp_path):
    cfg = _write_config(tmp_path / "parity.toml", wide_csv)
    out = tmp_path / "out.html"
    result = run("plot", cfg, "-o", out, "--no-open-browser")
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "2 paired" in result.output
    assert "2 unpaired" in result.output
    assert "1 empty" in result.output


def test_plot_defaults_to_parity_toml(run, wide_csv, tmp_path, monkeypatch):
    _write_config(tmp_path / "parity.toml", wide_csv)
    monkeypatch.chdir(tmp_path)
    result = run("plot", "-o", tmp_path / "out.html", "--no-open-browser")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out.html").exists()


def test_plot_missing_config_points_at_init(run, tmp_path):
    result = run("plot", tmp_path / "nope.toml", "--no-open-browser")
    assert result.exit_code != 0
    assert "init" in result.output
    assert "Traceback" not in result.output


def test_plot_opens_browser_by_default(run, wide_csv, tmp_path, no_real_browser):
    cfg = _write_config(tmp_path / "parity.toml", wide_csv)
    out = tmp_path / "out.html"
    assert run("plot", cfg, "-o", out).exit_code == 0
    assert no_real_browser == [out.resolve().as_uri()]


def test_plot_output_suffix_is_never_ignored(run, wide_csv, tmp_path):
    cfg = _write_config(tmp_path / "parity.toml", wide_csv)
    out = tmp_path / "p.svg"
    result = run("plot", cfg, "-o", out, "--no-open-browser")
    if result.exit_code != 0:
        assert "svg" in result.output
    else:
        assert out.read_bytes().lstrip()[:4] != b"<htm"


def test_plot_reports_a_bad_column_without_a_traceback(run, wide_csv, tmp_path):
    cfg = tmp_path / "parity.toml"
    cfg.write_text(
        f'[data]\nfiles = ["{wide_csv.as_posix()}"]\n'
        f'ref = "{wide_csv.name}:nope"\ntest = "{wide_csv.name}:test"\njoin = "id"\n',
        encoding="utf-8",
    )
    result = run("plot", cfg, "-o", tmp_path / "p.html", "--no-open-browser")
    assert result.exit_code != 0
    assert "nope" in result.output
    assert "Traceback" not in result.output


def test_plot_reports_unknown_toml_key_without_a_traceback(run, tmp_path):
    cfg = tmp_path / "parity.toml"
    cfg.write_text('[data]\nfiles = ["x.csv"]\ntheme = "neon"\n', encoding="utf-8")
    result = run("plot", cfg, "--no-open-browser")
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_plot_help_has_no_appearance_flags(run):
    result = run("plot", "--help")
    assert result.exit_code == 0
    for gone in (
        "--theme",
        "--ref",
        "--test",
        "--join",
        "--group",
        "--tol",
        "--legend",
        "--width",
        "--nulls",
        "--abstol",
    ):
        assert gone not in result.output
    assert "init" in result.output  # docstring routes to init


# --- init + top-level help ---


def test_init_writes_a_config_that_loads(run, tmp_path):
    from parity_plot.config import ParityConfig

    out = tmp_path / "parity.toml"
    assert run("init", "-o", out).exit_code == 0
    assert ParityConfig.from_toml(out).plot.theme == "dark"


def test_init_refuses_to_clobber_without_force(run, tmp_path):
    out = tmp_path / "parity.toml"
    out.write_text("# mine\n", encoding="utf-8")

    result = run("init", "-o", out)
    assert result.exit_code != 0
    assert "already exists" in result.output
    assert out.read_text(encoding="utf-8") == "# mine\n"

    assert run("init", "-o", out, "--force").exit_code == 0
    assert "already exists" not in out.read_text(encoding="utf-8")


def test_help_lists_every_subcommand(run):
    result = run("--help")
    assert result.exit_code == 0
    for command in ("plot", "example", "init", "design"):
        assert command in result.output
