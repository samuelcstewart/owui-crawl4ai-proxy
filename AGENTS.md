# AGENTS.md

Guidance for AI agents and contributors working in this repo.

## Scope

This repo is the **source of truth for the `owui-crawl4ai-proxy` container
image**. The image is consumed by anything that wants to feed Open WebUI
an external web loader backed by crawl4ai. Changes here should be small,
reviewable, and focused on the proxy's HTTP contract with Open WebUI and
crawl4ai. Do not redesign the service or refactor unrelated code.

## Conventions

- **Language**: Python 3.14+, type-checked with `ty`.
- **Linting**: `ruff check` + `ruff format`. No warnings allowed.
- **Tests**: `pytest`. New endpoints or error paths need tests.
- **Commits**: conventional commits (`feat:`, `fix:`, `build:`, etc.).
  52/72 rule. Rebase only — no merge commits.
- **Dependency updates**: edit `pyproject.toml`. The Dockerfile runs
  `uv sync --frozen` against the committed `uv.lock`, so adding a
  runtime dep requires `uv lock` to regenerate the lockfile.

## Open WebUI contract

The proxy implements the Open WebUI 0.9.x external web loader
contract. That contract is set by OWUI's
`ExternalWebLoader.lazy_load` (see
`backend/open_webui/retrieval/loaders/external_web.py` in the OWUI
repo) — when in doubt, that source is the source of truth, not this
proxy's README.

`POST /load`:

- Request: `{"urls": ["...", "..."]}` — a batch. OWUI sends up to 20
  URLs at a time.
- Response: a JSON array of langchain `Document` (`page_content` +
  `metadata`), one per input URL, in the same order.
- The proxy does not validate any inbound `Authorization` header.
  OWUI's `ExternalWebLoader` sends one (its
  `EXTERNAL_WEB_LOADER_API_KEY`); the proxy ignores it. The proxy
  is designed to run on a trusted local network alongside OWUI and
  crawl4ai — neither direction enforces auth by default.

## Auth posture

The proxy intentionally does no auth validation:

- Inbound: no dependency reads `Authorization`. Any header (or no
  header) is accepted on `/load`.
- Outbound: the lifespan attaches `Authorization: Bearer` to
  upstream `/crawl` calls only when `PROXY_CRAWL4AI_API_TOKEN` is
  set. Unset = upstream calls go without auth.

This is a deliberate trust posture for "next to OWUI on a local
network", not an oversight. If the deployment ever crosses a trust
boundary, that's the deployment's job to enforce (NetworkPolicy,
sidecar, ingress) — not the proxy's.

Changes to this contract are breaking for the OWUI side. Bump the
minor version in `pyproject.toml` and call out the change in the PR
description.

## Build

The image is built with buildx. The bundled `docker-compose.yml` does
this for local dev:

```
docker compose build
```

For a multi-arch (`linux/amd64` + `linux/arm64`) image loaded into
the local Docker daemon:

```
poe build
```

Requires Docker 29+ with the containerd image store (snapshotter)
enabled. That's what makes `buildx build --load` accept a
multi-platform build; on classic single-platform storage you'll get
an error.

## Publish

A GitHub Actions workflow at `.github/workflows/ci.yml` runs on every
push to `main`, every `v*.*.*` tag, and every pull request against
`main`, and on manual dispatch. Two jobs:

- `test` — `uv sync` + `uv run poe check` (ruff + format-check + ty +
  pytest). Runs first; the build job depends on it.
- `build` — multi-arch (linux/amd64 + linux/arm64) `buildx build`.
  On `push` events, pushes the result to GHCR. On `pull_request`
  events, builds for verification only (`push: false`).

The published image lives at:

```
ghcr.io/samuelcstewart/owui-crawl4ai-proxy
```

Tag scheme on push events:

- main push → `:main`, `:<short-sha>`, `:latest`
- `v0.1.0` tag → `:v0.1.0`, `:v0.1`, `:v0`, `:<short-sha>`

Visibility inherits from the repo (public). The `GITHUB_TOKEN` in the
runner has `packages: write` via the workflow's `permissions` block.

## What this repo is NOT

- Not a deployment repo. Bring the image up however you like
  (`docker run`, compose, Kubernetes, etc.) and point
  `PROXY_CRAWL4AI_URL` at your crawl4ai instance.
- Not a crawl4ai config repo. The proxy talks to whatever
  `PROXY_CRAWL4AI_URL` points at; pinning the crawl4ai version is
  downstream of this project.
- Not a test target for Open WebUI itself. The proxy just satisfies
  Open WebUI's external loader contract.

## Publishing

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs lint +
typecheck + tests + multi-arch build on every PR, and the same plus
a push to GHCR on every merge to `main` or `v*.*.*` tag:

```
ghcr.io/samuelcstewart/owui-crawl4ai-proxy
```

Tag scheme:

- main pushes → `:main`, `:<short-sha>`, `:latest`
- `v0.1.0` tag → `:v0.1.0`, `:v0.1`, `:v0`, `:<short-sha>`

PR builds run the same `buildx` invocation with `push: false`, so PRs
get a Dockerfile regression check (and the test suite) but never
produce a throwaway GHCR image.

Pullable directly:

```bash
docker pull ghcr.io/samuelcstewart/owui-crawl4ai-proxy:latest
```
