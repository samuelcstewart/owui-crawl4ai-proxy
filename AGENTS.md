# AGENTS.md

Guidance for AI agents and contributors working in this repo.

## Scope

This repo is the **source of truth for the `owui-crawl4ai-proxy` container
image**. The image is consumed by anything that wants to feed Open WebUI
an external web loader backed by crawl4ai. Changes here should be small,
reviewable, and focused on the proxy's HTTP contract with Open WebUI and
crawl4ai. Do not redesign the service or refactor unrelated code.

## Conventions

- **Language**: Python 3.12+, type-checked with `ty`.
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

For a single-arch image loaded into the local Docker daemon:

```
poe build
```

For a multi-arch (`linux/amd64` + `linux/arm64`) build saved to a
tarball (handy for offline transfer; no registry needed):

```
poe build-multiarch
```

## What this repo is NOT

- Not a deployment repo. Bring the image up however you like
  (`docker run`, compose, Kubernetes, etc.) and point
  `PROXY_CRAWL4AI_URL` at your crawl4ai instance.
- Not a crawl4ai config repo. The proxy talks to whatever
  `PROXY_CRAWL4AI_URL` points at; pinning the crawl4ai version is
  downstream of this project.
- Not a test target for Open WebUI itself. The proxy just satisfies
  Open WebUI's external loader contract.
