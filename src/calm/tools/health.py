from __future__ import annotations

import os

from fastmcp import Context, FastMCP

from src.calm.config import build_auth_url, build_base_url, get_auth_url, get_base_url
from src.calm.token_manager import get_managed_token


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calm_health(ctx: Context) -> dict:
        """Diagnostic tool. Confirms the MCP server is up and reports whether a
        token is currently resolvable. Does NOT make a live CALM API call.
        """
        token_source = None
        identity_zone = None
        region_zone = None
        client_id_hdr = None
        client_secret_hdr = None
        base_url = None

        try:
            request = ctx.request_context.request
            if request is not None:
                h = request.headers
                identity_zone = h.get("x-calm-identity-zone")
                region_zone = h.get("x-calm-region-zone")
                client_id_hdr = h.get("x-calm-client-id")
                client_secret_hdr = h.get("x-calm-client-secret")
                raw_base = h.get("x-calm-base-url")
                if raw_base:
                    base_url = raw_base.strip()
        except Exception:
            pass

        # Resolve base URL using same logic as dependencies.py
        if not base_url:
            if identity_zone or region_zone:
                base_url = build_base_url(identity_zone, region_zone)
            else:
                base_url = get_base_url()

        # Mirror resolution order from dependencies.py
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
            "base_url": base_url,
            "token_configured": token_source is not None,
            "token_source": token_source,
            "client_credentials_enabled": bool(
                (client_id_hdr and client_secret_hdr) or os.getenv("CALM_CLIENT_ID")
            ),
        }
