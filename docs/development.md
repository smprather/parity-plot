# Developing parity-plot

How to set up a machine to build, test, and release this project. The core
toolchain is small — Python 3.14 and [uv](https://docs.astral.sh/uv/) — and
everything else is needed only for a specific feature. Each section below says
what it is for and how to check it works.

## Core toolchain

| Tool | Why | Check |
| --- | --- | --- |
| Python `>=3.14` | the project's floor (see `CLAUDE.md`) | `uv run python -V` |
| [uv](https://docs.astral.sh/uv/) | manages the interpreter, venv and lockfile | `uv --version` |
| git | version control | `git --version` |

```bash
uv sync          # runtime + dev deps in .venv, including the designer
uv run pytest    # the full suite
```

There is no `pip` and no `requirements.txt`; `uv.lock` is authoritative and CI
runs `uv sync --locked`. The normal change gate is `./check-tier-1`; the release
gate is `./check-tier-2` (tier 2 is a superset: it reruns tier 1, runs the full
suite, builds the sdist/wheel, smokes the wheel in an isolated environment, and
builds the tabbed-report example). Raw commands are useful when diagnosing one
layer:

```bash
uv run ruff check .          # lint (E/F/I); must print "All checks passed!"
uv run ruff format .         # formatter; keeps the tree formatted
uv run ty check parity_plot  # type-check the shipped library; 0 diagnostics
uv run pytest                # full suite
```

## Feature-specific tools

### Plot previews need a browser

`parity-plot plot` and `parity-plot example` open the result in the default
browser. On a headless machine pass `--no-open-browser`; nothing else is needed.

```bash
uv run parity-plot example                              # regenerate data/, plot, open
uv run parity-plot plot parity.toml --no-open-browser -o out.html
```

### Static image export needs a headless Chrome

PNG/SVG/PDF output renders through kaleido, which drives a Chrome it downloads
once. HTML output needs none of it.

```bash
uv run plotly_get_chrome    # one-time; the only missing piece is the browser
```

`kaleido` is a required dependency, so a headless Chrome is the only thing that
can be absent — but kaleido's error names kaleido itself. `plot.py::_export_hint`
untangles the two; if the export path changes, keep it accurate.

### The shared demo server

Port **8085** is reserved for the parity-plot demo. Serve the working demo at
`http://localhost:8085` so there is one stable URL to reload, and stop any other
listener on that port first. Do not accept the launcher's fallback to a random
port for demo runs.

### Running the suite on a slow NFS mount (Docker)

`./check-slow-nfs` builds `tools/slow-nfs/Dockerfile` and runs the suite with
every `tmp_path` on an NFS mount behind a deliberately slow link — this is how
the designer's NFS bugs (event-loop stalls, saves that outlast a debounce) are
reproduced. It is the only dev-box requirement that needs Docker.

Requirements:

- **Docker Engine or Docker Desktop**, with `--privileged` containers allowed
  (the container mounts NFS and shapes its own loopback with `tc`). The script
  passes `--privileged` itself.
- **The `buildx` plugin / BuildKit.** The Dockerfile has a
  `RUN --mount=type=secret` for the optional proxy CA; the *legacy* builder
  rejects it with `the --mount option requires BuildKit`, which aborts the
  build. Docker Desktop bundles buildx. A CLI-only Docker install may not:
  `docker buildx version` will fail with `unknown command`, and Docker then
  reports `BuildKit is enabled but the buildx component is missing`. Install
  the plugin (or let the build fall back) with:

  ```bash
  mkdir -p ~/.docker/cli-plugins
  BUILDX_VERSION=v0.37.1   # latest tag from github.com/docker/buildx/releases
  arch=$(uname -m); case "$arch" in x86_64) arch=amd64;; aarch64) arch=arm64;; esac
  curl -sSL -o ~/.docker/cli-plugins/docker-buildx \
    "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-${arch}"
  chmod +x ~/.docker/cli-plugins/docker-buildx
  docker buildx version
  ```

  Then build with BuildKit explicitly, which is also a no-op when buildx is
  already the default:

  ```bash
  DOCKER_BUILDKIT=1 ./check-slow-nfs
  ```

- **Host kernel extras for the *realistic* path** (optional): an NFS client
  (`nfs`/`nfsv4` modules) and `sch_netem`. Mainstream distribution kernels and
  Docker Desktop have both. Minimal kernels (microVMs, some CI runners) have
  neither; the container then falls back to `fuse-nfs` plus a userspace delay
  relay and prints:

  ```text
  [slow-nfs] server=ganesha latency=proxy (rtt 40 ms) client=fuse mount=/mnt/nfs
  [slow-nfs] note: fallback path in use -- the host kernel lacks an NFS client and sch_netem.
  ```

  The fallback still puts every file operation behind real NFS RPCs over a slow
  link, but timings are indicative only — attribute-caching conclusions need the
  kernel client. See `tools/slow-nfs/README.md` for the knobs (`NFS_RTT_MS`,
  `NFS_DELAY`, `NFS_CLIENT`, `NFS_MOUNT_OPTS`, …) and recorded runs.

### Releases need the GitHub CLI

Shipping a release uses `gh` against the `origin` remote. Check it is
installed and authenticated:

```bash
gh --version
gh auth status      # must report a logged-in account
```

The version scheme, bump policy, and the exact ship flow are in `CLAUDE.md`
(section **Releases**). In short: run `./check-tier-2`, branch, commit, merge
`--no-ff` to `main`, `git tag -a vYYYY.M.N`, push `main` and the tag, then
`gh release create`.

## Sandboxed or restricted environments

Managed agent sandboxes often expose the home directory as read-only while the
workspace and `/tmp` stay writable. `uv` locks and creates temporary files under
`~/.cache/uv`, so commands can fail before they run with `Could not acquire lock`
/ `Read-only file system`. Point uv at a writable cache *on every command* (exec
calls do not preserve exported variables):

```bash
UV_CACHE_DIR=/tmp/parity-plot-uv-cache uv run pytest
UV_CACHE_DIR=/tmp/parity-plot-uv-cache uv sync
```

If `.venv` is already synced and no dependency change is needed, bypass uv
entirely — it is faster and avoids the cache lock:

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ty check parity_plot
```

Cache writability and network access are separate failures: `UV_CACHE_DIR` fixes
the read-only cache, and a blocked network needs the environment's escalation
mechanism. Never work around either with `pip` or a second environment.

## Testing the designer GUI

Logic lives in the browser-free modules (`state.py`, `session.py`,
`serialize.py`, `validation.py`, `view.py`) and is unit-tested directly. The
assembled page is driven in-process by `tests/designer/page_harness.py`, which
captures `build_app`'s page function, builds it inside a NiceGUI `Client` with
`core.loop` set, and dispatches clicks through NiceGUI's own `handle_event` —
exceptions are swallowed exactly as in production, so assert on outcomes.

`tests/designer/test_add_file_flow.py::test_add_file_through_the_browser_dialog`
is the pattern for a full GUI flow: it clicks **Add File**, waits for the async
browser listing, clicks the CSV, and asserts the commit reached both the config
and the auto-saved file on disk. New designer interactions should follow it —
wait on a condition (never a fixed sleep, which passes locally and fails under
`./check-slow-nfs`), and assert on observable results.
