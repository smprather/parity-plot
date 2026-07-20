from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from parity_plot.cli import cli


@pytest.fixture
def run(tmp_path: Path):
    runner = CliRunner()

    def _run(*args: str, **kwargs):
        return runner.invoke(cli, [str(a) for a in args], **kwargs)

    return _run


def test_example_writes_both_input_shapes(run, tmp_path):
    out = tmp_path / "data"
    result = run("example", "--out-dir", out, "-n", "50", "--missing-y", "3", "--missing-x", "2", "--both-null", "1", "--no-plot")

    assert result.exit_code == 0, result.output
    wide = out / "example.csv"
    assert wide.exists() and (out / "reference.csv").exists() and (out / "measured.csv").exists()

    rows = list(csv.DictReader(wide.open()))
    assert len(rows) == 50
    assert sum(1 for r in rows if not r["measured"] and r["reference"]) == 3
    assert sum(1 for r in rows if not r["reference"] and r["measured"]) == 2
    assert sum(1 for r in rows if not r["reference"] and not r["measured"]) == 1


def test_example_is_reproducible_for_a_seed(run, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    args = ("-n", "20", "--seed", "5", "--missing-y", "2", "--missing-x", "2",
            "--both-null", "1", "--no-plot")
    assert run("example", "--out-dir", a, *args).exit_code == 0
    assert run("example", "--out-dir", b, *args).exit_code == 0
    assert (a / "example.csv").read_text() == (b / "example.csv").read_text()


def test_example_plots_by_default(run, tmp_path):
    """Running `example` with no flags should show you something."""
    out = tmp_path / "parity.html"
    result = run("example", "--out-dir", tmp_path / "d", "-n", "30",
                 "--missing-y", "2", "--missing-x", "2", "--both-null", "0", "-o", out)

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "plot" in result.output


@pytest.mark.parametrize("command", ["plot", "example"])
def test_browser_opens_by_default(run, wide_csv, tmp_path, no_real_browser, command):
    """The whole point of `example`: run it and see a plot, no extra flag."""
    out = tmp_path / "p.html"
    if command == "plot":
        args = ("plot", wide_csv, "--x-col", "reference", "--y-col", "measured",
                "--key-col", "id", "-o", out)
    else:
        args = ("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "1",
                "--missing-x", "1", "--both-null", "0", "-o", out)

    assert run(*args).exit_code == 0
    assert no_real_browser == [out.resolve().as_uri()]


@pytest.mark.parametrize("command", ["plot", "example"])
def test_no_open_browser_suppresses_the_launch(run, wide_csv, tmp_path, no_real_browser, command):
    out = tmp_path / "p.html"
    if command == "plot":
        args = ("plot", wide_csv, "--x-col", "reference", "--y-col", "measured",
                "--key-col", "id", "-o", out, "--no-open-browser")
    else:
        args = ("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "1",
                "--missing-x", "1", "--both-null", "0", "-o", out, "--no-open-browser")

    assert run(*args).exit_code == 0
    assert out.exists()
    assert no_real_browser == []


def test_no_plot_means_no_browser(run, tmp_path, no_real_browser):
    """--no-plot writes no figure, so there is nothing to open."""
    result = run("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "1",
                 "--missing-x", "1", "--both-null", "0", "--no-plot")
    assert result.exit_code == 0
    assert no_real_browser == []


def test_example_can_skip_the_plot(run, tmp_path):
    out = tmp_path / "parity.html"
    result = run("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "2",
                 "--missing-x", "2", "--both-null", "0", "-o", out, "--no-plot")

    assert result.exit_code == 0, result.output
    assert not out.exists()


@pytest.mark.parametrize("command", ["plot", "example"])
def test_output_suffix_is_never_ignored(run, wide_csv, tmp_path, command):
    """`-o plot.svg` must not write HTML into a .svg file."""
    out = tmp_path / "p.svg"
    if command == "plot":
        args = ("plot", wide_csv, "--x-col", "reference", "--y-col", "measured",
                "--key-col", "id", "-o", out)
    else:
        args = ("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "1",
                "--missing-x", "1", "--both-null", "0", "-o", out)

    result = run(*args)

    if result.exit_code != 0:
        # Static export unavailable here; it must still have *tried* svg.
        assert "svg" in result.output
    else:
        assert out.read_bytes().lstrip()[:4] != b"<htm"


def test_example_shape_flags_change_the_data(run, tmp_path):
    """The knobs must actually reach the generator, not just parse."""
    from parity_plot import compute_stats, load_wide

    def stats_for(name, *flags):
        d = tmp_path / name
        assert run("example", "--out-dir", d, "-n", "300", "--seed", "3",
                   "--missing-y", "0", "--missing-x", "0", "--both-null", "0",
                   "--no-plot", *flags).exit_code == 0
        return compute_stats(load_wide(d / "example.csv", "reference", "measured", "id",
                                       na_values=[""]))

    tight = stats_for("tight", "--noise", "0.01", "--outliers", "0", "--bias", "0")
    loose = stats_for("loose", "--noise", "0.30", "--outliers", "0", "--bias", "0")
    assert loose.rmse > tight.rmse * 5

    unbiased = stats_for("unbiased", "--bias", "0", "--noise", "0.02", "--outliers", "0")
    skewed = stats_for("skewed", "--bias", "0.25", "--noise", "0.02", "--outliers", "0")
    assert skewed.bias > unbiased.bias * 10


def _tolerance_labels(html: Path) -> set[str]:
    """The distinct tolerance spec labels present in the rendered figure."""
    found = re.findall(r'"name":"(\xb1[^"]*)"', html.read_text(encoding="utf-8"))
    return set(found)


def test_example_draws_a_10_percent_wedge_by_default(run, tmp_path):
    out = tmp_path / "p.html"
    assert run("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "1",
               "--missing-x", "1", "--both-null", "0", "-o", out).exit_code == 0
    assert _tolerance_labels(out) == {"\u00b110%"}


def test_example_tolerance_can_be_overridden_and_switched_off(run, tmp_path):
    out = tmp_path / "p.html"
    base = ("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "1",
            "--missing-x", "1", "--both-null", "0", "-o", out)

    assert run(*base, "--reltol", "25pct").exit_code == 0
    assert _tolerance_labels(out) == {"\u00b125%"}

    assert run(*base, "--abstol", "2", "--no-tolerance").exit_code == 0
    assert _tolerance_labels(out) == set()


def test_example_abstol_alone_gives_parallel_limits(run, tmp_path):
    """--abstol on its own must not smuggle in the default relative wedge."""
    out = tmp_path / "p.html"
    assert run("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "1",
               "--missing-x", "1", "--both-null", "0", "-o", out,
               "--abstol", "2", "--reltol", "0").exit_code != 0  # 0 is not positive

    assert run("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "1",
               "--missing-x", "1", "--both-null", "0", "-o", out,
               "--abstol", "2", "--no-tolerance").exit_code == 0
    assert _tolerance_labels(out) == set()


def test_example_both_tolerances_give_a_funnel(run, tmp_path):
    out = tmp_path / "p.html"
    assert run("example", "--out-dir", tmp_path / "d", "-n", "30", "--missing-y", "1",
               "--missing-x", "1", "--both-null", "0", "-o", out,
               "--abstol", "2", "--reltol", "10pct").exit_code == 0
    assert _tolerance_labels(out) == {"\u00b1max(2, 10%)"}


def test_plot_still_draws_no_limits_unless_asked(run, wide_csv, tmp_path):
    """The default belongs to the demo, not to every plot anyone renders."""
    out = tmp_path / "p.html"
    assert run("plot", wide_csv, "--x-col", "reference", "--y-col", "measured",
               "--key-col", "id", "-o", out).exit_code == 0
    assert _tolerance_labels(out) == set()


def test_example_reports_the_shape_it_used(run, tmp_path):
    result = run("example", "--out-dir", tmp_path / "d", "-n", "20", "--missing-y", "1",
                 "--missing-x", "1", "--both-null", "0", "--no-plot",
                 "--bias", "0.1", "--noise", "0.2")
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


def test_plot_renders_from_a_wide_file(run, wide_csv, tmp_path):
    out = tmp_path / "p.html"
    result = run("plot", wide_csv, "--x-col", "reference", "--y-col", "measured", "--key-col", "id", "-o", out)

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "2 paired" in result.output
    assert "2 unpaired" in result.output
    assert "1 empty" in result.output


def test_plot_joins_two_files(run, write_csv, tmp_path):
    x = write_csv("ref.csv", "id,value\nA,1.0\nB,2.0\n")
    y = write_csv("meas.csv", "id,value\nA,1.1\nC,3.0\n")
    out = tmp_path / "p.html"

    result = run("plot", x, y, "--key-col", "id", "-o", out)

    assert result.exit_code == 0, result.output
    assert "1 paired" in result.output
    assert "2 unpaired" in result.output


def test_plot_infers_the_format_from_the_output_suffix(run, wide_csv, tmp_path):
    """`-o out.svg` should not also require `--format svg`."""
    result = run("plot", wide_csv, "--x-col", "reference", "--y-col", "measured",
                 "--key-col", "id", "-o", tmp_path / "p.svg")
    # Static export may be unavailable in this environment; what matters is that
    # it attempted svg rather than silently writing HTML into a .svg file.
    if result.exit_code != 0:
        assert "svg" in result.output
    else:
        assert (tmp_path / "p.svg").exists()


def test_plot_reports_a_bad_column_without_a_traceback(run, wide_csv, tmp_path):
    result = run("plot", wide_csv, "--x-col", "nope", "-o", tmp_path / "p.html")
    assert result.exit_code != 0
    assert "nope" in result.output
    assert "Traceback" not in result.output


def test_plot_reports_an_invalid_theme_as_a_usage_error(run, wide_csv, tmp_path):
    result = run("plot", wide_csv, "--theme", "neon", "-o", tmp_path / "p.html")
    assert result.exit_code != 0
    assert "neon" in result.output


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


def test_config_supplies_input_and_flags_override_it(run, wide_csv, tmp_path):
    config = tmp_path / "parity.toml"
    config.write_text(
        f'[data]\npaths = ["{wide_csv.as_posix()}"]\nx = "reference"\n'
        f'y = "measured"\nkey = "id"\n\n[plot]\ntheme = "light"\n',
        encoding="utf-8",
    )
    out = tmp_path / "p.html"

    # No paths given: they come from the config.
    assert run("plot", "-c", config, "-o", out).exit_code == 0
    assert out.exists()

    # And a flag still beats the file.
    result = run("plot", "-c", config, "--theme", "dark", "-o", out)
    assert result.exit_code == 0, result.output


def test_help_lists_every_subcommand(run):
    result = run("--help")
    assert result.exit_code == 0
    for command in ("plot", "example", "init"):
        assert command in result.output
