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
        project_id: str,
        scope_id: str,
        ctx: Context,
        solution_process_id: str | None = None,
        priority: str | None = None,
        is_prepared: bool | None = None,
        activities: list | None = None,
        references: list | None = None,
        solution_process_flow_id: str | None = None,
        solution_process_flow_diagram_id: str | None = None,
        content_package_id: str | None = None,
    ) -> dict:
        """Create a new manual test case.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            title: Test case title (required).
            project_id: Target project ID (required by the API).
            scope_id: Scope ID (required by the API — omitting it returns
                400 "Provide the missing value: scopeId").
            solution_process_id: Optional solution process ID.
            priority: Optional. "Very High"/"High"/"Medium"/"Low" (or raw 10/20/30/40).
            is_prepared: Optional boolean — whether the test case is prepared.
            activities: Optional list of activity dicts for deep insert. Each may
                include a `toActions` list. Activity fields: title, sequence,
                isInScope. Action fields: title, description, expectedResult,
                sequence, isEvidenceRequired.
            references: Optional list of {name, url} references.
            solution_process_flow_id, solution_process_flow_diagram_id,
            content_package_id: For a *process-linked* test case, pass all four of
                these plus solution_process_id together (content_package_id is
                "CUSTOM" for custom processes).

        Returns the created test case (ID, Project ID, Scope ID, Solution Process ID,
        Title, Prepared, Priority) or the submitted payload.
        """
        ensure_writes_enabled()
        if not title:
            raise ValueError("title is required")
        if not project_id:
            raise ValueError("project_id is required")
        if not scope_id:
            raise ValueError("scope_id is required (the API rejects a test case without one)")
        h = get_calm_headers(ctx)
        return client.create_test_case(
            token=h.token,
            title=title,
            project_id=project_id,
            scope_id=scope_id,
            solution_process_id=solution_process_id,
            priority=priority,
            is_prepared=is_prepared,
            activities=activities,
            references=references,
            solution_process_flow_id=solution_process_flow_id,
            solution_process_flow_diagram_id=solution_process_flow_diagram_id,
            content_package_id=content_package_id,
            base_url=h.base_url, user_email=h.user_email,
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
        if_match: str | None = None,
    ) -> dict:
        """Update fields of an existing manual test case (partial update).

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.
        OData service: PATCH needs an If-Match ETag — which for Test Management is
        the entity's modifiedAt timestamp. If you don't pass `if_match`, it's
        fetched from the entity automatically. Nested Activities/Actions are not
        editable here — use their own endpoints.

        Args:
            test_case_id: UUID of the test case to update.
            title: Optional new title.
            scope_id: Optional scope ID.
            solution_process_id: Optional solution process ID.
            priority: Optional priority label or raw code.
            is_prepared: Optional boolean.
            if_match: Optional ETag/modifiedAt for optimistic locking (auto-fetched
                if omitted).
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
            if_match=if_match,
            base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def delete_calm_test_case(
        test_case_id: str,
        ctx: Context,
        force: bool = False,
        if_match: str | None = None,
    ) -> dict:
        """Delete a manual test case.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.
        OData service: DELETE needs an If-Match ETag (= the entity's modifiedAt;
        auto-fetched if omitted). A plain delete fails if the test case has
        execution history — set `force=true` to also remove its test runs and
        results (needs the calm-api.testcases.force-delete scope on the tenant).

        Args:
            test_case_id: UUID of the test case to delete.
            force: If true, force-delete including runs/results (destructive).
            if_match: Optional ETag/modifiedAt (auto-fetched if omitted).
        """
        ensure_writes_enabled()
        if not test_case_id:
            raise ValueError("test_case_id is required")
        h = get_calm_headers(ctx)
        return client.delete_test_case(
            token=h.token,
            test_case_id=test_case_id,
            force=force,
            if_match=if_match,
            base_url=h.base_url, user_email=h.user_email,
        )

    # --- Activities & Actions (OData; PATCH/DELETE need If-Match=modifiedAt) --

    @mcp.tool()
    def update_calm_test_activity(
        activity_id: str,
        ctx: Context,
        title: str | None = None,
        sequence: int | None = None,
        is_in_scope: bool | None = None,
        if_match: str | None = None,
    ) -> dict:
        """Update a test-case activity (step group). Requires CALM_ENABLE_WRITES=true.
        If-Match (modifiedAt) is auto-fetched if omitted."""
        ensure_writes_enabled()
        if not activity_id:
            raise ValueError("activity_id is required")
        h = get_calm_headers(ctx)
        return client.update_test_activity(
            token=h.token, activity_id=activity_id, title=title, sequence=sequence,
            is_in_scope=is_in_scope, if_match=if_match, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def delete_calm_test_activity(activity_id: str, ctx: Context, if_match: str | None = None) -> dict:
        """Delete a test-case activity. Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not activity_id:
            raise ValueError("activity_id is required")
        h = get_calm_headers(ctx)
        return client.delete_test_activity(
            token=h.token, activity_id=activity_id, if_match=if_match, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def create_calm_test_action(
        activity_id: str,
        title: str,
        ctx: Context,
        description: str | None = None,
        expected_result: str | None = None,
        sequence: int | None = None,
        is_evidence_required: bool | None = None,
    ) -> dict:
        """Create an action (step) under a test-case activity. Requires CALM_ENABLE_WRITES=true.

        Args:
            activity_id: Parent activity UUID.
            title: Action title.
            description / expected_result: Rich-text fields.
            sequence: Numeric order.
            is_evidence_required: Whether evidence is required.
        """
        ensure_writes_enabled()
        if not activity_id or not title:
            raise ValueError("activity_id and title are required")
        h = get_calm_headers(ctx)
        return client.create_test_action(
            token=h.token, activity_id=activity_id, title=title, description=description,
            expected_result=expected_result, sequence=sequence,
            is_evidence_required=is_evidence_required, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def update_calm_test_action(
        action_id: str,
        ctx: Context,
        title: str | None = None,
        description: str | None = None,
        expected_result: str | None = None,
        sequence: int | None = None,
        is_evidence_required: bool | None = None,
        if_match: str | None = None,
    ) -> dict:
        """Update a test-case action. Requires CALM_ENABLE_WRITES=true.
        If-Match (modifiedAt) is auto-fetched if omitted."""
        ensure_writes_enabled()
        if not action_id:
            raise ValueError("action_id is required")
        h = get_calm_headers(ctx)
        return client.update_test_action(
            token=h.token, action_id=action_id, title=title, description=description,
            expected_result=expected_result, sequence=sequence,
            is_evidence_required=is_evidence_required, if_match=if_match, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def delete_calm_test_action(action_id: str, ctx: Context, if_match: str | None = None) -> dict:
        """Delete a test-case action. Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not action_id:
            raise ValueError("action_id is required")
        h = get_calm_headers(ctx)
        return client.delete_test_action(
            token=h.token, action_id=action_id, if_match=if_match, base_url=h.base_url, user_email=h.user_email,
        )
