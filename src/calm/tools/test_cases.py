from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calm_test_cases(ctx: Context) -> list[dict]:
        """List all manual test cases from the CALM test management API.

        Returns a list of {Project ID, Scope ID, Solution Process ID, Title,
        Prepared, Priority}. Priority is human-readable
        ("Very High" / "High" / "Medium" / "Low").
        """
        h = get_calm_headers(ctx)
        return client.get_test_cases(h.token, h.base_url)
