"""Shared test fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from owui_crawl4ai_proxy.config import Settings
from owui_crawl4ai_proxy.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Settings with a fixed test token so the env is irrelevant.

    `owui_api_token` is left at its default (`None`) so `/load` accepts
    unauthenticated calls by default. Tests that exercise the auth path
    build their own `Settings` with a token set.
    """
    return Settings(
        crawl4ai_url="http://upstream.test",
        crawl4ai_api_token="test-token-not-secret",
        request_timeout=5.0,
    )


@pytest.fixture
def make_client():  # type: ignore[no-untyped-def]
    """Build a TestClient wired to a `MockTransport`-backed httpx client.

    Usage::

        def test_x(make_client):
            def handler(request):
                return httpx.Response(200, json={"ok": True})
            with make_client(handler) as client:
                r = client.post("/load", json={"url": "https://example.com"})
                assert r.status_code == 200

    Optional kwargs are forwarded to `Settings`, so the auth path can
    be exercised by passing `owui_api_token="..."`.
    """
    upstreams: list[httpx.AsyncClient] = []

    def _factory(
        handler: Callable[[httpx.Request], httpx.Response],
        **settings_overrides: Any,
    ) -> TestClient:
        transport = httpx.MockTransport(handler)
        # The base_url is arbitrary here — the MockTransport ignores it
        # and the request URL is whatever the app sends. The lifespan
        # owns nothing; we close the client ourselves below. Headers
        # here mirror what the production lifespan sets on the
        # httpx.AsyncClient so tests reflect real auth behaviour.
        upstream = httpx.AsyncClient(
            transport=transport,
            base_url="http://upstream.test",
            headers={
                "Authorization": "Bearer test-token-not-secret",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        upstreams.append(upstream)
        cfg = Settings(
            crawl4ai_url="http://upstream.test",
            crawl4ai_api_token="test-token-not-secret",
            request_timeout=5.0,
            **settings_overrides,
        )
        app = create_app(settings=cfg, http_client=upstream)
        return TestClient(app)

    yield _factory

    # Cleanup: close any upstream clients we created. TestClient closes
    # the FastAPI lifespan, which leaves the client alone (owns_client=False).
    # httpx.AsyncClient only exposes async `aclose()`, so we drive it
    # via a fresh event loop in the fixture teardown. MockTransport
    # doesn't hold sockets, but we close anyway to silence resource
    # warnings.
    for u in upstreams:
        if not u.is_closed:
            asyncio.run(u.aclose())


def make_crawl_result(
    *,
    url: str = "https://example.com",
    markdown: str | None = "# Example",
    html: str | None = "<h1>Example</h1>",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single crawl4ai `/crawl` result entry."""
    return {
        "url": url,
        "markdown": markdown,
        "html": html,
        "metadata": metadata or {},
    }


def make_crawl_response(
    *,
    url: str = "https://example.com",
    markdown: str | None = "# Example",
    html: str | None = "<h1>Example</h1>",
    success: bool = True,
    metadata: dict[str, Any] | None = None,
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a representative crawl4ai `/crawl` response body.

    Pass `results=[...]` to override the default single-result body —
    useful for multi-URL batch tests. The `url` / `markdown` / `html` /
    `metadata` kwargs only apply when `results` is `None` (single-result
    shortcut).
    """
    if results is None:
        results = [make_crawl_result(url=url, markdown=markdown, html=html, metadata=metadata)]
    return {"success": success, "results": results}
