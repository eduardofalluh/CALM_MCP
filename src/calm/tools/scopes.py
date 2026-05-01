from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calm_scopes(ctx: Context) -> list[dict]:
        """List all CALM process-management scopes.

        Returns a list of {ID, Project ID, Name, Description}.
        """
        h = get_calm_headers(ctx)
        return client.get_scopes(h.token, h.base_url)
