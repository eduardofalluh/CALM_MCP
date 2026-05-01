from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calm_business_processes(ctx: Context) -> list[dict]:
        """List all CALM business processes (process authoring API).

        Returns a list of {ID, Name, Description}.
        """
        h = get_calm_headers(ctx)
        return client.get_business_processes(h.token, h.base_url)

    @mcp.tool()
    def get_calm_solution_processes(ctx: Context) -> list[dict]:
        """List all CALM solution processes (process authoring API).

        Returns a list of {ID, Name, Description, Status, Countries, State}.
        """
        h = get_calm_headers(ctx)
        return client.get_solution_processes(h.token, h.base_url)
