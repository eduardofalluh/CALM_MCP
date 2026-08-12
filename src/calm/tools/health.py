from __future__ import annotations

import os

from fastmcp import Context, FastMCP

from src.calm.config import build_auth_url, build_base_url, get_auth_url, get_base_url
from src.calm.dependencies import writes_enabled
from src.calm.tm_dependencies import tm_configured, tm_writes_enabled
from src.calm.token_manager import get_managed_token


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calm_health(ctx: Context) -> dict:
        """Diagnostic tool. Confirms the MCP server is up and reports token status,
        resolved URLs, and the raw zone header values received. Use this to verify
        that GenAI Studio is injecting the correct header values.
        Does NOT make a live CALM API call.
        """
        token_source = None
        identity_zone = None
        region_zone = None
        client_id_hdr = None
        client_secret_hdr = None
        auth_url_hdr = None
        base_url = None

        try:
            request = ctx.request_context.request
            if request is not None:
                h = request.headers
                identity_zone = h.get("x-calm-identity-zone") or None
                region_zone = h.get("x-calm-region-zone") or None
                client_id_hdr = h.get("x-calm-client-id")
                client_secret_hdr = h.get("x-calm-client-secret")
                raw_auth = h.get("x-calm-auth-url")
                if raw_auth and raw_auth.strip().startswith("https://"):
                    auth_url_hdr = raw_auth.strip()
                raw_base = h.get("x-calm-base-url")
                if raw_base and raw_base.strip().startswith("https://"):
                    base_url = raw_base.strip()
        except Exception:
            pass

        # Resolve URLs using same logic as dependencies.py
        if not base_url:
            if identity_zone or region_zone:
                base_url = build_base_url(identity_zone, region_zone)
            else:
                base_url = get_base_url()

        if auth_url_hdr:
            auth_url = auth_url_hdr
        elif identity_zone or region_zone:
            auth_url = build_auth_url(identity_zone, region_zone)
        else:
            auth_url = get_auth_url()

        # Mirror token resolution order from dependencies.py
        if client_id_hdr and client_secret_hdr:
            token_source = "client_credentials (header)"
        elif get_managed_token():
            token_source = "client_credentials"
        else:
            try:
                request = ctx.request_context.request
                if request is not None and request.headers.get("Authorization"):
                    token_source = "Authorization header"
            except Exception:
                pass

        if not token_source and os.getenv("CALM_TOKEN"):
            token_source = "CALM_TOKEN env var"

        return {
            "server": "sap-cloud-alm",
            "token_configured": token_source is not None,
            "token_source": token_source,
            "client_credentials_enabled": bool(
                (client_id_hdr and client_secret_hdr) or os.getenv("CALM_CLIENT_ID")
            ),
            "server_auth_mode": (
                "x509/mTLS"
                if (os.getenv("CALM_CLIENT_CERT") or os.getenv("CALM_CLIENT_CERT_PEM"))
                else "client_secret" if os.getenv("CALM_CLIENT_SECRET")
                else "header/token"
            ),
            "writes_enabled": writes_enabled(),
            "auth_url": auth_url,
            "base_url": base_url,
            # Optional BTP Test Management OData connection (tm_* tools).
            "tm_odata": {
                "configured": tm_configured(ctx),
                "tm_writes_enabled": tm_writes_enabled(),
                "base_url": os.getenv("TM_BASE_URL") or "(not set — env or x-tm-base-url header)",
            },
            "headers_received": {
                "x-calm-identity-zone": identity_zone or "(not set)",
                "x-calm-region-zone": region_zone or "(not set)",
                "x-calm-client-id": ("set" if client_id_hdr else "(not set)"),
                "x-calm-client-secret": ("set" if client_secret_hdr else "(not set)"),
                "x-calm-auth-url": auth_url_hdr or "(not set)",
                "x-calm-base-url": base_url if base_url != build_base_url(identity_zone, region_zone) else "(not set)",
            },
        }
