# syntax=docker/dockerfile:1.7
#
# The test suite on an emulated slow NFS mount. Built and run by ./check-slow-nfs
# from the repo root; see tools/slow-nfs/README.md.
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
# A commit, not a branch: fuse-nfs is the fallback NFS client for kernels that
# have none, and the build must not drift underneath the emulation.
ARG FUSE_NFS_REF=6444bfc52db44ab93c8930e327a8802a08d2060e
ARG UV_VERSION=0.9.5

# An extra CA certificate is optional -- only for building behind a
# TLS-intercepting proxy: pass `--secret id=extra_ca,src=/path/to/ca.pem`.
RUN --mount=type=secret,id=extra_ca,required=false \
    set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl git \
        nfs-ganesha nfs-ganesha-vfs nfs-common rpcbind iproute2 kmod \
        python3 python3-pip \
        build-essential autoconf automake libtool pkg-config \
        libnfs-dev libfuse-dev; \
    if [ -f /run/secrets/extra_ca ]; then \
        cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra-ca.crt; \
        update-ca-certificates; \
    fi; \
    rm -rf /var/lib/apt/lists/*

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

RUN set -eux; \
    git clone https://github.com/sahlberg/fuse-nfs /tmp/fuse-nfs; \
    cd /tmp/fuse-nfs; \
    git checkout "$FUSE_NFS_REF"; \
    ./setup.sh; \
    ./configure; \
    make -j"$(nproc)"; \
    make install; \
    rm -rf /tmp/fuse-nfs

# uv from PyPI rather than its container image: PyPI is the one index every
# build environment can already reach.
RUN pip3 install --no-cache-dir --break-system-packages "uv==${UV_VERSION}"

ENV UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_CACHE_DIR=/opt/uv-cache \
    UV_PYTHON=3.14

WORKDIR /work
# Dependencies first, so editing the code does not re-download them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project
COPY . .
RUN uv sync --locked

COPY tools/slow-nfs/ganesha.conf /etc/ganesha/ganesha.conf
COPY tools/slow-nfs/entrypoint tools/slow-nfs/delay_proxy.py /usr/local/lib/slow-nfs/
RUN chmod +x /usr/local/lib/slow-nfs/entrypoint

ENTRYPOINT ["/usr/local/lib/slow-nfs/entrypoint"]
# Every test's tmp_path lives on the NFS mount, so each file the suite writes
# and reads -- CSVs, configs, auto-saves -- crosses the slow link.
CMD ["uv", "run", "--locked", "pytest", "-q", "-p", "no:cacheprovider", \
     "--basetemp=/mnt/nfs/pytest", "--durations=15"]
