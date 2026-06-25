"""Integration tests against a real crawl4ai instance.

These tests are NOT run by `poe test` (the default test task
excludes the `integration` marker). They're invoked by
`poe integration-test`, which:

1. `docker compose up -d --build` — starts crawl4ai 0.9.0 + this proxy
   on a shared network.
2. Waits for `GET $PROXY_HEALTH_URL` to return 2xx.
3. Runs `pytest -m integration -v --tb=short`.
4. `docker compose down` — tears the stack down (via a shell `trap`).

The proxy is reachable at http://localhost:8000 (mapped from the
compose port forward). crawl4ai is reachable inside the compose
network on port 11235; the proxy talks to it via that internal DNS.

Why a separate test file
------------------------
The unit tests in `test_load.py` / `test_health.py` use
`httpx.MockTransport` to inject canned responses. That's fast and
deterministic, but it doesn't catch:

- A shape drift between what crawl4ai returns and what the proxy
  expects (e.g. a `markdown` field whose value is `None` instead of a
  string or dict).
- A real auth round-trip with a non-trivial token.
- A real network error / connection-refused path.

The integration tests exercise the full stack end-to-end against a
real crawl4ai 0.9.0 instance. When the unit suite goes green but the
integration suite goes red, it's almost always a shape drift in the
upstream response.

Marking convention
------------------
Every test in this file is decorated with
`@pytest.mark.integration` so the default `poe test` run skips it.
The matching `[tool.pytest.ini_options].markers` entry in
`pyproject.toml` registers the marker so `--strict-markers` is
satisfied.

URL under test
--------------
The proxy is published to localhost:8000 by docker compose. The
target URL crawled is `https://example.com` — it's stable, tiny,
allows crawlers, and is the canonical test fixture for any HTTP
fetch path.
"""

from __future__ import annotations

import os

import httpx
import pytest

# Reuse the proxy's expected port forward (set by docker compose).
# The PROXY_URL env var exists so CI / dockerized runners can
# override the target (e.g. `PROXY_URL=http://proxy:8000`).
PROXY_URL = os.environ.get("PROXY_URL", "http://localhost:8000")
TARGET_URL = "https://example.com"


def _client() -> httpx.Client:
    """Plain sync httpx client — no need for async, the proxy is HTTP/1.1."""
    return httpx.Client(base_url=PROXY_URL, timeout=httpx.Timeout(60.0))


@pytest.mark.integration
def test_health_endpoint_reports_ok_against_real_crawl4ai() -> None:
    """`/health` returns 200 + `{"status": "ok"}` once crawl4ai is reachable."""
    with _client() as c:
        r = c.get("/health")

    assert r.status_code == 200, f"unexpected status: {r.status_code} body={r.text!r}"
    body = r.json()
    assert body == {"status": "ok"}


@pytest.mark.integration
def test_load_returns_document_for_example_com() -> None:
    """`/load` against `https://example.com` returns a non-empty Document.

    This exercises the full path: POST /load → proxy → crawl4ai
    `/crawl` with bearer auth → response shape mapping → Document.
    """
    with _client() as c:
        r = c.post("/load", json={"url": TARGET_URL})

    assert r.status_code == 200, f"unexpected status: {r.status_code} body={r.text!r}"
    payload = r.json()
    # Document shape: page_content + metadata
    assert "page_content" in payload
    assert "metadata" in payload

    page_content = payload["page_content"]
    # example.com is a real HTML page that crawl4ai should render to
    # something with non-trivial content. We don't pin the exact
    # string (crawl4ai markdown formatting can shift between versions)
    # but we do assert non-empty + meaningful length.
    assert isinstance(page_content, str)
    assert len(page_content) > 20, f"page_content suspiciously short: {page_content!r}"
    # example.com's canonical heading is "Example Domain".
    assert "Example Domain" in page_content, (
        f"page_content missing the expected heading: {page_content!r}"
    )

    metadata = payload["metadata"]
    assert metadata.get("source") == TARGET_URL


@pytest.mark.integration
def test_load_propagates_invalid_url_to_upstream() -> None:
    """FastAPI's URL validator rejects malformed URLs at the boundary.

    This isn't an integration assertion about crawl4ai specifically —
    it's a smoke test that the proxy is actually running (so the
    request lands on our code, not on a connection-refused). A
    different error mode would suggest the wrong service is on
    localhost:8000.
    """
    with _client() as c:
        r = c.post("/load", json={"url": "not-a-url"})

    assert r.status_code == 422


@pytest.mark.integration
def test_load_rejects_unknown_host_with_502() -> None:
    """An unreachable target URL bubbles up as a 502 from the proxy.

    crawl4ai will try to fetch the URL, fail, and return either
    `success: false` or an HTTP error. Either way the proxy should
    surface it as 502 — the caller doesn't need to know which
    specific failure mode happened upstream.
    """
    # `.invalid` is a reserved TLD (RFC 2606) guaranteed never to
    # resolve, so this is a deterministic fetch failure.
    with _client() as c:
        r = c.post("/load", json={"url": "https://nonexistent.invalid/"})

    assert r.status_code == 502, (
        f"expected 502 for unreachable target, got {r.status_code}: {r.text!r}"
    )
