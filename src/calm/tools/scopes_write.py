"""Write tools for Cloud ALM process-management scopes (create / update).

Guarded by CALM_ENABLE_WRITES — every tool calls ensure_writes_enabled() first.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def create_calm_scope(
        project_id: str,
        name: str,
        ctx: Context,
        description: str | None = None,
    ) -> dict:
        """Create a new process-management scope in a project.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            project_id: Target CALM project ID.
            name: Scope name.
            description: Optional description.

        Returns the created scope (ID, Project ID, Name, Description) or the payload.
        """
        ensure_writes_enabled()
        if not project_id:
            raise ValueError("project_id is required")
        if not name:
            raise ValueError("name is required")
        h = get_calm_headers(ctx)
        return client.create_scope(
            token=h.token,
            project_id=project_id,
            name=name,
            description=description,
            base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def update_calm_scope(
        scope_id: str,
        ctx: Context,
        name: str | None = None,
        description: str | None = None,
        if_match: str | None = None,
    ) -> dict:
        """Update fields of an existing scope (partial update).

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.
        OData service: an If-Match ETag is fetched and sent defensively (its
        requirement on scopes is unconfirmed); a supplied `if_match` wins.

        Args:
            scope_id: ID of the scope to update.
            name: Optional new name.
            description: Optional new description.
            if_match: Optional ETag for optimistic locking (auto-fetched if omitted).
        """
        ensure_writes_enabled()
        if not scope_id:
            raise ValueError("scope_id is required")
        h = get_calm_headers(ctx)
        return client.update_scope(
            token=h.token,
            scope_id=scope_id,
            name=name,
            description=description,
            if_match=if_match,
            base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def delete_calm_scope(
        scope_id: str,
        ctx: Context,
        if_match: str | None = None,
    ) -> dict:
        """Delete a process-management scope.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.
        OData service; an If-Match ETag is sent defensively (auto-fetched if omitted).
        """
        ensure_writes_enabled()
        if not scope_id:
            raise ValueError("scope_id is required")
        h = get_calm_headers(ctx)
        return client.delete_scope(
            token=h.token,
            scope_id=scope_id,
            if_match=if_match,
            base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def assign_calm_scenario_versions(scope_id: str, version_ids: list, ctx: Context) -> dict:
        """Assign solution-scenario versions to a scope. Requires CALM_ENABLE_WRITES=true.

        Args:
            scope_id: The scope to assign versions to.
            version_ids: List of solutionScenarioVersion UUIDs.
        """
        ensure_writes_enabled()
        if not scope_id:
            raise ValueError("scope_id is required")
        h = get_calm_headers(ctx)
        return client.assign_scenario_versions(
            token=h.token, scope_id=scope_id, version_ids=version_ids, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def update_calm_scope_assignments(assignments: list, ctx: Context) -> dict:
        """Scope/unscope solution processes (collection-level). Requires CALM_ENABLE_WRITES=true.

        Args:
            assignments: List of dicts, each with scopeId, solutionScenarioVersionId,
                solutionProcessVersionId, isScoped (all required) and an optional
                statusId (EMPTY/DESIGN/REALIZATION/PRODUCTION/MAINTENANCE/OBSOLETE).
        """
        ensure_writes_enabled()
        if not assignments:
            raise ValueError("assignments must be a non-empty list")
        h = get_calm_headers(ctx)
        return client.update_scope_assignments(
            token=h.token, assignments=assignments, base_url=h.base_url, user_email=h.user_email,
        )
