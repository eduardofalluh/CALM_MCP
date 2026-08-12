"""
BTP Test Management OData connection resolution — entirely OPTIONAL.

When none of the TM_* env vars / x-tm-* headers are set, the server behaves
exactly as before: every CALM tool works unchanged and the tm_* tools return a
clear "not configured" message instead of failing cryptically. Nothing here is
mandatory for existing deployments.

Resolution order (mirrors the CALM resolution in dependencies.py):
  1. Request headers — x-tm-client-id + x-tm-client-secret + x-tm-token-url
     (+ x-tm-base-url). Preferred for HTTP/multi-tenant; each project injects
     its own service-key values, cached per (client_id, token_url) pair.
  2. Server env vars — TM_CLIENT_ID + TM_CLIENT_SECRET + TM_TOKEN_URL.
  3. TM_TOKEN env var — static bearer token (stdio / local dev / tests).

Base URL resolution: x-tm-base-url header > TM_BASE_URL env var.

The token flow is the same OAuth2 client-credentials / XSUAA flow as CALM, so
the existing TokenManager is reused — tokens are fetched once, cached, and
refreshed automatically before expiry. Values come from the BTP service key:
    cf service-key test-management-uaa sync-integration
      tokenUrl     = <url> + /oauth/token
      clientId     = clientid
      clientSecret = clientsecret
"""

from __future__ import annotations

import os

from fastmcp import Context
from pydantic import BaseModel

from .token_manager import get_or_create_token_manager

TM_NOT_CONFIGURED_MSG = (
    "BTP Test Management OData is not configured (this feature is optional — all "
    "CALM tools work without it). To enable it, either set server env vars "
    "TM_BASE_URL + TM_TOKEN_URL + TM_CLIENT_ID + TM_CLIENT_SECRET, or send the "
    "request headers x-tm-base-url + x-tm-token-url + x-tm-client-id + "
    "x-tm-client-secret. For local dev, TM_BASE_URL + TM_TOKEN (static bearer) "
    "also works. Values come from the BTP service key "
    "(cf service-key test-management-uaa sync-integration)."
)


class TMHeaders(BaseModel):
    token: str
    base_url: str
    token_source: str | None = None


def tm_writes_enabled() -> bool:
    """Whether TM repository write tools are permitted. Off unless
    TM_ENABLE_WRITES is truthy. Deliberately independent from
    CALM_ENABLE_WRITES so enabling CALM writes never silently enables writes
    to the Test Management repository (and vice versa)."""
    return os.getenv("TM_ENABLE_WRITES", "").strip().lower() in ("1", "true", "yes", "on")


def ensure_tm_writes_enabled() -> None:
    if not tm_writes_enabled():
        raise ValueError(
            "Test Management repository write operations are disabled. Set "
            "TM_ENABLE_WRITES=true to enable create/update/delete tools. This "
            "guard is independent from CALM_ENABLE_WRITES and prevents "
            "accidental changes to the repository."
        )


def _read_tm_request_headers(ctx: Context) -> dict[str, str | None]:
    out: dict[str, str | None] = {
        "base_url": None, "token_url": None, "client_id": None, "client_secret": None,
    }
    try:
        request = ctx.request_context.request
        if request is not None:
            h = request.headers
            raw_base = h.get("x-tm-base-url")
            if raw_base and raw_base.strip().startswith("https://"):
                out["base_url"] = raw_base.strip()
            raw_token_url = h.get("x-tm-token-url")
            if raw_token_url and raw_token_url.strip().startswith("https://"):
                out["token_url"] = raw_token_url.strip()
            out["client_id"] = h.get("x-tm-client-id") or None
            out["client_secret"] = h.get("x-tm-client-secret") or None
    except Exception:
        pass
    return out


def tm_configured(ctx: Context | None = None) -> bool:
    """True when a TM base URL plus some credential source is available."""
    hdr = _read_tm_request_headers(ctx) if ctx is not None else {}
    base_url = hdr.get("base_url") or os.getenv("TM_BASE_URL")
    has_creds = bool(
        (hdr.get("client_id") and hdr.get("client_secret"))
        or (os.getenv("TM_CLIENT_ID") and os.getenv("TM_CLIENT_SECRET") and os.getenv("TM_TOKEN_URL"))
        or os.getenv("TM_TOKEN")
    )
    return bool(base_url and has_creds)


def get_tm_headers(ctx: Context) -> TMHeaders:
    hdr = _read_tm_request_headers(ctx)

    base_url = hdr["base_url"] or (os.getenv("TM_BASE_URL") or "").strip() or None
    if not base_url:
        raise ValueError(TM_NOT_CONFIGURED_MSG)

    token: str | None = None
    token_source: str | None = None

    # --- 1. Client credentials from request headers (per-project OAuth) ---
    if hdr["client_id"] and hdr["client_secret"]:
        token_url = hdr["token_url"] or (os.getenv("TM_TOKEN_URL") or "").strip() or None
        if not token_url:
            raise ValueError(
                "x-tm-client-id/x-tm-client-secret received but no token URL — "
                "send x-tm-token-url as well (or set TM_TOKEN_URL on the server)."
            )
        mgr = get_or_create_token_manager(hdr["client_id"], hdr["client_secret"], token_url)
        token = mgr.get_token()
        token_source = "tm client_credentials (header)"

    # --- 2. Server env vars (client credentials) ---
    if not token:
        client_id = (os.getenv("TM_CLIENT_ID") or "").strip()
        client_secret = (os.getenv("TM_CLIENT_SECRET") or "").strip()
        token_url = (os.getenv("TM_TOKEN_URL") or "").strip()
        if client_id and client_secret and token_url:
            mgr = get_or_create_token_manager(client_id, client_secret, token_url)
            token = mgr.get_token()
            token_source = "tm client_credentials"

    # --- 3. TM_TOKEN env var (stdio / local dev / tests) ---
    if not token:
        env_token = (os.getenv("TM_TOKEN") or "").strip()
        if env_token:
            token = env_token
            token_source = "TM_TOKEN env var"

    if not token:
        raise ValueError(TM_NOT_CONFIGURED_MSG)

    return TMHeaders(token=token, base_url=base_url.rstrip("/"), token_source=token_source)
