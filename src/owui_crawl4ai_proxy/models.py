"""Request/response models.

The public `/load` contract matches Open WebUI's external web loader as
shipped in 0.9.x:

- `POST /load` accepts `{"urls": ["...", "..."]}` (a batch)
- the response is a JSON array of langchain-style `Document` objects,
  one per input URL, in the same order

The internal `/crawl` payload is the crawl4ai batch shape:

- `POST /crawl` accepts `{"urls": [...]}` (also a batch)

URL handling
------------
We use `str` (with a manual http/https validator) instead of pydantic's
`HttpUrl`. `HttpUrl` normalises bare hosts by appending a trailing
slash (`https://example.com` -> `https://example.com/`), which leaks
into the upstream crawl4ai request and into the `source` field of the
returned metadata. Open WebUI sends the URL verbatim — preserving it
is the right behaviour.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


def _validate_http_url(value: str) -> str:
    """Lightweight http(s) URL check without `pydantic.HttpUrl` normalisation."""
    if not isinstance(value, str) or not value:
        raise ValueError("url must be a non-empty string")
    lowered = value.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError("url must start with http:// or https://")
    return value


class LoadRequest(BaseModel):
    """Request body for `POST /load`.

    Matches the Open WebUI 0.9.x `ExternalWebLoader` contract: a
    batch of URLs in `urls`. The order is preserved through to the
    response (one Document per URL, same order).
    """

    urls: list[str] = Field(
        ...,
        min_length=1,
        description="http(s) URLs to crawl, in order.",
    )

    @field_validator("urls")
    @classmethod
    def _check_urls(cls, v: list[str]) -> list[str]:
        for u in v:
            _validate_http_url(u)
        return v


class Document(BaseModel):
    """langchain-shaped document returned by `POST /load`.

    Open WebUI's external loader contract: `page_content` (str) +
    `metadata` (dict with at least the source URL). The proxy returns
    a JSON array of these — one per input URL — in input order.
    """

    page_content: str = Field(..., description="Markdown text (or HTML fallback).")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Source URL, title, and any upstream-provided metadata.",
    )


class CrawlRequest(BaseModel):
    """Internal request body for `POST /crawl` (crawl4ai batch shape)."""

    urls: list[str] = Field(..., min_length=1)

    @field_validator("urls")
    @classmethod
    def _check_urls(cls, v: list[str]) -> list[str]:
        for u in v:
            _validate_http_url(u)
        return v
