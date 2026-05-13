from __future__ import annotations

import os

from fastmcp import Context, FastMCP

from src.calm.config import get_base_url
from src.calm.token_manager import get_managed_token


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calm_health(ctx: Context) -> dict:
        """Diagnostic tool. Confirms the MCP server is up and reports whether a
        token is currently resolvable. Does NOT make a live CALM API call.
        """
        token_source = None

        # Client-credentials token manager
        if get_managed_token():
            token_source = "client_credentials"

        # Authorization header (HTTP legacy)
        if not token_source:
            try:
                request = ctx.request_context.request
                if request is not None and request.headers.get("Authorization"):
                    token_source = "Authorization header"
            except Exception:
                pass

        # Static env var (stdio / local dev)
        if not token_source and os.getenv("CALM_TOKEN"):
            token_source = "CALM_TOKEN env var"

        return {
            "server": "sap-cloud-alm",
            "base_url": get_base_url(),
            "token_configured": token_source is not None,
            "token_source": token_source,
            "client_credentials_enabled": bool(os.getenv("CALM_CLIENT_ID")),
        }
