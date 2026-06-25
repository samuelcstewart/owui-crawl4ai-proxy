"""Tests for `GET /health`."""

from __future__ import annotations

import httpx


def test_health_ok_when_upstream_reachable(make_client):  # type: ignore[no-untyped-def]
    """Upstream 2xx on `/health` → 200 with `{"status": "ok"}`."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    with make_client(handler) as client:
        r = client.get("/health")

    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_degraded_when_upstream_5xx(make_client):  # type: ignore[no-untyped-def]
    """Upstream 5xx on `/health` → 503 with `{"status": "degraded"}`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    with make_client(handler) as client:
        r = client.get("/health")

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert "upstream status 503" in body["reason"]


def test_health_degraded_when_upstream_unreachable(make_client):  # type: ignore[no-untyped-def]
    """Transport error on `/health` → 503 with `reason: upstream unreachable`."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with make_client(handler) as client:
        r = client.get("/health")

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["reason"] == "upstream unreachable"


def test_health_does_not_require_authorization(make_client):  # type: ignore[no-untyped-def]
    """The lifespan-managed client always carries a Bearer header.

    crawl4ai's `/health` is the one endpoint that doesn't require auth;
    the header is harmless to send and keeps the client config uniform.
    This test documents that we DON'T need a separate unauthenticated
    client for the health check — the existing one is fine.
    """

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"status": "ok"})

    with make_client(handler) as client:
        r = client.get("/health")

    assert r.status_code == 200
    # The header is present (not stripped) because the test fixture
    # passes a client with the auth header baked in. The lifespan
    # uses a single client for both `/load` (auth required) and
    # `/health` (no auth required); crawl4ai 0.9.0+ accepts the
    # Bearer header on `/health` as a no-op, so the unified client
    # is fine.
    assert seen["authorization"].startswith("Bearer ")
