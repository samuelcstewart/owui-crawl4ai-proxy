# AGENTS.md

Guidance for AI agents and contributors working in this repo.

## Scope

This repo is the **source of truth for the `owui-crawl4ai-proxy` container
image**. The image is consumed by the cluster via
`samuelcstewart/fluxcd` at `apps/opti/open-webui/crawl4ai-proxy/` (the
fluxcd kustomization references this image by tag + digest).

Changes here should be small, reviewable, and focused on the proxy's
HTTP contract with Open WebUI and crawl4ai. Do not redesign the
service or refactor unrelated code.

## Conventions

- **Language**: Python 3.12+, type-checked with `ty`.
- **Linting**: `ruff check` + `ruff format`. No warnings allowed.
- **Tests**: `pytest`. New endpoints or error paths need tests.
- **Commits**: conventional commits (`feat:`, `fix:`, `build:`, etc.).
  52/72 rule. Rebase only — no merge commits.
- **Dependency updates**: edit `pyproject.toml`. The Dockerfile runs
  `uv sync --frozen` against the committed `uv.lock`, so adding a
  runtime dep requires `uv lock` to regenerate the lockfile.

## Build + publish

The image ships to `registry.lan.stew.foo/samuelcstewart/owui-crawl4ai-proxy`
as a multi-arch (`linux/amd64` + `linux/arm64`) OCI image index. The
canonical handoff is:

```
uv run poe docker-build
```

That task builds both platforms in parallel, assembles the manifest
list, and pushes it tagged as `:<git short SHA>` and `:latest` in a
single buildx invocation. The push log prints per-arch digests and the
list digest — those are the values the fluxcd kustomization should pin.

## What this repo is NOT

- Not a deployment repo. The kustomization lives in `samuelcstewart/fluxcd`.
- Not a crawl4ai config repo. The proxy talks to whatever
  `PROXY_CRAWL4AI_URL` points at; pinning the crawl4ai version is the
  cluster's job.
- Not a test target for Open WebUI itself. The proxy just satisfies
  Open WebUI's external loader contract.
