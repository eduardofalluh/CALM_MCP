"""User/team member tools for SAP Cloud ALM MCP server."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:
    """Register user-related MCP tools."""

    @mcp.tool()
    def get_calm_project_users(project_id: str, ctx: Context) -> list[dict]:
        """List all users/team members for a Cloud ALM project.

        Returns the correct assignee IDs to use when creating or updating tasks.
        This prevents the 'Former Member' issue when assigning tasks.

        IMPORTANT: Use the 'ID' field from this response as the assignee_id
        parameter in create_calm_task or update_calm_task. Do NOT use email
        addresses directly as assignee_id.

        Args:
            project_id: Target project ID

        Returns:
            List of users with:
            - ID: The correct assignee ID to use (NOT the email)
            - Email: User's email address
            - Name: Full display name
            - Role: Project role
            - Active: Whether user is active

        Example workflow:
            1. Call get_calm_project_users(project_id="P001")
            2. Find the user you want (e.g., by email "eduardo.falluh@syntax.com")
            3. Extract their ID field (e.g., "a1b2c3d4-...")
            4. Use that ID in create_calm_task(assignee_id="a1b2c3d4-...")
        """
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.get_project_users(project_id, h.token, h.base_url)
