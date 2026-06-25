"""Settings for the proxy.

All env vars are prefixed `PROXY_` (e.g. `PROXY_CRAWL4AI_URL`).
The token is required at startup.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from `PROXY_*` env vars.

    The upstream crawl4ai bearer token is required — the proxy is not
    useful without it (crawl4ai 0.9.0+ rejects unauthenticated calls on
    every endpoint except `GET /health`).
    """

    model_config = SettingsConfigDict(
        env_prefix="PROXY_",
        env_file=None,  # never read from disk
        case_sensitive=False,
        extra="ignore",
    )

    crawl4ai_url: str = Field(
        default="http://crawl4ai:11235",
        description="Upstream crawl4ai base URL.",
    )

    crawl4ai_api_token: str = Field(
        ...,  # required, no default
        min_length=1,
        description="Bearer token for crawl4ai 0.9.0+.",
    )

    request_timeout: float = Field(
        default=60.0,
        gt=0,
        description="httpx request timeout for upstream crawl4ai calls (seconds).",
    )


def load_settings(**overrides: Any) -> Settings:
    """Construct a `Settings` instance.

    `overrides` are passed as keyword arguments and take precedence
    over env vars. Used by tests to inject a token without touching
    the real environment.
    """
    return Settings(**overrides)
