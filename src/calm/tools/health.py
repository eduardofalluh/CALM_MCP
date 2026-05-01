from __future__ import annotations

import os

from mcp.server.fastmcp import Context, FastMCP

from src.calm.client import DEFAULT_BASE_URL


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calm_health(ctx: Context) -> dict:
        """Diagnostic tool. Confirms the MCP server is up and reports whether a
        token is currently resolvable. Does NOT make a live CALM API call.
        """
        has_env_token = bool(os.getenv("CALM_TOKEN"))

        header_token_present = False
        try:
            request = ctx.request_context.request
            if request is not None:
                header_token_present = bool(request.headers.get("x-calm-token"))
        except Exception:
            pass

        token_source = None
        if header_token_present:
            token_source = "x-calm-token header"
        elif has_env_token:
            token_source = "CALM_TOKEN env var"

        return {
            "server": "sap-cloud-alm",
            "base_url": os.getenv("CALM_BASE_URL", DEFAULT_BASE_URL),
            "token_configured": header_token_present or has_env_token,
            "token_source": token_source,
        }
