from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calm_projects(ctx: Context) -> list[dict]:
        """List all Cloud ALM projects visible to the configured tenant.

        Returns a list of {ID, Name, Status, Purpose}. Status is human-readable
        ("Active" / "Hidden").
        """
        h = get_calm_headers(ctx)
        return client.get_projects(h.token, h.base_url)

    @mcp.tool()
    def get_calm_tasks(project_id: str, ctx: Context) -> list[dict]:
        """Return all tasks for a Cloud ALM project.

        Args:
            project_id: The CALM project ID (use `get_calm_projects` to discover).

        Each task has: ID, Title, Type (Roadmap Task / Project Task / User Story /
        Sub-task / Requirement / Defect / Quality Gate / Checklist Item) and
        Status (Open / In Progress / Blocked / Done / Not Relevant).
        """
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.get_tasks(project_id, h.token, h.base_url)
