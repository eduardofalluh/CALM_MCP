"""Write tools for Cloud ALM projects (create / update).

Guarded by CALM_ENABLE_WRITES — every tool calls ensure_writes_enabled() first.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def create_calm_project(
        name: str,
        ctx: Context,
        status: str | None = None,
        purpose: str | None = None,
        operational_status: str | None = None,
        phase_id: str | None = None,
        program_id: str | None = None,
        deployment_plan_id: str | None = None,
    ) -> dict:
        """Create a new Cloud ALM project.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            name: Project name.
            status: Optional. "Active" or "Hidden" (or raw code O/C).
            purpose: Optional comma-separated purpose (e.g. "IMPLEMENTATION,SERVICE_DELIVERY").
            operational_status: Optional operational status code (e.g. "ONTRK").
            phase_id: Optional current-phase ID (2025+).
            program_id: Optional program ID this project belongs to.
            deployment_plan_id: Optional deployment plan ID.

        Returns the created project (ID, Name, Status, Purpose, OperationalStatus)
        or the submitted payload if the API returns no body.
        """
        ensure_writes_enabled()
        if not name:
            raise ValueError("name is required")
        h = get_calm_headers(ctx)
        return client.create_project(
            token=h.token,
            name=name,
            status=status,
            purpose=purpose,
            operational_status=operational_status,
            phase_id=phase_id,
            program_id=program_id,
            deployment_plan_id=deployment_plan_id,
            base_url=h.base_url,
        )

    @mcp.tool()
    def update_calm_project(
        project_id: str,
        ctx: Context,
        name: str | None = None,
        status: str | None = None,
        purpose: str | None = None,
        operational_status: str | None = None,
        phase_id: str | None = None,
        program_id: str | None = None,
        deployment_plan_id: str | None = None,
    ) -> dict:
        """Update fields of an existing Cloud ALM project (partial update).

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.
        Only the fields you pass are changed.

        Args:
            project_id: ID of the project to update.
            name: Optional new name.
            status: Optional "Active"/"Hidden" (or raw code O/C).
            purpose: Optional comma-separated purpose.
            operational_status: Optional operational status code (e.g. "ONTRK").
            phase_id: Optional current-phase ID (2025+).
            program_id: Optional program ID.
            deployment_plan_id: Optional deployment plan ID.
        """
        ensure_writes_enabled()
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.update_project(
            token=h.token,
            project_id=project_id,
            name=name,
            status=status,
            purpose=purpose,
            operational_status=operational_status,
            phase_id=phase_id,
            program_id=program_id,
            deployment_plan_id=deployment_plan_id,
            base_url=h.base_url,
        )
