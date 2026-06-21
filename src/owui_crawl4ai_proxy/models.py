"""Request/response models.

The public `/load` contract matches Open WebUI's external web loader:
- `POST /load` accepts `{"url": "..."}`
- the response is a langchain-style `Document` (`page_content` + `metadata`)

The internal `/crawl` payload is the crawl4ai batch shape:
- `POST /crawl` accepts `{"urls": [...]}`

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
    """Request body for `POST /load`."""

    url: str = Field(..., description="http(s) URL to crawl.")

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v)


class Document(BaseModel):
    """langchain-shaped document returned by `POST /load`.

    Open WebUI's external loader contract: `page_content` (str) +
    `metadata` (dict with at least the source URL).
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
