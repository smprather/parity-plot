"""How long does the designer's event loop stall while it works on a big CSV?

The NFS complaint was the reconnect overlay: a handler that blocks the asyncio
loop starves the websocket heartbeat. NiceGUI pings every 4 s and allows 2 s for
the answer, so a stall anywhere near 2 s is a dropped connection. File reads are
offloaded to threads now, but parsing is Python holding the GIL, and the figure,
table and inspector are rebuilt on the loop -- so "the I/O is off the loop" is
not the same as "the loop stays responsive". This measures it.

It builds the real designer page in-process (the harness from
``tests/designer/test_app_toolbar.py``), with a ticker task on the loop
recording every gap, and drives the phases a user does:

    page load       build the page; initial refresh and option read
    change test     pick another test column: option re-read, load, commit
    edit title      a sync panel commit: figure, table, inspector rebuilt

    uv run python tools/slow-nfs/loop_lag_probe.py --rows 200000 --dir /mnt/nfs/probe

Run it inside ./check-slow-nfs for NFS numbers, or anywhere for a local baseline.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import time
from pathlib import Path
from typing import Any

HEARTBEAT_BUDGET_S = 2.0  # NiceGUI's ping_timeout at the default reconnect_timeout


class Ticker:
    """Record how late each 10 ms tick fires; the lateness is the loop's stall."""

    def __init__(self, period: float = 0.01) -> None:
        self.period = period
        self.samples: list[tuple[float, float]] = []  # (when, lateness)

    async def run(self) -> None:
        while True:
            before = time.monotonic()
            await asyncio.sleep(self.period)
            now = time.monotonic()
            self.samples.append((now, now - before - self.period))

    def worst(self, start: float, end: float) -> float:
        return max((lag for t, lag in self.samples if start <= t <= end), default=0.0)


def write_csv(path: Path, rows: int) -> None:
    rng = random.Random(17)
    with path.open("w", encoding="utf-8") as f:
        f.write("id,reference,test,alt,temperature,package\n")
        for i in range(rows):
            ref = rng.uniform(1, 100)
            f.write(
                f"S{i:07d},{ref:.4f},{ref * rng.gauss(1, 0.05):.4f},"
                f"{ref * rng.gauss(1, 0.1):.4f},{rng.uniform(20, 120):.2f},"
                f"{rng.choice(('BGA', 'QFN', 'SOIC'))}\n"
            )


async def settle_until(predicate, timeout: float) -> float:
    start = time.monotonic()
    while not predicate():
        if time.monotonic() - start > timeout:
            raise TimeoutError("phase did not finish")
        await asyncio.sleep(0.02)
    return time.monotonic() - start


async def main(rows: int, directory: Path) -> None:
    from nicegui import Client, core, ui

    from parity_plot.designer import app as app_mod
    from parity_plot.designer.session import Session
    from parity_plot.sources import clear_cache

    directory.mkdir(parents=True, exist_ok=True)
    csv = directory / "big.csv"
    config_path = directory / "probe.toml"
    t0 = time.monotonic()
    write_csv(csv, rows)
    write_s = time.monotonic() - t0
    config_path.write_text(
        '[data]\nfiles = ["big.csv"]\nref = "big.csv:reference"\n'
        'test = "big.csv:test"\njoin = "id"\n',
        encoding="utf-8",
    )
    size_mb = csv.stat().st_size / 1e6
    os.chdir(directory)
    clear_cache()

    results: list[tuple[str, float, float]] = []
    ticker = Ticker()
    core.loop = asyncio.get_running_loop()
    tick_task = asyncio.create_task(ticker.run())

    # Launch reads the data before any server exists (launch.run), so it is
    # timed but cannot stall a loop.
    t0 = time.monotonic()
    session, config, data = Session.start((), config_path)
    launch_s = time.monotonic() - t0

    captured: dict[str, Any] = {}
    real_page = ui.page
    ui.page = lambda *a, **k: lambda func: captured.setdefault("page", func)  # type: ignore[assignment]
    state = app_mod.build_app(session, config, data)
    ui.page = real_page  # type: ignore[assignment]

    start = time.monotonic()
    with Client(page=real_page("/")) as client:
        captured["page"]()
    await asyncio.sleep(1.0)  # initial refresh + background option read
    results.append(
        ("page load", time.monotonic() - start, ticker.worst(start, time.monotonic()))
    )

    def element(label: str) -> Any:
        for el in client.elements.values():
            if el.props.get("label") == label:
                return el
        raise LookupError(label)

    start = time.monotonic()
    element("Test").value = "big.csv:alt"
    await settle_until(lambda: state.config.data.test == "big.csv:alt", 600)
    await asyncio.sleep(0.2)
    results.append(
        ("change test", time.monotonic() - start, ticker.worst(start, time.monotonic()))
    )

    start = time.monotonic()
    element("Title").value = "probe"
    await settle_until(lambda: state.config.plot.title == "probe", 60)
    await asyncio.sleep(0.5)
    results.append(
        ("edit title", time.monotonic() - start, ticker.worst(start, time.monotonic()))
    )

    tick_task.cancel()
    core.loop = None

    print(f"\n{rows:,} rows, {size_mb:.1f} MB at {csv}")
    print(
        f"write {write_s:.1f}s; launch load (before the server, no loop) {launch_s:.1f}s"
    )
    print(f"{'phase':<14}{'elapsed':>10}{'worst loop stall':>20}  heartbeat")
    for name, elapsed, worst in results:
        verdict = "at risk" if worst >= HEARTBEAT_BUDGET_S else "ok"
        print(f"{name:<14}{elapsed:>9.2f}s{worst * 1000:>17.0f} ms  {verdict}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=200_000)
    parser.add_argument("--dir", type=Path, default=Path("/mnt/nfs/probe"))
    args = parser.parse_args()
    asyncio.run(main(args.rows, args.dir.resolve()))
