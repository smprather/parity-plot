"""Command line interface, built on rich-click."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import rich_click as click

from . import examples
from .config import (
    OUTPUT_FORMATS,
    ConfigError,
    ParityConfig,
)
from .data import DataError, load
from .plot import ExportError, build_figure, save

HELP_CONFIG = click.RichHelpConfiguration(
    text_markup="markdown",
    show_arguments=True,
    style_options_table_box="SIMPLE",
    option_groups={
        "parity-plot plot": [
            {"name": "Input", "options": ["CONFIG"]},
            {"name": "Output", "options": ["--output", "--open-browser"]},
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
            {"name": "Plot", "options": ["--plot", "--output", "--open-browser"]},
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

    Every plot and data setting lives in a TOML config. Get started with
    `parity-plot init` to write a fully-commented `parity.toml`, edit it (by
    hand or with `parity-plot design`), then `parity-plot plot`. Or run
    `parity-plot example` to generate sample data and see a plot immediately.
    """


@cli.command()
@click.argument(
    "config",
    required=False,
    default="parity.toml",
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Override where the plot is written. A path only — it does not change how the plot looks.",
)
@click.option(
    "--open-browser/--no-open-browser",
    "open_browser",
    default=True,
    help="Open the result in the default browser after writing.  [default: open]",
)
def plot(config: Path, output: Path | None, open_browser: bool) -> None:
    """Render a parity plot from a TOML **CONFIG** (default `parity.toml`).

    Every plot and data setting lives in the TOML — there are no appearance
    flags. Run `parity-plot init` to write a fully-commented template, or
    `parity-plot design` to edit it visually against your data. The only flag
    here, `-o/--output`, changes *where* the plot is written, not how it looks.
    """
    try:
        if not Path(config).exists():
            raise click.ClickException(
                f"config file not found: {config}. Run `parity-plot init` to "
                f"create one, or pass the path to an existing TOML config."
            )
        cfg = ParityConfig.from_toml(config)
        if output is not None:
            cfg = cfg.merge(
                output={"path": output, "format": _infer_format(output, None)}
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
@click.option(
    "--out-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("data"),
    show_default=True,
    help="Directory to write the CSVs into.",
)
@click.option(
    "-n",
    "--count",
    type=int,
    default=1000,
    show_default=True,
    help="Number of records.",
)
@click.option(
    "--seed",
    type=int,
    default=17,
    show_default=True,
    help="Random seed. The same seed always gives the same data.",
)
@click.option(
    "--x-min",
    type=float,
    default=10.0,
    show_default=True,
    help="Low end of the reference range (central 95% of draws).",
)
@click.option(
    "--x-max",
    type=float,
    default=100.0,
    show_default=True,
    help="High end of the reference range.",
)
@click.option(
    "--bias",
    type=float,
    default=0.015,
    show_default=True,
    help="Systematic slope error as a fraction, e.g. `0.015` reads 1.5% high.",
)
@click.option(
    "--noise",
    type=float,
    default=0.06,
    show_default=True,
    help="Gaussian scatter proportional to the value, as a fraction.",
)
@click.option(
    "--noise-floor",
    type=float,
    default=0.4,
    show_default=True,
    help="Gaussian scatter in absolute units, which dominates near zero.",
)
@click.option(
    "--outliers",
    type=float,
    default=0.01,
    show_default=True,
    help="Fraction of records thrown far off the line.  Use `0` for none.",
)
@click.option(
    "--missing-y",
    type=int,
    help="Records with no measured value.  [default: 1.5% of -n]",
)
@click.option(
    "--missing-x",
    type=int,
    help="Records with no reference value.  [default: 1.2% of -n]",
)
@click.option(
    "--both-null",
    type=int,
    help="Records missing from both datasets.  [default: 0.2% of -n]",
)
@click.option(
    "--plot/--no-plot",
    default=True,
    show_default=True,
    help="Also render the generated data.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("parity.html"),
    show_default=True,
    help="Where to write the plot.",
)
@click.option(
    "--open-browser/--no-open-browser",
    "open_browser",
    default=True,
    help="Open the plot in the default browser after writing.  [default: open]",
)
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
    open_browser: bool,
) -> None:
    """Generate example data and plot it.

    Writes both input shapes from the same draws: `example.csv` (a wide file
    with `reference`, `test`, and extra `package`/`vendor`/`temperature`
    columns), plus `reference.csv` and `measured.csv` for join mode.

    The shape of the data is adjustable, so you can see how the plot responds:

        parity-plot example --noise 0.25 --bias 0.1     # sloppy and skewed

        parity-plot example --noise 0.01 --outliers 0   # tight and clean

    Appearance is set in TOML, not here — to style the plot, run
    `parity-plot init` then edit `parity.toml` (or use `parity-plot design`).
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
        wide = written["wide"]
        cfg = ParityConfig().merge(
            data={
                "files": (wide,),
                "ref": f"{wide.name}:reference",
                "test": f"{wide.name}:test",
            },
            output={"path": output, "format": _infer_format(output, None)},
        )
        data = load(cfg.data)
        written_plot = save(build_figure(data, cfg.plot, cfg.stats), cfg.output)
    except (ConfigError, DataError, ExportError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None

    click.echo(f"  plot  {click.style(str(written_plot), bold=True)}")
    if open_browser:
        webbrowser.open(written_plot.resolve().as_uri())


@cli.command(name="init")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("parity.toml"),
    show_default=True,
    help="Where to write the config.",
)
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
@click.option(
    "-c",
    "--config",
    type=click.Path(dir_okay=False, path_type=Path),
    help="TOML config file to open and save back to.",
)
@click.option(
    "--port",
    type=int,
    default=8080,
    show_default=True,
    help="Port to serve on.  Falls back to a free port if taken.",
)
@click.option(
    "--open-browser/--no-open-browser",
    "open_browser",
    default=True,
    help="Open the designer in the default browser.  [default: open]",
)
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
