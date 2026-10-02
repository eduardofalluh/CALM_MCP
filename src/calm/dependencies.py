"""
CALM credential resolution.

Resolution order:
  1. Client credentials from request headers — x-calm-client-id + x-calm-client-secret
     (preferred for HTTP/multi-tenant; GenAI Studio injects these per customer).
  2. Server-startup token manager — CALM_CLIENT_ID + CALM_CLIENT_SECRET env vars.
  3. Authorization: Bearer <token> request header — HTTP legacy / per-request.
  4. CALM_TOKEN env var — stdio / local dev, static token.

Auth URL resolution order:
  x-calm-auth-url header (full URL) > zone headers (x-calm-identity-zone + x-calm-region-zone) > env vars.

Base URL resolution order:
  x-calm-base-url header > zone headers > env vars.
"""

from __future__ import annotations

import hashlib
import logging
import os

from fastmcp import Context

from .config import build_auth_url, build_base_url, get_auth_url, get_base_url
from .models import CALMHeaders
from .token_manager import get_managed_token, get_or_create_token_manager

log = logging.getLogger("calm-mcp.auth")


def _fp(secret: str | None) -> str:
    """Non-reversible fingerprint of a secret for logs: '<len>:<sha256[:8]>'.

    Never returns the secret itself — just enough to tell two secrets apart and
    spot truncation. 'none' when absent.
    """
    if not secret:
        return "none"
    return f"{len(secret)}:{hashlib.sha256(secret.encode()).hexdigest()[:8]}"


def writes_enabled() -> bool:
    """Whether write tools are permitted. Off unless CALM_ENABLE_WRITES is truthy."""
    return os.getenv("CALM_ENABLE_WRITES", "").strip().lower() in ("1", "true", "yes", "on")


def ensure_writes_enabled() -> None:
    """Raise a clear error if write operations are disabled."""
    if not writes_enabled():
        raise ValueError(
            "Write operations are disabled. Set CALM_ENABLE_WRITES=true to enable "
            "create/update tools. This guard prevents accidental changes to the tenant."
        )


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
    user_email: str | None = None

    identity_zone: str | None = None
    region_zone: str | None = None
    client_id_hdr: str | None = None
    client_secret_hdr: str | None = None
    auth_bearer_token: str | None = None
    auth_url_hdr: str | None = None

    # Read all CALM-related request headers in one pass
    try:
        request = ctx.request_context.request
        if request is not None:
            h = request.headers
            identity_zone = h.get("x-calm-identity-zone") or None
            region_zone = h.get("x-calm-region-zone") or None
            client_id_hdr = h.get("x-calm-client-id")
            client_secret_hdr = h.get("x-calm-client-secret")
            auth_bearer_token = _token_from_authorization(h.get("Authorization"))
            raw_auth = h.get("x-calm-auth-url")
            if raw_auth and raw_auth.strip().startswith("https://"):
                auth_url_hdr = raw_auth.strip()
            raw_base = h.get("x-calm-base-url")
            if raw_base and raw_base.strip().startswith("https://"):
                base_url = raw_base.strip()
            # User email from GenAI Studio (x-user-email) or other headers
            user_email = (h.get("x-user-email") or
                         h.get("x-forwarded-user") or
                         h.get("x-calm-user-email") or None)
    except Exception:
        pass

    # Diagnostic: what the request actually carried (no secret values — fingerprint only).
    log.info(
        "CALM headers in: client_id=%s client_secret_fp=%s identity_zone=%s region_zone=%s "
        "auth_url_hdr=%s base_url_hdr=%s bearer=%s",
        client_id_hdr or "-",
        _fp(client_secret_hdr),
        identity_zone or "-",
        region_zone or "-",
        auth_url_hdr or "-",
        base_url or "-",
        "yes" if auth_bearer_token else "no",
    )

    # Resolve base URL: explicit header > zone headers > env vars
    if not base_url:
        if identity_zone or region_zone:
            base_url = build_base_url(identity_zone, region_zone)
        else:
            base_url = get_base_url()

    # --- 1. Client credentials from request headers (per-tenant OAuth) ---
    if client_id_hdr and client_secret_hdr:
        if auth_url_hdr:
            auth_url = auth_url_hdr
        elif identity_zone or region_zone:
            auth_url = build_auth_url(identity_zone, region_zone)
        else:
            auth_url = get_auth_url()
        log.info(
            "CALM auth path=HEADER (per-tenant) client_id=%s secret_fp=%s auth_url=%s base_url=%s",
            client_id_hdr, _fp(client_secret_hdr), auth_url, base_url,
        )
        mgr = get_or_create_token_manager(client_id_hdr, client_secret_hdr, auth_url)
        token = mgr.get_token()
        token_source = "client_credentials (header)"

    # --- 2. Server-startup token manager (env vars) ---
    if not token:
        # NOTE: this uses the POD ENV credential, which is shared by ALL tenants.
        # If a request routed to one tenant's base_url (from headers) but reaches
        # this branch, it is authenticating with the env credential — a mismatch
        # that yields 'invalid_client' for every tenant except the one whose
        # credential is in the pod env.
        log.info(
            "CALM auth path=ENV (shared pod credential) env_client_id=%s env_secret_fp=%s "
            "against base_url=%s  <-- header credential was NOT present",
            os.getenv("CALM_CLIENT_ID") or "-", _fp(os.getenv("CALM_CLIENT_SECRET")), base_url,
        )
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

    # Fallback to env var if no header provided
    if not user_email:
        user_email = os.getenv("CALM_USER_EMAIL")

    return CALMHeaders(token=token, base_url=base_url, token_source=token_source, user_email=user_email)
