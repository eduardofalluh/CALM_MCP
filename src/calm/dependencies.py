"""
CALM credential resolution.

Resolution order:
  1. Client credentials from request headers — x-calm-client-id + x-calm-client-secret
     (preferred for HTTP/multi-tenant; GenAI Studio injects these per customer).
  2. Server-startup token manager — CALM_CLIENT_ID + CALM_CLIENT_SECRET env vars.
  3. Authorization: Bearer <token> request header — HTTP legacy / per-request.
  4. CALM_TOKEN env var — stdio / local dev, static token.

Base URL resolution order:
  x-calm-base-url header > zone headers (x-calm-identity-zone + x-calm-region-zone) > env vars.
"""

from __future__ import annotations

import os

from fastmcp import Context

from .config import build_auth_url, build_base_url, get_auth_url, get_base_url
from .models import CALMHeaders
from .token_manager import get_managed_token, get_or_create_token_manager


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
    base_url: str | None = None
    token_source: str | None = None

    identity_zone: str | None = None
    region_zone: str | None = None
    client_id_hdr: str | None = None
    client_secret_hdr: str | None = None
    auth_bearer_token: str | None = None

    # Read all CALM-related request headers in one pass
    try:
        request = ctx.request_context.request
        if request is not None:
            h = request.headers
            identity_zone = h.get("x-calm-identity-zone")
            region_zone = h.get("x-calm-region-zone")
            client_id_hdr = h.get("x-calm-client-id")
            client_secret_hdr = h.get("x-calm-client-secret")
            auth_bearer_token = _token_from_authorization(h.get("Authorization"))
            raw_base = h.get("x-calm-base-url")
            if raw_base:
                base_url = raw_base.strip()
    except Exception:
        pass

    # Resolve base URL: explicit header > zone headers > env vars
    if not base_url:
        if identity_zone or region_zone:
            base_url = build_base_url(identity_zone, region_zone)
        else:
            base_url = get_base_url()

    # --- 1. Client credentials from request headers (per-tenant OAuth) ---
    if client_id_hdr and client_secret_hdr:
        auth_url = (
            build_auth_url(identity_zone, region_zone)
            if (identity_zone or region_zone)
            else get_auth_url()
        )
        mgr = get_or_create_token_manager(client_id_hdr, client_secret_hdr, auth_url)
        token = mgr.get_token()
        token_source = "client_credentials (header)"

    # --- 2. Server-startup token manager (env vars) ---
    if not token:
        managed = get_managed_token()
        if managed:
            token = managed
            token_source = "client_credentials"

    # --- 3. Authorization: Bearer header (HTTP legacy) ---
    if not token and auth_bearer_token:
        token = auth_bearer_token
        token_source = "Authorization header"

    # --- 4. CALM_TOKEN env var (stdio / local dev) ---
    if not token:
        env_token = os.getenv("CALM_TOKEN")
        if env_token:
            token = env_token.strip()
            token_source = "CALM_TOKEN env var"

    if not token:
        raise ValueError(
            "Missing CALM token. Options:\n"
            "  HTTP headers: x-calm-client-id + x-calm-client-secret (+ optional x-calm-identity-zone, x-calm-region-zone)\n"
            "  Server env vars: CALM_CLIENT_ID + CALM_CLIENT_SECRET\n"
            "  Per-request: Authorization: Bearer <token>\n"
            "  Local dev: CALM_TOKEN env var"
        )

    return CALMHeaders(token=token, base_url=base_url, token_source=token_source)
