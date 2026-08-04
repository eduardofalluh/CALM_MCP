"""Features read/write tools for SAP Cloud ALM MCP server."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:
    """Register feature-related MCP tools."""

    @mcp.tool()
    def get_calm_features(project_id: str, ctx: Context) -> list[dict]:
        """List all features for a Cloud ALM project.

        Features are higher-level groupings used for transport tracking and
        release planning. Each feature can contain multiple requirements.

        Args:
            project_id: Target project ID
        """
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.get_features(project_id, h.token, h.base_url)

    @mcp.tool()
    def create_calm_feature(
        project_id: str,
        name: str,
        ctx: Context,
        description: str | None = None,
        external_id: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Create a new feature in a Cloud ALM project.

        Features group requirements for transport and release management. Used
        for baseline requirements in BP workflows. Requires CALM_ENABLE_WRITES=true.

        Args:
            project_id: Target project ID
            name: Feature name
            description: Optional description
            external_id: Optional external system reference
            extra_fields: Additional API fields (status, etc.)
        """
        ensure_writes_enabled()
        if not project_id:
            raise ValueError("project_id is required")
        if not name:
            raise ValueError("name is required")
        h = get_calm_headers(ctx)
        return client.create_feature(
            token=h.token,
            project_id=project_id,
            name=name,
            description=description,
            external_id=external_id,
            extra_fields=extra_fields,
            base_url=h.base_url,
            user_email=h.user_email,
        )
