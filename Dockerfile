# syntax=docker/dockerfile:1.7
#
# Multi-stage build for owui-crawl4ai-proxy.
#
# Stage 1 (builder): uv + python:3.12-slim. Copy the project
# (pyproject.toml, uv.lock, README.md, src/), then `uv sync --frozen
# --no-dev --no-editable`.
#   --frozen      pin to the existing uv.lock; refuse to mutate it
#   --no-dev      skip the [dependency-groups.dev] group
#                 (pytest/ruff/ty/poethepoet aren't needed in the image)
#   --no-editable install the project as a real wheel rather than an
#                 editable install (uv's default). The runtime stage
#                 only copies /app/.venv, not /app/src, so a .pth-based
#                 editable install would fail to import the package.
#
# Runtime deps come from [project] dependencies in pyproject.toml --
# this Dockerfile does not name any specific package, so adding a
# runtime dep to pyproject.toml is the only place the image needs to
# be touched.
#
# Stage 2 (runtime): python:3.12-slim, non-root user, copy just the
# venv from the builder. uvicorn is the entrypoint.
#
# Note on the venv path: the venv is created at /app/.venv in BOTH
# stages. The console script's shebang (`#!/app/.venv/bin/python`) is
# baked in at venv creation time and must match a path that exists
# at runtime -- if the builder's venv lived at /build/.venv, the
# copied shebang would point to a non-existent interpreter.

# ---- Stage 1: builder -----------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# uv ships as a static binary -- no Python deps needed. Pin the same
# version the dev workflow uses (mise.toml) so lockfile resolution is
# identical between `uv sync` here and `uv sync` on a workstation.
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy the project metadata + lock + readme first so the dependency
# layer caches across source-only changes. README is required:
# hatchling (the build backend) validates the readme field declared
# in pyproject.toml.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# `uv sync --frozen --no-dev --no-editable` resolves runtime deps
# from pyproject.toml (no names hardcoded here) and installs the
# project as a non-editable wheel. The build cache mount keeps the
# uv download cache between builds. `--no-editable` is critical: by
# default uv creates a .pth file that points back to /app/src, which
# doesn't exist in the runtime image -- a non-editable install bakes
# the package into the venv's site-packages instead.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---- Stage 2: runtime -----------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Non-root: the proxy binds 0.0.0.0:8000 and egresses to crawl4ai.
# Static uid/gid so a host-side chown is predictable.
#
# We intentionally skip `groupadd`/`useradd` from the `passwd` package.
# Those binaries dynamically link against `libaudit.so.1` (for
# pam_tty_audit, lastlog, etc.), and `libaudit.so.1` triggers a
# known-bad QEMU-user-static emulation path under binfmt_misc on
# arm64 hosts -- the loader fails with "failed to map segment from
# shared object" when the linker mmap's the library under QEMU
# emulation. The result is a multi-arch build that succeeds on the
# host arch (where the native loader runs) and fails on the emulated
# arch. Since the build only needs an owner for the venv files and
# a uid for `USER`, the cheapest fix is to write the passwd/group
# entries directly via `printf` (no dynamic linking) and run the
# container as the numeric uid:gid.
RUN printf 'proxy:x:1001:1001:proxy:/app:/usr/sbin/nologin\n' >> /etc/passwd \
 && printf 'proxy:x:1001:\n'                          >> /etc/group

WORKDIR /app

# Copy the venv (with the project installed + uvicorn console script
# under bin/) from the builder. The source package is already inside
# the venv's site-packages thanks to `uv sync` installing the project
# itself -- no separate src/ copy needed at runtime.
# `--chown=proxy:proxy` resolves the names via the /etc/passwd and
# /etc/group entries written above.
COPY --from=builder --chown=proxy:proxy /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# uvicorn is installed by `uv sync` as a runtime dep (uvicorn[standard]
# in pyproject.toml). The app module is `owui_crawl4ai_proxy.main:app`,
# which creates the FastAPI instance at import time. The lifespan
# inside the app loads Settings from `PROXY_*` env vars on first
# request.
CMD ["uvicorn", "owui_crawl4ai_proxy.main:app", "--host", "0.0.0.0", "--port", "8000"]

# After the venv is owned by proxy, USER doesn't matter for read paths,
# but switch to it anyway so the process can't accidentally write to
# /app (a read-only root filesystem is a common container-hardening
# pattern; we want a fail-fast on a write attempt rather than a silent
# write).
USER proxy
