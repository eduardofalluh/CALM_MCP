"""Tags read/write tools for SAP Cloud ALM MCP server."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:
    """Register tag-related MCP tools."""

    @mcp.tool()
    def get_calm_tags(project_id: str, ctx: Context) -> list[dict]:
        """List all tag definitions for a Cloud ALM project.

        Tags are project-level metadata organized in groups, formatted as
        "Group: Tag" (e.g. "Scope:Baseline", "Tshirt size:L"). Tags must be
        defined before they can be assigned to tasks or requirements.

        Args:
            project_id: Target project ID
        """
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.get_tags(project_id, h.token, h.base_url)

    @mcp.tool()
    def create_calm_tag(
        project_id: str,
        group: str,
        tag: str,
        ctx: Context,
    ) -> dict:
        """Create a new tag definition in a Cloud ALM project.

        Tags must be created before they can be assigned to tasks/requirements.
        The group and tag names are case-sensitive. Requires CALM_ENABLE_WRITES=true.

        Args:
            project_id: Target project ID
            group: Tag group name (e.g. "Scope", "Tshirt size")
            tag: Tag value (e.g. "Baseline", "L")
        """
        ensure_writes_enabled()
        if not project_id:
            raise ValueError("project_id is required")
        if not group:
            raise ValueError("group is required")
        if not tag:
            raise ValueError("tag is required")
        h = get_calm_headers(ctx)
        return client.create_tag(
            token=h.token,
            project_id=project_id,
            group=group,
            tag=tag,
            base_url=h.base_url,
            user_email=h.user_email,
        )
