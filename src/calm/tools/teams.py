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

    @mcp.tool()
    def get_calm_project_teams(ctx: Context, project_id: str) -> list[dict]:
        """List all teams for a specific CALM project.

        Teams group users for project collaboration and assignment. This returns
        teams associated with a specific project, including both project-specific
        teams and global teams assigned to the project.

        This tool tries multiple API endpoints to maximize compatibility:
        1. Project-specific teams endpoint
        2. Teams endpoint with project filter
        3. Falls back to filtering all teams by project ID

        Args:
            project_id: The CALM project ID to get teams for

        Returns teams with fields: ID, Name, Description, Project ID, Members.
        - ID: Unique team identifier
        - Name: Team name
        - Description: Team description or purpose
        - Project ID: The project this team belongs to
        - Members: List of team members (when available)

        Use this when you need to:
        - Match project task owners to their teams
        - Get team definitions for a specific project
        - Find which teams are available for assignment in a project
        """
        h = get_calm_headers(ctx)
        return client.get_project_teams(project_id, h.token, h.base_url)
