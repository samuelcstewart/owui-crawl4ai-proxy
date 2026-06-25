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

A GitHub Actions workflow at `.github/workflows/publish.yml` builds
the multi-arch image on every push to `main` and every `v*.*.*` tag,
and pushes the result to GitHub Container Registry:

```
ghcr.io/samuelcstewart/owui-crawl4ai-proxy
```

Tag scheme:

- main pushes → `:main`, `:<short-sha>`, `:latest`
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

A GitHub Actions workflow (`.github/workflows/publish.yml`) builds
the multi-arch image and pushes it to GHCR:

```
ghcr.io/samuelcstewart/owui-crawl4ai-proxy
```

Pullable directly:

```bash
docker pull ghcr.io/samuelcstewart/owui-crawl4ai-proxy:latest
```
