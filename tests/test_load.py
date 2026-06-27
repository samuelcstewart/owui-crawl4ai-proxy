"""Tests for `POST /load`."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from tests.conftest import make_crawl_response, make_crawl_result


def test_load_happy_path_single_url(make_client):  # type: ignore[no-untyped-def]
    """Single-URL batch: markdown is forwarded; metadata is merged with source URL.

    The Open WebUI 0.9.x loader always sends batches (up to 20 URLs),
    but a batch of one is the common path for ad-hoc chat ingestion.
    """

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
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 200
    payload = r.json()
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["page_content"] == "# Hello"
    assert payload[0]["metadata"] == {
        "source": "https://example.com",
        "title": "Example Domain",
    }


def test_load_happy_path_multi_url_preserves_order(make_client):  # type: ignore[no-untyped-def]
    """Multi-URL batch returns one Document per URL, in input order."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {
            "urls": [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/c",
            ]
        }
        return httpx.Response(
            200,
            json=make_crawl_response(
                results=[
                    make_crawl_result(url="https://example.com/a", markdown="# A"),
                    make_crawl_result(url="https://example.com/b", markdown="# B"),
                    make_crawl_result(url="https://example.com/c", markdown="# C"),
                ],
            ),
        )

    with make_client(handler) as client:
        r = client.post(
            "/load",
            json={
                "urls": [
                    "https://example.com/a",
                    "https://example.com/b",
                    "https://example.com/c",
                ]
            },
        )

    assert r.status_code == 200
    payload = r.json()
    assert [d["page_content"] for d in payload] == ["# A", "# B", "# C"]
    assert [d["metadata"]["source"] for d in payload] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]


def test_load_single_url_response_is_list_not_dict(make_client):  # type: ignore[no-untyped-def]
    """Regression: OWUI iterates the response and calls .get() on each element.

    If the proxy returned a single Document (dict) instead of a list,
    OWUI would iterate over the dict's keys (strings), and `.get()` on
    a string would AttributeError. The response MUST be a list.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_crawl_response(markdown="# Hello"))

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 200
    payload = r.json()
    assert isinstance(payload, list), f"response must be a JSON array; got {type(payload).__name__}"


def test_load_falls_back_to_html_when_markdown_missing(make_client):  # type: ignore[no-untyped-def]
    """When `markdown` is empty/null, use `html`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_crawl_response(markdown=None, html="<p>hi</p>"),
        )

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 200
    assert r.json()[0]["page_content"] == "<p>hi</p>"


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
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 200
    body = r.json()[0]
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
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 200
    assert r.json()[0]["page_content"] == "<p>plain html fallback</p>"


def test_load_rejects_empty_urls(make_client):  # type: ignore[no-untyped-def]
    """An empty `urls` list is rejected by pydantic validation (422)."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream should not be called")

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": []})

    assert r.status_code == 422


def test_load_rejects_missing_urls(make_client):  # type: ignore[no-untyped-def]
    """A request with no `urls` field at all is rejected (422).

    This is the regression test for the original drift: OWUI 0.9.x
    sends `{"urls": [...]}`, but the proxy used to expect
    `{"url": "..."}`. A missing `urls` field must 422, not silently
    fall through.
    """

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream should not be called")

    with make_client(handler) as client:
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 422


def test_load_rejects_invalid_url(make_client):  # type: ignore[no-untyped-def]
    """A non-HTTP URL is rejected by pydantic validation (422)."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream should not be called")

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["not-a-url"]})

    assert r.status_code == 422


def test_load_logs_422_validation_errors(  # type: ignore[no-untyped-def]
    make_client, caplog: pytest.LogCaptureFixture
) -> None:
    """422s are logged so request-shape drift is visible in proxy logs.

    Without this, a future OWUI upgrade that changes the loader contract
    would be invisible in the proxy's logs — only the caller's logs
    would show the rejection. This is exactly what happened with the
    original `{"url": "..."}` -> `{"urls": [...]}` drift.
    """

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("upstream should not be called")

    with (
        make_client(handler) as client,
        caplog.at_level(logging.WARNING, logger="owui_crawl4ai_proxy"),
    ):
        r = client.post("/load", json={"url": "https://example.com"})

    assert r.status_code == 422
    assert any("rejected request to /load" in rec.message for rec in caplog.records)


@pytest.mark.parametrize("upstream_status", [401, 403, 500, 502, 503, 504])
def test_load_propagates_upstream_auth_and_server_errors(
    make_client,
    upstream_status: int,  # type: ignore[no-untyped-def]
) -> None:
    """401/403 and 5xx pass through verbatim with a generic body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"detail": "internal"})

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == upstream_status
    assert r.json() == {"detail": "upstream error"}


def test_load_maps_unknown_4xx_to_502(make_client):  # type: ignore[no-untyped-def]
    """Any non-propagated 4xx (e.g. 418) collapses to 502 for the caller."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text="I'm a teapot")

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream error"}


def test_load_maps_success_false_to_502(make_client):  # type: ignore[no-untyped-def]
    """crawl4ai `success: false` is a 502 to the caller."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "results": []})

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream reported failure"}


def test_load_maps_empty_results_to_502(make_client):  # type: ignore[no-untyped-def]
    """`success: true` but empty `results` is a 502 (nothing to return)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "results": []})

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream returned no results"}


def test_load_maps_connection_error_to_502(make_client):  # type: ignore[no-untyped-def]
    """httpx transport errors (connection refused, DNS, timeout) → 502."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream unreachable"}


def test_load_handles_non_json_upstream_body(make_client):  # type: ignore[no-untyped-def]
    """Upstream returns HTML error page (200 OK but not JSON) → 502."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>oops</html>")

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream reported failure"}


def test_load_handles_malformed_first_result(make_client):  # type: ignore[no-untyped-def]
    """If `results[0]` isn't a dict, we treat it as a 502 (defensive)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "results": ["oops"]})

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream returned malformed result"}


def test_load_handles_mismatched_result_count(make_client):  # type: ignore[no-untyped-def]
    """`len(results) != len(urls)` is a 502 (upstream bug, can't map back)."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Caller asked for two URLs, but upstream returned one result.
        return httpx.Response(
            200,
            json=make_crawl_response(
                results=[make_crawl_result(url="https://example.com/a", markdown="# A")],
            ),
        )

    with make_client(handler) as client:
        r = client.post(
            "/load",
            json={"urls": ["https://example.com/a", "https://example.com/b"]},
        )

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream returned mismatched result count"}


def test_load_handles_non_list_results(make_client):  # type: ignore[no-untyped-def]
    """`results` that isn't a list is a 502 (defensive)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"success": True, "results": {"url": "https://example.com"}}
        )

    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 502
    assert r.json() == {"detail": "upstream returned malformed results"}


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
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 200
    meta = r.json()[0]["metadata"]
    assert meta["source"] == "https://example.com"
    assert meta["title"] == "Example Domain"
    assert meta["language"] == "en"
    assert meta["crawl_depth"] == 0


# ---------------------------------------------------------------------------
# Auth posture: no client auth, optional upstream auth
# ---------------------------------------------------------------------------


def test_load_ignores_inbound_authorization_header(make_client):  # type: ignore[no-untyped-def]
    """Inbound `Authorization` is never validated; any value is accepted.

    The proxy is designed to run on a trusted local network alongside
    Open WebUI. OWUI's `ExternalWebLoader` sends a Bearer header
    regardless of any proxy setting; the proxy simply ignores it.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_crawl_response(markdown="# Hello"))

    with make_client(handler) as client:
        r = client.post(
            "/load",
            json={"urls": ["https://example.com"]},
            headers={"Authorization": "Bearer anything-goes"},
        )

    assert r.status_code == 200
    assert r.json()[0]["page_content"] == "# Hello"


def test_load_ignores_inbound_authorization_with_garbage_value(make_client):  # type: ignore[no-untyped-def]
    """Even a clearly-invalid Authorization value is ignored, not 401."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_crawl_response(markdown="# Hello"))

    with make_client(handler) as client:
        r = client.post(
            "/load",
            json={"urls": ["https://example.com"]},
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )

    assert r.status_code == 200


def test_load_sends_bearer_upstream_when_crawl4ai_token_set(  # type: ignore[no-untyped-def]
    make_client,
) -> None:
    """When `PROXY_CRAWL4AI_API_TOKEN` is set, the upstream call carries it."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer test-token-not-secret"
        return httpx.Response(200, json=make_crawl_response(markdown="# Hello"))

    # Default make_client settings include crawl4ai_api_token.
    with make_client(handler) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 200


def test_load_omits_authorization_upstream_when_crawl4ai_token_unset(  # type: ignore[no-untyped-def]
    make_client,
) -> None:
    """When `PROXY_CRAWL4AI_API_TOKEN` is unset, the upstream call has no Authorization."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers, (
            f"upstream should not receive Authorization header; got {request.headers.get('Authorization')!r}"
        )
        return httpx.Response(200, json=make_crawl_response(markdown="# Hello"))

    with make_client(handler, crawl4ai_api_token=None) as client:
        r = client.post("/load", json={"urls": ["https://example.com"]})

    assert r.status_code == 200
    assert r.json()[0]["page_content"] == "# Hello"
