"""Write tools for Cloud ALM manual test cases (create / update).

Guarded by CALM_ENABLE_WRITES — every tool calls ensure_writes_enabled() first.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def create_calm_test_case(
        title: str,
        ctx: Context,
        project_id: str | None = None,
        scope_id: str | None = None,
        solution_process_id: str | None = None,
        priority: str | None = None,
        is_prepared: bool | None = None,
    ) -> dict:
        """Create a new manual test case.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            title: Test case title.
            project_id: Optional target project ID.
            scope_id: Optional scope ID.
            solution_process_id: Optional solution process ID.
            priority: Optional. "Very High"/"High"/"Medium"/"Low" (or raw 10/20/30/40).
            is_prepared: Optional boolean — whether the test case is prepared.

        Returns the created test case (ID, Project ID, Scope ID, Solution Process ID,
        Title, Prepared, Priority) or the submitted payload.
        """
        ensure_writes_enabled()
        if not title:
            raise ValueError("title is required")
        h = get_calm_headers(ctx)
        return client.create_test_case(
            token=h.token,
            title=title,
            project_id=project_id,
            scope_id=scope_id,
            solution_process_id=solution_process_id,
            priority=priority,
            is_prepared=is_prepared,
            base_url=h.base_url,
        )

    @mcp.tool()
    def update_calm_test_case(
        test_case_id: str,
        ctx: Context,
        title: str | None = None,
        scope_id: str | None = None,
        solution_process_id: str | None = None,
        priority: str | None = None,
        is_prepared: bool | None = None,
    ) -> dict:
        """Update fields of an existing manual test case (partial update).

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            test_case_id: ID of the test case to update.
            title: Optional new title.
            scope_id: Optional scope ID.
            solution_process_id: Optional solution process ID.
            priority: Optional priority label or raw code.
            is_prepared: Optional boolean.
        """
        ensure_writes_enabled()
        if not test_case_id:
            raise ValueError("test_case_id is required")
        h = get_calm_headers(ctx)
        return client.update_test_case(
            token=h.token,
            test_case_id=test_case_id,
            title=title,
            scope_id=scope_id,
            solution_process_id=solution_process_id,
            priority=priority,
            is_prepared=is_prepared,
            base_url=h.base_url,
        )
