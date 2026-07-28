from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calm_teams(ctx: Context) -> list[dict]:
        """List all teams visible to the configured CALM tenant.

        Teams group users for project collaboration and assignment. This returns
        all teams the authenticated user has access to.

        Returns teams with fields: ID, Name, Description, Project ID.
        - Project ID: The project this team belongs to (may be null for global teams)
        - Description: Team description or purpose
        """
        h = get_calm_headers(ctx)
        return client.get_teams(h.token, h.base_url)
