"""
CALM credential resolution.

Resolution order:
  1. OAuth access token  — set by OAuthProxy when running HTTP + OAuth
  2. x-calm-token header — HTTP transport without OAuth (legacy / backward-compat)
  3. CALM_TOKEN env var  — stdio / local dev

This means:
- In production (HTTP + OAuth) the proxy handles authentication and token
  refresh automatically. No manual token management needed.
- In legacy HTTP mode the client passes credentials per-request via headers.
- In local dev (stdio, MCP Inspector) you still just set CALM_TOKEN in .env.
"""

from __future__ import annotations

import os

from fastmcp import Context
from fastmcp.server.dependencies import get_access_token

from .client import DEFAULT_BASE_URL
from .models import CALMHeaders


def get_calm_headers(ctx: Context) -> CALMHeaders:
    token: str | None = None
    base_url: str = os.getenv("CALM_BASE_URL", DEFAULT_BASE_URL)
    token_source: str | None = None

    # --- 1. OAuth: upstream SAP token from authenticated session ---
    access_token_obj = get_access_token()
    if access_token_obj and access_token_obj.token:
        token = access_token_obj.token
        token_source = "oauth"

    # --- 2. x-calm-token header (HTTP transport, legacy) ---
    if not token:
        try:
            request = ctx.request_context.request
            if request is not None:
                raw_token = request.headers.get("x-calm-token")
                if raw_token:
                    token = raw_token.strip()
                    token_source = "x-calm-token header"
                raw_url = request.headers.get("x-calm-base-url")
                if raw_url:
                    base_url = raw_url.strip()
        except Exception:
            pass

    # --- 3. stdio / local dev: fall back to env var ---
    if not token:
        env_token = os.getenv("CALM_TOKEN")
        if env_token:
            token = env_token.strip()
            token_source = "CALM_TOKEN env var"

    if not token:
        raise ValueError(
            "Missing CALM token. "
            "Authenticate via OAuth (HTTP + OAuth mode), "
            "send x-calm-token header (HTTP legacy mode), "
            "or set CALM_TOKEN env var (stdio mode)."
        )

    return CALMHeaders(token=token, base_url=base_url, token_source=token_source)
