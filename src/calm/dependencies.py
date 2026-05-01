"""
Header-based dependency for CALM credentials.

Resolution order:
  1. x-calm-token / x-calm-base-url HTTP request headers  (HTTP transport)
  2. CALM_TOKEN / CALM_BASE_URL environment variables      (stdio / local dev)

This means:
- In production (Studio over HTTP) the client passes credentials per-request
  — no server-side secrets needed.
- In local dev (stdio, MCP Inspector) you still just set CALM_TOKEN in .env.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import Context

from .client import DEFAULT_BASE_URL
from .models import CALMHeaders


def get_calm_headers(ctx: Context) -> CALMHeaders:
    token: str | None = None
    base_url: str = os.getenv("CALM_BASE_URL", DEFAULT_BASE_URL)

    # --- HTTP transport: read from request headers ---
    try:
        request = ctx.request_context.request
        if request is not None:
            raw_token = request.headers.get("x-calm-token")
            if raw_token:
                token = raw_token.strip()
            raw_url = request.headers.get("x-calm-base-url")
            if raw_url:
                base_url = raw_url.strip()
    except Exception:
        pass

    # --- stdio / local dev: fall back to env var ---
    if not token:
        env_token = os.getenv("CALM_TOKEN")
        if env_token:
            token = env_token.strip()

    if not token:
        raise ValueError(
            "Missing CALM token. "
            "Send x-calm-token header (HTTP transport) or set CALM_TOKEN env var (stdio)."
        )

    return CALMHeaders(token=token, base_url=base_url)
