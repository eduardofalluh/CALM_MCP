from __future__ import annotations

from typing import Optional

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calm_teams(ctx: Context, project_id: Optional[str] = None) -> list[dict]:
        """List teams - all teams or teams for a specific project.

        Teams group users for project collaboration and assignment.

        Args:
            project_id: Optional. If provided, returns only teams for this project.
                       If omitted, returns all teams visible to the authenticated user.

        Returns teams with fields: ID, Name, Description, Project ID, Members.
        - ID: Unique team identifier
        - Name: Team name
        - Description: Team description or purpose
        - Project ID: The project this team belongs to (may be null for global teams)
        - Members: List of team members (when available for project-specific queries)

        Use cases:
        - Get all teams: get_calm_teams()
        - Get teams for a project: get_calm_teams(project_id="P001")
        - Match task owners to their teams (use with project_id)
        - Find teams available for assignment in a project (use with project_id)
        """
        h = get_calm_headers(ctx)
        if project_id:
            return client.get_project_teams(project_id, h.token, h.base_url)
        return client.get_teams(h.token, h.base_url)
