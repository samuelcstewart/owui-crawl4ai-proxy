"""FastAPI app: bridges Open WebUI's external loader to crawl4ai.

Endpoints
---------
- `POST /load`  — Open WebUI 0.9.x external loader contract.
                  Body: `{"urls": ["..."]}`. Response: JSON array of
                  langchain `Document` (one per input URL, in order).
- `GET /health` — kubelet probe target. Probes upstream crawl4ai `/health`
                  (no auth required) and returns 200/503.

Auth posture
------------
This proxy is designed to run on a trusted local network alongside
Open WebUI (and crawl4ai). Neither direction is authenticated:

- Inbound (`/load`): the proxy never reads the inbound
  `Authorization` header. OWUI's `ExternalWebLoader` sends one by
  default; the proxy ignores it.
- Outbound (`/crawl`): if `PROXY_CRAWL4AI_API_TOKEN` is set, the
  proxy attaches `Authorization: Bearer` to every upstream call.
  If unset, the proxy sends no Authorization header. crawl4ai 0.9.0+
  requires auth by default, so leaving the token unset implies that
  crawl4ai is reachable only on a network you trust.

Error mapping for `/load`
-------------------------
- pydantic validation failure (422)             → logged + 422 to caller
- crawl4ai `success: false` or empty `results`  → 502 to caller
- `len(results) != len(urls)` upstream bug      → 502 to caller
- upstream 401 / 403 / 5xx                      → propagate status + generic body
- upstream connection error / timeout           → 502
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from owui_crawl4ai_proxy.config import Settings, load_settings
from owui_crawl4ai_proxy.models import CrawlRequest, Document, LoadRequest

logger = logging.getLogger("owui_crawl4ai_proxy")

# Endpoints we call on the upstream crawl4ai service.
_CRAWL_PATH = "/crawl"
_HEALTH_PATH = "/health"

# HTTP status codes we propagate verbatim from upstream. Other non-2xx
# codes fall through to the generic 502 mapping.
_PROPAGATE_UPSTREAM_STATUSES: frozenset[int] = frozenset({401, 403, 500, 502, 503, 504})

_router = APIRouter()


# ---------------------------------------------------------------------------
# FastAPI app factory
# ---------------------------------------------------------------------------


def create_app(
    settings: Settings | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    Parameters
    ----------
    settings:
        Optional pre-built `Settings`. If `None`, `load_settings()` is
        called from inside the lifespan. Tests pass a `Settings`
        constructed with explicit overrides so the env is irrelevant.
    http_client:
        Optional pre-built `httpx.AsyncClient`. If `None`, one is created
        inside the lifespan. Tests pass a `MockTransport`-backed client
        to short-circuit upstream calls.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Manage the upstream httpx client lifecycle."""
        if http_client is not None:
            # Tests pass a client they own; we must not close it.
            app.state.http_client = http_client
            app.state.owns_client = False
            try:
                yield
            finally:
                app.state.http_client = None
            return

        cfg = settings or load_settings()
        # The crawl4ai bearer is optional. When unset we attach no
        # Authorization header — that's the entire "local network"
        # posture of this proxy.
        upstream_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if cfg.crawl4ai_api_token:
            upstream_headers["Authorization"] = f"Bearer {cfg.crawl4ai_api_token}"
        client = httpx.AsyncClient(
            base_url=str(cfg.crawl4ai_url),
            timeout=httpx.Timeout(cfg.request_timeout),
            headers=upstream_headers,
        )
        app.state.http_client = client
        app.state.owns_client = True
        try:
            yield
        finally:
            await client.aclose()
            app.state.http_client = None

    app = FastAPI(
        title="owui-crawl4ai-proxy",
        version="0.3.0",
        lifespan=lifespan,
        # Hide OpenAPI by default — callers pass a pre-built Settings
        # in tests, which means docs are off; otherwise expose /docs for
        # local exploration.
        docs_url="/docs" if (settings is None) else None,
        redoc_url=None,
    )

    # Log 422s so a future request-shape drift (e.g. an Open WebUI
    # upgrade changing the loader contract) is visible in proxy logs
    # instead of only in the caller's logs.
    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # `exc.errors()` can carry non-JSON-serialisable objects (e.g.
        # the original `ValueError` instance under `ctx['error']`).
        # FastAPI's stock handler runs the same payload through
        # `jsonable_encoder`; mirror that so the response is
        # serialisable.
        logger.warning(
            "rejected request to %s: %s",
            request.url.path,
            exc.errors(),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": jsonable_encoder(exc.errors())},
        )

    app.include_router(_router)
    return app


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_http_client(request: Request) -> httpx.AsyncClient:
    """FastAPI dependency that yields the lifespan-managed httpx client."""
    client = getattr(request.app.state, "http_client", None)
    if client is None:  # pragma: no cover — lifespan guarantees this
        raise RuntimeError("http_client not initialised; lifespan did not run")
    return client


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@_router.post("/load", response_model=list[Document])
async def load(
    body: LoadRequest,
    client: httpx.AsyncClient = Depends(get_http_client),
) -> list[Document]:
    """Open WebUI 0.9.x external web loader contract.

    Accepts `{"urls": ["...", "..."]}` and returns a JSON array of
    langchain `Document` (one per input URL, in the same order).
    """
    upstream_body = CrawlRequest(urls=body.urls).model_dump(mode="json")
    try:
        resp = await client.post(_CRAWL_PATH, json=upstream_body)
    except httpx.HTTPError as exc:
        logger.warning("upstream connection error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="upstream unreachable",
        ) from exc

    if resp.status_code in _PROPAGATE_UPSTREAM_STATUSES:
        # Forward auth/permission/server errors with a generic body so
        # we don't leak upstream internals to Open WebUI.
        raise HTTPException(status_code=resp.status_code, detail="upstream error")

    # For any other non-2xx, treat as a generic bad-gateway to keep the
    # public contract simple (Open WebUI only needs to know "ok vs not").
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="upstream error",
        )

    payload = _safe_json(resp)
    if not isinstance(payload, dict) or not payload.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="upstream reported failure",
        )

    results = payload.get("results") or []
    if not isinstance(results, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="upstream returned malformed results",
        )

    if not results:
        # `success: true` with an empty list is a meaningful state —
        # the upstream call completed cleanly but there's nothing to
        # return. Map to 502 with a dedicated message so callers can
        # distinguish this from a misaligned batch (below).
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="upstream returned no results",
        )

    # crawl4ai's contract: results[i] corresponds to urls[i]. A length
    # mismatch means upstream returned a partial / misaligned batch,
    # which we can't safely map back to the caller's URLs.
    if len(results) != len(body.urls):
        logger.warning(
            "upstream returned %d results for %d urls",
            len(results),
            len(body.urls),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="upstream returned mismatched result count",
        )

    documents: list[Document] = []
    for url, entry in zip(body.urls, results, strict=True):
        if not isinstance(entry, dict):
            # Same defensive posture as the single-URL case: a
            # non-dict result is a contract violation, not something
            # we can map back to a Document.
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="upstream returned malformed result",
            )
        page_content = _extract_page_content(entry)
        upstream_meta_raw: Any = entry.get("metadata") or {}
        upstream_meta = upstream_meta_raw if isinstance(upstream_meta_raw, dict) else {}
        metadata: dict[str, Any] = {"source": str(url), **upstream_meta}
        documents.append(Document(page_content=page_content, metadata=metadata))

    return documents


@_router.get("/health")
async def health(
    client: httpx.AsyncClient = Depends(get_http_client),
) -> JSONResponse:
    """kubelet probe target.

    Returns 200 if upstream crawl4ai `/health` is reachable, 503
    otherwise. The Authorization header on the lifespan-managed client
    (if any) is harmless here — crawl4ai's `/health` is unauthenticated.
    """
    try:
        resp = await client.get(_HEALTH_PATH)
    except httpx.HTTPError as exc:
        logger.warning("upstream health unreachable: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "reason": "upstream unreachable"},
        )

    if 200 <= resp.status_code < 300:
        return JSONResponse(status_code=200, content={"status": "ok"})

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "degraded", "reason": f"upstream status {resp.status_code}"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json(resp: httpx.Response) -> Any:
    """Return the parsed JSON body or an empty dict on parse failure."""
    try:
        return resp.json()
    except ValueError:
        logger.warning("upstream returned non-JSON body (status=%s)", resp.status_code)
        return {}


def _extract_page_content(first: dict[str, Any]) -> str:
    """Pull the page text out of a crawl4ai result entry.

    crawl4ai 0.8.x returns `markdown` as either:

    - a string (older shapes / some configs)
    - a dict shaped `{"raw_markdown": "...", "markdown_with_citations": "...",
      "fit_markdown": "...", "fit_html": "..."}`

    We prefer `raw_markdown`, then the dict's `markdown_with_citations`,
    then any string fallback (`fit_markdown`). If all markdown fields
    are empty, fall back to `cleaned_html` → `fit_html` → `html`.

    This is defensive: we don't want a shape change in crawl4ai to
    silently produce empty pages.
    """
    md = first.get("markdown")
    if isinstance(md, str) and md.strip():
        return md
    if isinstance(md, dict):
        for key in ("raw_markdown", "markdown_with_citations", "fit_markdown"):
            value = md.get(key)
            if isinstance(value, str) and value.strip():
                return value
    for key in ("cleaned_html", "fit_html", "html"):
        value = first.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


# Module-level app for `uvicorn owui_crawl4ai_proxy.main:app`. The
# lifespan will load settings from the environment on first request.
app = create_app()
