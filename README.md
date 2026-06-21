# owui-crawl4ai-proxy

A small HTTP service that bridges [Open WebUI](https://github.com/open-webui/open-webui)'s
external web loader interface to an internal [crawl4ai](https://github.com/unclecode/crawl4ai)
instance. The proxy:

- Accepts `POST /load` requests shaped like the Open WebUI external loader contract
  (`{"url": "..."}`).
- Internally forwards to crawl4ai's `POST /crawl` endpoint with the bearer token
  crawl4ai 0.9.0+ requires.
- Returns a langchain-style `Document` (`page_content` + `metadata`).
- Exposes `GET /health` for kubelet probes — checks that crawl4ai is reachable.

The image is published to `registry.lan.stew.foo/samuelcstewart/owui-crawl4ai-proxy`
and is wired into the cluster via
`samuelcstewart/fluxcd` at `apps/opti/open-webui/crawl4ai-proxy/`.

## Stack

- Python 3.12+
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
| `PROXY_CRAWL4AI_URL` | `http://crawl4ai.crawl4ai.svc:80` | Upstream crawl4ai base URL |
| `PROXY_CRAWL4AI_API_TOKEN` | *(required)* | Bearer token for crawl4ai 0.9.0+ |
| `PROXY_REQUEST_TIMEOUT` | `60.0` | Upstream request timeout (seconds) |

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
docker build -t registry.lan.stew.foo/samuelcstewart/owui-crawl4ai-proxy:0.1.0 .
docker compose up --build            # brings up crawl4ai 0.8.9 + this proxy
curl -X POST http://localhost:8000/load \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}' | jq
```

## API

### `POST /load`

```json
// Request
{"url": "https://example.com"}

// Response (langchain Document)
{
  "page_content": "Markdown text...",
  "metadata": {"source": "https://example.com", "title": "..."}
}
```

### `GET /health`

```json
{"status": "ok"}    // 200 if upstream crawl4ai is reachable
{"status": "degraded"}  // 503 if upstream is unreachable
```
