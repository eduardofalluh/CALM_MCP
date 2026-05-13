"""
CALM credential resolution.

Resolution order:
  1. Client-credentials token manager — server fetches+caches its own SAP token
     (set CALM_CLIENT_ID + CALM_CLIENT_SECRET).  Auto-refreshes silently.
  2. Authorization request header — HTTP transport, legacy / per-request.
  3. CALM_TOKEN env var            — stdio / local dev, static token.
"""

from __future__ import annotations

import os

from fastmcp import Context

from .config import get_base_url
from .models import CALMHeaders
from .token_manager import get_managed_token


def _token_from_authorization(value: str | None) -> str | None:
    if not value:
        return None

    raw_token = value.strip()
    scheme, _, token = raw_token.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return raw_token


def get_calm_headers(ctx: Context) -> CALMHeaders:
    token: str | None = None
    base_url: str = get_base_url()
    token_source: str | None = None

    # --- 1. Client-credentials (auto-managed, preferred) ---
    managed = get_managed_token()
    if managed:
        token = managed
        token_source = "client_credentials"

    # --- 2. Authorization header (HTTP legacy) ---
    if not token:
        try:
            request = ctx.request_context.request
            if request is not None:
                raw_token = _token_from_authorization(request.headers.get("Authorization"))
                if raw_token:
                    token = raw_token
                    token_source = "Authorization header"
                raw_url = request.headers.get("x-calm-base-url")
                if raw_url:
                    base_url = raw_url.strip()
        except Exception:
            pass

    # --- 3. CALM_TOKEN env var (stdio / local dev) ---
    if not token:
        env_token = os.getenv("CALM_TOKEN")
        if env_token:
            token = env_token.strip()
            token_source = "CALM_TOKEN env var"

    if not token:
        raise ValueError(
            "Missing CALM token. "
            "Set CALM_CLIENT_ID + CALM_CLIENT_SECRET (recommended), "
            "send Authorization header (HTTP legacy), "
            "or set CALM_TOKEN env var (stdio)."
        )

    return CALMHeaders(token=token, base_url=base_url, token_source=token_source)
