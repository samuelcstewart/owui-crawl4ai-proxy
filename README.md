# owui-crawl4ai-proxy

A small HTTP service that bridges [Open WebUI](https://github.com/open-webui/open-webui)
0.9.x's external web loader interface to a [crawl4ai](https://github.com/unclecode/crawl4ai)
instance. The proxy:

- Accepts `POST /load` requests shaped like the Open WebUI external loader
  contract (`{"urls": ["...", "..."]}` — a batch).
- Internally forwards to crawl4ai's `POST /crawl` endpoint with the bearer
  token crawl4ai 0.9.0+ requires.
- Returns a JSON array of langchain-style `Document` (`page_content` +
  `metadata`) — one per input URL, in order.
- Exposes `GET /health` for liveness probes — checks that crawl4ai is
  reachable.

## Stack

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) for package management
- [ruff](https://docs.astral.sh/ruff/) for lint + format
- [ty](https://docs.astral.sh/ty/) for type checking
- FastAPI + uvicorn for the HTTP server
- httpx for upstream calls
- pydantic / pydantic-settings for config + request/response models

## Configuration

All env vars are prefixed `PROXY_`:

| Variable | Default | Description |
|---|---|---|
| `PROXY_CRAWL4AI_URL` | `http://crawl4ai:11235` | Upstream crawl4ai base URL |
| `PROXY_CRAWL4AI_API_TOKEN` | *(unset)* | Optional Bearer token for upstream crawl4ai calls. When set, the proxy attaches `Authorization: Bearer` to every upstream request. When unset, upstream calls go without auth — only safe when crawl4ai is reachable only on a trusted in-cluster network. |
| `PROXY_REQUEST_TIMEOUT` | `60.0` | Upstream request timeout (seconds) |

The proxy never validates any inbound `Authorization` header on
`POST /load`. OWUI's `ExternalWebLoader` sends one by default and
the proxy simply ignores it. This proxy is designed to run on a
trusted local network alongside Open WebUI and crawl4ai; both
directions are unauthenticated by default.

## Local development

```bash
uv sync                              # install all deps
uv run pytest                        # run tests
uv run ruff check                    # lint
uv run ruff format                   # format
uv run ty check                      # type check
uv run uvicorn owui_crawl4ai_proxy.main:app --reload --port 8000
```

## Docker

```bash
docker compose up --build            # brings up crawl4ai 0.9.0 + this proxy
curl -X POST http://localhost:8000/load \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://example.com"]}' | jq
```

For a standalone build of the proxy image only:

```bash
poe build                            # multi-arch (amd64+arm64), --load (Docker 29+)
```

## API

### `POST /load`

Open WebUI 0.9.x's `ExternalWebLoader` sends `POST /load` with a
`urls` batch (up to 20 URLs at a time). The proxy accepts that
exact shape and returns one `Document` per URL in the same order:

```json
// Request
{"urls": ["https://example.com", "https://example.org"]}

// Response (JSON array of langchain Documents, in input order)
[
  {
    "page_content": "Markdown text for example.com...",
    "metadata": {"source": "https://example.com", "title": "..."}
  },
  {
    "page_content": "Markdown text for example.org...",
    "metadata": {"source": "https://example.org", "title": "..."}
  }
]
```

The proxy does not validate any inbound `Authorization` header on
`/load`. OWUI may send one (its `ExternalWebLoader` always does)
and the proxy ignores it.

### `GET /health`

```json
{"status": "ok"}    // 200 if upstream crawl4ai is reachable
{"status": "degraded"}  // 503 if upstream is unreachable
```

## Publishing

A GitHub Actions workflow builds and pushes a multi-arch image to
GHCR. The same workflow also runs on every PR (build + tests, no
push) as a Dockerfile regression gate:

```
ghcr.io/samuelcstewart/owui-crawl4ai-proxy
```

Tag scheme:

- main pushes → `:main`, `:<short-sha>`, `:latest`
- `v0.1.0` tag → `:v0.1.0`, `:v0.1`, `:v0`, `:<short-sha>`

PR builds run the same `buildx` invocation with `push: false`, so PRs
get a build verification (and the test suite) but never produce a
throwaway GHCR image.

Pullable directly:

```bash
docker pull ghcr.io/samuelcstewart/owui-crawl4ai-proxy:latest
```

## License

MIT.
