"""Settings for the proxy.

All env vars are prefixed `PROXY_` (e.g. `PROXY_CRAWL4AI_URL`).
The crawl4ai bearer token is OPTIONAL — when set, the proxy
attaches it to upstream /crawl calls; when unset, upstream calls
go without auth. The proxy is designed to run on a trusted
local network next to Open WebUI; neither side enforces auth
on the other.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from `PROXY_*` env vars.

    The upstream crawl4ai bearer token is optional. When set, the
    proxy attaches it as `Authorization: Bearer` to every
    upstream call. When unset, upstream calls go without auth —
    fine when crawl4ai is reachable only over a trusted in-cluster
    network. crawl4ai 0.9.0+ requires auth by default, so leaving
    the token unset also implies that crawl4ai itself is configured
    to accept unauthenticated calls (e.g. `AUTH_ENABLED=false` or
    a network policy that blocks off-cluster traffic).

    The proxy never validates any inbound Authorization header on
    /load — OWUI may send one (its `ExternalWebLoader` always does)
    and the proxy simply ignores it.
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

    crawl4ai_api_token: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Optional Bearer token for upstream crawl4ai calls. "
            "When set, the proxy attaches Authorization: Bearer. "
            "When unset, upstream calls go without auth."
        ),
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
