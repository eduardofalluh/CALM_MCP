from __future__ import annotations

import os

from fastmcp import Context, FastMCP
from fastmcp.server.dependencies import get_access_token

from src.calm.client import DEFAULT_BASE_URL


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calm_health(ctx: Context) -> dict:
        """Diagnostic tool. Confirms the MCP server is up and reports whether a
        token is currently resolvable. Does NOT make a live CALM API call.
        """
        token_source = None

        # Check OAuth token (HTTP + OAuth mode)
        access_token_obj = get_access_token()
        if access_token_obj and access_token_obj.token:
            token_source = "oauth"

        # Check x-calm-token header (HTTP legacy mode)
        if not token_source:
            try:
                request = ctx.request_context.request
                if request is not None and request.headers.get("x-calm-token"):
                    token_source = "x-calm-token header"
            except Exception:
                pass

        # Check env var (stdio mode)
        if not token_source and os.getenv("CALM_TOKEN"):
            token_source = "CALM_TOKEN env var"

        oauth_configured = bool(os.getenv("CALM_OAUTH_CLIENT_ID"))

        return {
            "server": "sap-cloud-alm",
            "base_url": os.getenv("CALM_BASE_URL", DEFAULT_BASE_URL),
            "token_configured": token_source is not None,
            "token_source": token_source,
            "oauth_enabled": oauth_configured,
        }
