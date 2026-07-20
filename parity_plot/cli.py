"""Command line interface, built on rich-click."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import rich_click as click

from . import examples
from .config import (
    BAND_STYLES,
    LEGEND_POSITIONS,
    NULL_MODES,
    OUTPUT_FORMATS,
    THEMES,
    ConfigError,
    ParityConfig,
)
from .data import DataError, load
from .plot import ExportError, build_figure, save
from .tol_spec import TolSpecError, build_tolerances
from .tolerance import parse_reltol

HELP_CONFIG = click.RichHelpConfiguration(
    text_markup="markdown",
    show_arguments=True,
    style_options_table_box="SIMPLE",
    option_groups={
        # Flag pairs are matched by their first declaration ("--log"), not by
        # the "--log/--no-log" spelling, or they fall into a leftover panel.
        "parity-plot plot": [
            {
                "name": "Input",
                "options": ["PATHS", "--config", "--x-col", "--y-col", "--key-col"],
            },
            {
                "name": "Appearance",
                "options": [
                    "--theme",
                    "--title",
                    "--x-label",
                    "--y-label",
                    "--log",
                    "--tol",
                    "--abstol",
                    "--reltol",
                    "--band-style",
                    "--nulls",
                    "--legend",
                    "--stats",
                ],
            },
            {
                "name": "Output",
                "options": ["--output", "--format", "--width", "--height", "--open-browser"],
            },
            {"name": "Help", "options": ["--help"]},
        ],
        "parity-plot example": [
            {"name": "Size", "options": ["--out-dir", "--count", "--seed"]},
            {
                "name": "Shape of the data",
                "options": [
                    "--x-min",
                    "--x-max",
                    "--bias",
                    "--noise",
                    "--noise-floor",
                    "--outliers",
                ],
            },
            {
                "name": "Missing records",
                "options": ["--missing-y", "--missing-x", "--both-null"],
            },
            {
                "name": "Plot",
                "options": [
                    "--plot",
                    "--output",
                    "--theme",
                    "--abstol",
                    "--reltol",
                    "--tol",
                    "--no-tolerance",
                    "--band-style",
                    "--legend",
                    "--width",
                    "--height",
                    "--open-browser",
                ],
            },
            {"name": "Help", "options": ["--help"]},
        ],
        "parity-plot design": [
            {"name": "Input", "options": ["PATHS", "--config"]},
            {"name": "Server", "options": ["--port", "--open-browser"]},
            {"name": "Help", "options": ["--help"]},
        ],
    },
    command_groups={
        "parity-plot": [
            {"name": "Plotting", "commands": ["plot", "design"]},
            {"name": "Getting started", "commands": ["example", "init"]},
        ]
    },
)


class RelTolParam(click.ParamType):
    """A relative tolerance: a ratio by default, or an explicit percentage.

    `0.1` and `10pct` both mean a tenth. A bare `10` is ten times the reading,
    not 10% -- inferring the unit is the error this spelling exists to avoid.
    """

    name = "ratio|N pct"

    def convert(self, value, param, ctx):
        if isinstance(value, float):
            return value
        try:
            return parse_reltol(value)
        except ValueError as exc:
            self.fail(str(exc), param, ctx)


RELTOL = RelTolParam()


def _infer_format(output: Path | None, fmt: str | None) -> str | None:
    """Take the output format from the filename when it wasn't given outright.

    Without this, `-o plot.png` silently writes HTML into a .png file.
    """
    if fmt is not None or output is None:
        return fmt
    suffix = output.suffix.lstrip(".").lower()
    return suffix if suffix in OUTPUT_FORMATS else fmt


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="parity-plot")
@click.rich_config(help_config=HELP_CONFIG)
def cli() -> None:
    """Plot two datasets against a 45° parity line.

    Start with `parity-plot example` to generate sample data, then
    `parity-plot plot data/example.csv` to render it.
    """


@cli.command()
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("-c", "--config", type=click.Path(dir_okay=False, path_type=Path), help="TOML config file.")
@click.option("--x-col", help="Column holding the reference values.")
@click.option("--y-col", help="Column holding the measured values.")
@click.option("--key-col", help="Column identifying each record (required to join two files).")
@click.option("--theme", type=click.Choice(THEMES), help="Colour theme.  [default: dark]")
@click.option("--title", help="Plot title.")
@click.option("--x-label", help="X axis label.  [default: column name]")
@click.option("--y-label", help="Y axis label.  [default: column name]")
@click.option("--log/--no-log", default=None, help="Use logarithmic axes.")
@click.option("--tol", "tol", multiple=True, help="A tolerance spec as `key=value,key=value` (repeatable). Keys: name, label, abstol, reltol, kind, color, style.")
@click.option("--abstol", type=float, help="Absolute tolerance in the data's own units.  Draws lines parallel to y = x.")
@click.option("--reltol", type=RELTOL, help="Relative tolerance as a ratio, or a percentage with a `pct` suffix (`0.1` = `10pct`).  Draws a wedge through the origin.")
@click.option("--band-style", type=click.Choice(BAND_STYLES), help="Draw the tolerance limits as lines or as a shaded band.  [default: lines]")
@click.option("--nulls", type=click.Choice(NULL_MODES), help="Show unpaired records as axis rug marks, or drop them.")
@click.option("--legend", type=click.Choice(LEGEND_POSITIONS), help="Where to put the legend.  [default: right]")
@click.option("--stats/--no-stats", "show_stats", default=None, help="Show the statistics box.")
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), help="Output file.  [default: parity.html]")
@click.option("--format", "fmt", type=click.Choice(OUTPUT_FORMATS), help="Output format.  [default: inferred from --output]")
@click.option("--width", type=int, help="Figure width in pixels.")
@click.option("--height", type=int, help="Figure height in pixels.")
@click.option("--open-browser/--no-open-browser", "open_browser", default=True, help="Open the result in the default browser after writing.  [default: open]")
def plot(
    paths: tuple[Path, ...],
    config: Path | None,
    x_col: str | None,
    y_col: str | None,
    key_col: str | None,
    theme: str | None,
    title: str | None,
    x_label: str | None,
    y_label: str | None,
    log: bool | None,
    tol: tuple[str, ...],
    abstol: float | None,
    reltol: float | None,
    band_style: str | None,
    nulls: str | None,
    legend: str | None,
    show_stats: bool | None,
    output: Path | None,
    fmt: str | None,
    width: int | None,
    height: int | None,
    open_browser: bool,
) -> None:
    """Render a parity plot from **PATHS**.

    One path reads a single wide file; two paths outer-join a file per dataset
    on the key column. With no paths, the input comes from the config file.
    """
    try:
        cfg = ParityConfig.from_toml(config) if config else ParityConfig()

        fmt = _infer_format(output, fmt)
        try:
            tolerances = build_tolerances(tol, abstol, reltol, band_style)
        except TolSpecError as exc:
            raise click.ClickException(str(exc)) from None
        cfg = cfg.merge(
            data={
                "paths": tuple(paths) or None,
                "x": x_col,
                "y": y_col,
                "key": key_col,
            },
            plot={
                "theme": theme,
                "title": title,
                "x_label": x_label,
                "y_label": y_label,
                "log": log,
                "tolerances": tolerances or None,
                "nulls": nulls,
                "legend": legend,
            },
            stats={"show": show_stats},
            output={
                "path": output,
                "format": fmt,
                "width": width,
                "height": height,
            },
        )

        data = load(cfg.data)
        figure = build_figure(data, cfg.plot, cfg.stats)
        written = save(figure, cfg.output)
    except (ConfigError, DataError, ExportError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None

    click.echo(
        f"Wrote {click.style(str(written), bold=True)} — "
        f"{data.n_paired:,} paired, {data.n_unpaired:,} unpaired, "
        f"{data.n_dropped:,} empty"
    )
    if open_browser:
        webbrowser.open(written.resolve().as_uri())


@cli.command()
@click.option("--out-dir", type=click.Path(file_okay=False, path_type=Path), default=Path("data"), show_default=True, help="Directory to write the CSVs into.")
@click.option("-n", "--count", type=int, default=1000, show_default=True, help="Number of records.")
@click.option("--seed", type=int, default=17, show_default=True, help="Random seed. The same seed always gives the same data.")
@click.option("--x-min", type=float, default=10.0, show_default=True, help="Low end of the reference range (central 95% of draws).")
@click.option("--x-max", type=float, default=100.0, show_default=True, help="High end of the reference range.")
@click.option("--bias", type=float, default=0.015, show_default=True, help="Systematic slope error as a fraction, e.g. `0.015` reads 1.5% high.")
@click.option("--noise", type=float, default=0.06, show_default=True, help="Gaussian scatter proportional to the value, as a fraction.")
@click.option("--noise-floor", type=float, default=0.4, show_default=True, help="Gaussian scatter in absolute units, which dominates near zero.")
@click.option("--outliers", type=float, default=0.01, show_default=True, help="Fraction of records thrown far off the line.  Use `0` for none.")
@click.option("--missing-y", type=int, help="Records with no measured value.  [default: 1.5% of -n]")
@click.option("--missing-x", type=int, help="Records with no reference value.  [default: 1.2% of -n]")
@click.option("--both-null", type=int, help="Records missing from both datasets.  [default: 0.2% of -n]")
@click.option("--plot/--no-plot", default=True, show_default=True, help="Also render the generated data.")
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), default=Path("parity.html"), show_default=True, help="Where to write the plot.")
@click.option("--theme", type=click.Choice(THEMES), help="Colour theme for the plot.  [default: dark]")
@click.option("--abstol", type=float, help="Absolute tolerance in the data's own units.  Draws lines parallel to y = x.")
@click.option("--reltol", type=RELTOL, default=0.10, show_default=True, help="Relative tolerance as a ratio, or a percentage with a `pct` suffix (`0.1` = `10pct`).  Draws a wedge through the origin.")
@click.option("--tol", "tol", multiple=True, help="A tolerance spec as `key=value,key=value` (repeatable). Keys: name, label, abstol, reltol, kind, color, style.")
@click.option("--no-tolerance", is_flag=True, help="Draw no tolerance limits at all.")
@click.option("--band-style", type=click.Choice(BAND_STYLES), help="Draw the tolerance limits as lines or as a shaded band.  [default: lines]")
@click.option("--legend", type=click.Choice(LEGEND_POSITIONS), help="Where to put the legend.  [default: right]")
@click.option("--width", type=int, help="Figure width in pixels.")
@click.option("--height", type=int, help="Figure height in pixels.")
@click.option("--open-browser/--no-open-browser", "open_browser", default=True, help="Open the plot in the default browser after writing.  [default: open]")
def example(
    out_dir: Path,
    count: int,
    seed: int,
    x_min: float,
    x_max: float,
    bias: float,
    noise: float,
    noise_floor: float,
    outliers: float,
    missing_y: int | None,
    missing_x: int | None,
    both_null: int | None,
    plot: bool,
    output: Path,
    theme: str | None,
    abstol: float | None,
    reltol: float | None,
    tol: tuple[str, ...],
    no_tolerance: bool,
    band_style: str | None,
    legend: str | None,
    width: int | None,
    height: int | None,
    open_browser: bool,
) -> None:
    """Generate example data and plot it.

    Writes both input shapes from the same draws: `example.csv` for wide mode,
    plus `reference.csv` and `measured.csv` for join mode.

    The shape of the data is adjustable, so you can see how the plot responds:

        parity-plot example --noise 0.25 --bias 0.1     # sloppy and skewed

        parity-plot example --noise 0.01 --outliers 0   # tight and clean
    """
    try:
        spec = examples.ExampleSpec(
            n=count,
            seed=seed,
            x_min=x_min,
            x_max=x_max,
            bias=bias,
            noise=noise,
            noise_floor=noise_floor,
            outlier_rate=outliers,
            n_missing_y=missing_y,
            n_missing_x=missing_x,
            n_both_null=both_null,
        )
        written = examples.write_all(out_dir, spec)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None

    click.echo(f"Wrote {spec.n:,} records:")
    click.echo(f"  wide  {click.style(str(written['wide']), bold=True)}")
    click.echo(
        f"  join  {click.style(str(written['reference']), bold=True)} + "
        f"{click.style(str(written['measured']), bold=True)}"
    )
    click.echo(
        f"  nulls {spec.n_missing_y} missing measured, "
        f"{spec.n_missing_x} missing reference, {spec.n_both_null} missing both"
    )
    click.echo(
        f"  shape {spec.bias:+.1%} bias, {spec.noise:.1%} noise, "
        f"{spec.outlier_rate:.1%} outliers"
    )

    if not plot:
        return

    try:
        if no_tolerance:
            tolerances: tuple = ()
        else:
            try:
                tolerances = build_tolerances(tol, abstol, reltol, band_style)
            except TolSpecError as exc:
                raise click.ClickException(str(exc)) from None
        cfg = ParityConfig().merge(
            data={"paths": (written["wide"],)},
            plot={
                "theme": theme,
                "tolerances": tolerances or None,
                "legend": legend,
            },
            output={
                "path": output,
                "format": _infer_format(output, None),
                "width": width,
                "height": height,
            },
        )
        data = load(cfg.data)
        written_plot = save(build_figure(data, cfg.plot, cfg.stats), cfg.output)
    except (ConfigError, DataError, ExportError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None

    click.echo(f"  plot  {click.style(str(written_plot), bold=True)}")
    if open_browser:
        webbrowser.open(written_plot.resolve().as_uri())


@cli.command(name="init")
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), default=Path("parity.toml"), show_default=True, help="Where to write the config.")
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
def init_config(output: Path, force: bool) -> None:
    """Write a starter `parity.toml` with every option documented."""
    from .config import EXAMPLE_TOML

    if output.exists() and not force:
        raise click.ClickException(
            f"{output} already exists; pass --force to overwrite it"
        )
    output.write_text(EXAMPLE_TOML, encoding="utf-8")
    click.echo(f"Wrote {click.style(str(output), bold=True)}")


@cli.command()
@click.argument(
    "paths",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("-c", "--config", type=click.Path(dir_okay=False, path_type=Path), help="TOML config file to open and save back to.")
@click.option("--port", type=int, default=8080, show_default=True, help="Port to serve on.  Falls back to a free port if taken.")
@click.option("--open-browser/--no-open-browser", "open_browser", default=True, help="Open the designer in the default browser.  [default: open]")
def design(
    paths: tuple[Path, ...],
    config: Path | None,
    port: int,
    open_browser: bool,
) -> None:
    """Open the interactive designer.

    Edit every plot setting against your real data and watch the result
    update, then save the settings back to a `parity.toml`.
    """
    from .designer import launch

    try:
        launch.run(
            data_paths=tuple(paths),
            config_path=config,
            port=port,
            open_browser=open_browser,
        )
    except (ConfigError, DataError, launch.MissingDependencyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None


def main() -> int:
    cli()
    return 0


if __name__ == "__main__":
    sys.exit(main())
