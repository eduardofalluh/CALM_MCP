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
        program_id: str | None = None,
        deployment_plan_id: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Create a new Cloud ALM project.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.
        Per the API spec, create accepts `name` (and optionally `programId`);
        status/purpose/operationalStatus/phase are managed via other flows, not here.

        Args:
            name: Project name (max 128 chars).
            program_id: Optional program ID this project belongs to.
            deployment_plan_id: Optional deployment plan ID.
            extra_fields: Optional dict of any additional raw fields to attempt.

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
            program_id=program_id,
            deployment_plan_id=deployment_plan_id,
            extra_fields=extra_fields,
            base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def update_calm_project(
        project_id: str,
        ctx: Context,
        name: str | None = None,
        program_id: str | None = None,
        deployment_plan_id: str | None = None,
        if_match: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Update fields of an existing Cloud ALM project (partial update).

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.
        Per the API spec the PATCH body is limited to name, deploymentPlanId, and
        programId (status/operationalStatus/purpose/phase are not patchable here).
        PATCH requires If-Match — the project's `etag` (auto-fetched if omitted).

        Args:
            project_id: ID of the project to update.
            name: Optional new name.
            program_id: Optional program ID.
            deployment_plan_id: Optional deployment plan ID.
            if_match: Optional ETag for optimistic locking (auto-fetched if omitted).
            extra_fields: Optional dict of any additional raw fields to attempt.
        """
        ensure_writes_enabled()
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.update_project(
            token=h.token,
            project_id=project_id,
            name=name,
            program_id=program_id,
            deployment_plan_id=deployment_plan_id,
            if_match=if_match,
            extra_fields=extra_fields,
            base_url=h.base_url, user_email=h.user_email,
        )

    # --- Timeboxes (no If-Match) -------------------------------------------

    @mcp.tool()
    def create_calm_timebox(
        project_id: str,
        ctx: Context,
        name: str | None = None,
        timebox_type: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        closed: bool | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Create a timebox in a project. Requires CALM_ENABLE_WRITES=true.

        Args:
            project_id: The project to add the timebox to.
            name: Timebox name.
            timebox_type: Numeric type (e.g. 0).
            start_date / end_date: ISO dates (YYYY-MM-DD). Note: `start_date` is
                sent correctly but CALM may return it null on create — a timebox's
                start is typically derived server-side from the preceding phase;
                set it via update_calm_timebox if you need an explicit value.
            closed: Whether the timebox is closed.
            extra_fields: Any additional raw fields.
        """
        ensure_writes_enabled()
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.create_timebox(
            token=h.token, project_id=project_id, name=name, timebox_type=timebox_type,
            start_date=start_date, end_date=end_date, closed=closed,
            extra_fields=extra_fields, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def update_calm_timebox(
        timebox_id: str,
        ctx: Context,
        name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        closed: bool | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Update a timebox by its ID (partial). Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not timebox_id:
            raise ValueError("timebox_id is required")
        h = get_calm_headers(ctx)
        return client.update_timebox(
            token=h.token, timebox_id=timebox_id, name=name, start_date=start_date,
            end_date=end_date, closed=closed, extra_fields=extra_fields, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def delete_calm_timebox(timebox_id: str, ctx: Context) -> dict:
        """Delete a timebox by its ID. Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not timebox_id:
            raise ValueError("timebox_id is required")
        h = get_calm_headers(ctx)
        return client.delete_timebox(token=h.token, timebox_id=timebox_id, base_url=h.base_url, user_email=h.user_email)
