# Slow-NFS test harness

The designer's worst bugs have been NFS bugs: a read that blocks the event loop
past the websocket heartbeat, a save that outlasts a debounce, a cached `stat`
that lags a rewrite. None of them show on a local SSD. This harness runs the
test suite — or anything else — with its files on an NFS mount behind a
deliberately slow link, in one Docker container, so the result is the same on
any machine with Docker.

```bash
./check-slow-nfs                       # the full suite, every tmp_path on NFS
NFS_RTT_MS=200 ./check-slow-nfs        # a much slower link
./check-slow-nfs uv run pytest tests/designer -x --basetemp=/mnt/nfs/t
./check-slow-nfs bash                  # a shell with /mnt/nfs mounted
```

## What is inside the container

| Piece | Normal path | Fallback (used automatically) |
| --- | --- | --- |
| Server | NFS-Ganesha (userspace), exporting a tmpfs | — |
| Latency | `tc` `prio` qdisc on `lo` with `netem delay` on port 2049 only | `delay_proxy.py`, a TCP relay that delays each direction |
| Client | the kernel NFS client (`mount -t nfs4`, v4.1), default attribute caching | `fuse-nfs` (libnfs over FUSE, NFSv3) |

The server is userspace so the host kernel needs no `nfsd`. Only NFS traffic is
delayed: the tests that boot the designer and fetch its page over loopback keep
full speed. Mount options are left at their defaults (attribute caching on), because
that is what users get — pass `NFS_MOUNT_OPTS=noac` to see the uncached worst case.

The container reports what it actually used and a measured cost per small-file
create, e.g.

```
[slow-nfs] server=ganesha latency=netem (rtt 40 ms) client=kernel mount=/mnt/nfs
[slow-nfs] measured: 123 ms per small-file create+write+close
```

## Requirements and fallbacks

`--privileged` (to mount and to run `tc`). The realistic path needs two things
from the **host kernel**: the NFS client (`nfs`/`nfsv4` modules) and
`sch_netem`. Mainstream distribution kernels and Docker Desktop have both.

Minimal kernels (microVMs, some CI runners) may have neither. Then the container
falls back to `fuse-nfs` and/or the delay relay and says so. The fallback still
puts every file operation behind real NFSv4 RPCs over a slow link, but it is not
the kernel client: its caching and its request pipelining differ. Timings from it
are indicative; conclusions about attribute caching need the kernel path.

One visible difference: `fuse-nfs` does not retry a stale file handle, so a read
that races a rename-over (the designer's atomic config save) can fail with ENOENT
where the kernel client would quietly retry. Tests that poll a file read an
`OSError` as "not yet" for that reason.

Force a path with `NFS_CLIENT=kernel|fuse` and `NFS_DELAY=netem|proxy`; a forced
path that is unavailable fails loudly instead of falling back.

## Building behind a TLS-intercepting proxy

Only for unusual build environments:

```bash
EXTRA_CA_CERT=/path/to/proxy-ca.pem \
SLOW_NFS_BUILD_ARGS="--network host --build-arg HTTPS_PROXY=$HTTPS_PROXY" \
./check-slow-nfs
```

The run itself needs no network. Do not add `--network host` to
`SLOW_NFS_RUN_ARGS`: the container shapes *its own* loopback with `tc`, and in the
host's network namespace that would be the host's loopback.
