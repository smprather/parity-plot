"""A TCP relay that delivers every chunk a fixed time after it arrived, each way.

The fallback latency for kernels built without ``sch_netem`` (so ``tc ... netem
delay`` is unavailable -- some CI and microVM kernels). The NFS client talks to
this relay, the relay to the server. Each direction is timestamped on receipt
and released in order once its delay has passed, so pipelined RPCs overlap the
way they do on a real long link: this adds latency, not a bandwidth cap.

Stdlib only; runs under the container's system Python.

    python3 delay_proxy.py LISTEN_PORT UPSTREAM_HOST:PORT ONE_WAY_MS
"""

from __future__ import annotations

import asyncio
import sys


async def _pump(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, delay: float
) -> None:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[float, bytes]] = asyncio.Queue()

    async def release() -> None:
        while True:
            due, chunk = await queue.get()
            wait = due - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
        writer.close()

    releaser = asyncio.create_task(release())
    try:
        while True:
            chunk = await reader.read(1 << 16)
            queue.put_nowait((loop.time() + delay, chunk))
            if not chunk:
                break
    except ConnectionError:
        queue.put_nowait((loop.time(), b""))
    await releaser


async def _serve(listen_port: int, upstream: str, delay: float) -> None:
    host, _, port = upstream.rpartition(":")

    async def handle(
        client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        try:
            server_reader, server_writer = await asyncio.open_connection(
                host, int(port)
            )
        except OSError:
            client_writer.close()
            return
        await asyncio.gather(
            _pump(client_reader, server_writer, delay),
            _pump(server_reader, client_writer, delay),
            return_exceptions=True,
        )

    server = await asyncio.start_server(handle, "127.0.0.1", listen_port)
    async with server:
        await server.serve_forever()


def main() -> None:
    listen_port, upstream, one_way_ms = sys.argv[1:4]
    asyncio.run(_serve(int(listen_port), upstream, float(one_way_ms) / 1000))


if __name__ == "__main__":
    main()
