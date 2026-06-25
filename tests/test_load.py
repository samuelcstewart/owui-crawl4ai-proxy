"""Tests for `POST /load`."""

from __future__ import annotations

import json

import httpx
import pytest

from tests.conftest import make_crawl_response


def test_load_happy_path(make_client):  # type: ignore[no-untyped-def]
    """Markdown is forwarded; metadata is merged with source URL."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Sanity-check the upstream contract: POST /crawl, bearer auth,
        # batch body with the requested URL.
        assert request.method == "POST"
        assert request.url.path == "/crawl"
        assert request.headers.get("Authorization") == "Bearer test-token-not-secret"
        body = json.loads(request.content)
        assert body == {"urls": ["https://example.com"]}
        return httpx.Response(
            200,
            json=make_crawl_response(
                url="https://example.com",
                markdown="# Hello",
                html="<h1>Hello</h1>",
                metadata={"title": "Example Domain"},
            ),
        )

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 200
    payload = r.json()
    assert payload["page_content"] == "# Hello"
    assert payload["metadata"] == {
        "source": "https://example.com",
        "title": "Example Domain",
    }


def test_load_falls_back_to_html_when_markdown_missing(make_client):  # type: ignore[no-untyped-def]
    """When `markdown` is empty/null, use `html`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_crawl_response(markdown=None, html="<p>hi</p>"),
        )

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 200
    assert r.json()["page_content"] == "<p>hi</p>"


def test_load_handles_crawl4ai_0_8_markdown_dict_shape(make_client):  # type: ignore[no-untyped-def]
    """crawl4ai 0.8.x returns `markdown` as a dict — pull `raw_markdown` out.

    Real shape from crawl4ai 0.8.x:
    `{"markdown": {"raw_markdown": "...", "markdown_with_citations": "...",
                   "fit_markdown": "", "fit_html": ""}}`
    """
    real_shape = {
        "success": True,
        "results": [
            {
                "url": "https://example.com",
                "html": "<html>...</html>",
                "fit_html": "<html>...</html>",
                "cleaned_html": "<html>...</html>",
                "markdown": {
                    "raw_markdown": "# Example Domain\nThis domain is for use in documentation examples.",
                    "markdown_with_citations": "# Example Domain [1]",
                    "fit_markdown": "",
                    "fit_html": "",
                },
                "metadata": {
                    "title": "Example Domain",
                    "description": None,
                    "keywords": None,
                    "author": None,
                },
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=real_shape)

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 200
    body = r.json()
    assert body["page_content"].startswith("# Example Domain\nThis domain is for use")
    assert body["metadata"]["source"] == "https://example.com"
    assert body["metadata"]["title"] == "Example Domain"


def test_load_falls_back_to_html_when_markdown_dict_is_empty(make_client):  # type: ignore[no-untyped-def]
    """When every markdown field in the dict is empty, fall through to HTML."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "results": [
                    {
                        "url": "https://example.com",
                        "html": "<p>plain html fallback</p>",
                        "markdown": {
                            "raw_markdown": "",
                            "markdown_with_citations": "",
                            "fit_markdown": "",
                            "fit_html": "",
                        },
                    }
                ],
            },
        )

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 200
    assert r.json()["page_content"] == "<p>plain html fallback</p>"


def test_load_rejects_invalid_url(make_client):  # type: ignore[no-untyped-def]
    """A non-HTTP URL is rejected by pydantic validation (422)."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream should not be called")

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "not-a-url"})

    assert r.status_code == 422


@pytest.mark.parametrize("upstream_status", [401, 403, 500, 502, 503, 504])
def test_load_propagates_upstream_auth_and_server_errors(
    make_client,
    upstream_status: int,  # type: ignore[no-untyped-def]
) -> None:
    """401/403 and 5xx pass through verbatim with a generic body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"detail": "internal"})

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == upstream_status
    assert r.json() == {"detail": "upstream error"}


def test_load_maps_unknown_4xx_to_502(make_client):  # type: ignore[no-untyped-def]
    """Any non-propagated 4xx (e.g. 418) collapses to 502 for the caller."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text="I'm a teapot")

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream error"}


def test_load_maps_success_false_to_502(make_client):  # type: ignore[no-untyped-def]
    """crawl4ai `success: false` is a 502 to the caller."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "results": []})

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream reported failure"}


def test_load_maps_empty_results_to_502(make_client):  # type: ignore[no-untyped-def]
    """`success: true` but empty `results` is a 502 (nothing to return)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "results": []})

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream returned no results"}


def test_load_maps_connection_error_to_502(make_client):  # type: ignore[no-untyped-def]
    """httpx transport errors (connection refused, DNS, timeout) → 502."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream unreachable"}


def test_load_handles_non_json_upstream_body(make_client):  # type: ignore[no-untyped-def]
    """Upstream returns HTML error page (200 OK but not JSON) → 502."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>oops</html>")

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream reported failure"}


def test_load_handles_malformed_first_result(make_client):  # type: ignore[no-untyped-def]
    """If `results[0]` isn't a dict, we treat it as a 502 (defensive)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "results": ["oops"]})

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream returned malformed result"}


def test_load_preserves_upstream_metadata_keys(make_client):  # type: ignore[no-untyped-def]
    """Upstream metadata is shallow-merged, not replaced."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_crawl_response(
                metadata={
                    "title": "Example Domain",
                    "language": "en",
                    "crawl_depth": 0,
                },
            ),
        )

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 200
    meta = r.json()["metadata"]
    assert meta["source"] == "https://example.com"
    assert meta["title"] == "Example Domain"
    assert meta["language"] == "en"
    assert meta["crawl_depth"] == 0
