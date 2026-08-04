"""Project customization read tools for SAP Cloud ALM MCP server."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:
    """Register project customization tools."""

    @mcp.tool()
    def get_calm_project_customization(project_id: str, ctx: Context) -> dict:
        """Get all customization values for a Cloud ALM project.

        Returns picklist values for workstreams, deliverables, and other
        project-specific custom fields. Used to validate task field values
        against the project's allowed options.

        Args:
            project_id: Target project ID

        Returns:
            Dict with keys: Project ID, Workstreams, Deliverables, Custom Fields
        """
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.get_project_customization(project_id, h.token, h.base_url)
