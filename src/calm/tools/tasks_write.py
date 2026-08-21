"""Write tools for Cloud ALM tasks (create / update).

Guarded by CALM_ENABLE_WRITES — every tool calls ensure_writes_enabled() first,
so the tools are advertised but refuse to run unless writes are explicitly on.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers
from src.calm.tools.user_resolver import resolve_assignee


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def create_calm_task(
        project_id: str,
        title: str,
        task_type: str,
        ctx: Context,
        status: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        assignee_id: str | None = None,
        description: str | None = None,
        priority_id: int | None = None,
        external_id: str | None = None,
        parent_id: str | None = None,
        extra_fields: dict | None = None,
        acting_user_email: str | None = None,
    ) -> dict:
        """Create a new task in a Cloud ALM project.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            project_id: Target CALM project ID (use `get_calm_projects` to discover).
            title: Task title.
            task_type: Human label ("Project Task", "User Story", "Requirement",
                "Defect", "Quality Gate", "Sub-task", "Checklist Item", "Roadmap Task")
                or a raw CALM code (e.g. "CALMTASK").
            status: Optional. Human label ("Open", "In Progress", "Blocked", "Done",
                "Not Relevant") or a raw CALM status code. The valid statuses depend
                on the task type.
            start_date: Optional ISO date (YYYY-MM-DD).
            due_date: Optional ISO date (YYYY-MM-DD).
            assignee_id: Optional assignee — pass email, name, or UUID. The tool
                automatically resolves it (tries API lookup, manual mapping, then
                email pass-through). Just pass "eduardo.falluh@syntax.com" or
                "Eduardo Falluh" and it works.
            description: Optional task description.
            priority_id: Optional numeric priority (10/20/30/40 = Very High/High/
                Medium/Low).
            external_id: Optional free-text external reference.
            parent_id: Optional parent task ID (required for sub-tasks).
            extra_fields: Optional dict of any other documented task fields to send
                verbatim (e.g. {"scopeId": "...", "storyPoints": 5, "effort": 8.5,
                "workstream": "WS001,WS002", "classificationId": "US_GAP"}).
            acting_user_email: Optional email of the user performing this action
                (for CALM audit logs). The agent should pass the current user's email
                from the chat session context. Example: "eduardo.falluh@syntax.com"

        Returns the created task (ID, Title, Type, Status, dates, AssigneeName,
        ApprovalState, Obsolete), or the submitted payload if the API returns no body.
        """
        ensure_writes_enabled()
        if not project_id:
            raise ValueError("project_id is required")
        if not title:
            raise ValueError("title is required")
        if not task_type:
            raise ValueError("task_type is required")
        h = get_calm_headers(ctx)

        # Smart assignee resolution - handles emails, names, UUIDs automatically
        resolved_assignee = None
        if assignee_id:
            resolved_assignee = resolve_assignee(
                user_identifier=assignee_id,
                project_id=project_id,
                token=h.token,
                base_url=h.base_url,
            )

        return client.create_task(
            token=h.token,
            project_id=project_id,
            title=title,
            task_type=task_type,
            status=status,
            start_date=start_date,
            due_date=due_date,
            assignee_id=resolved_assignee,
            description=description,
            priority_id=priority_id,
            external_id=external_id,
            parent_id=parent_id,
            extra_fields=extra_fields,
            base_url=h.base_url, user_email=acting_user_email or h.user_email,
        )

    @mcp.tool()
    def update_calm_task(
        task_id: str,
        ctx: Context,
        title: str | None = None,
        task_type: str | None = None,
        status: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        assignee_id: str | None = None,
        description: str | None = None,
        priority_id: int | None = None,
        external_id: str | None = None,
        obsolete: bool | None = None,
        extra_fields: dict | None = None,
        acting_user_email: str | None = None,
    ) -> dict:
        """Update fields of an existing Cloud ALM task (partial update).

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.
        Only the fields you pass are changed.

        Args:
            task_id: ID of the task to update (use `get_calm_tasks` to discover).
            title: Optional new title.
            task_type: Optional new type (human label or raw code). Also required
                when changing `status` by human label so the correct code is chosen.
            status: Optional new status (human label or raw CALM code). If given as a
                human label, pass `task_type` too.
            start_date / due_date: Optional ISO dates (YYYY-MM-DD).
            assignee_id: Optional assignee — pass email, name, or UUID. The tool
                automatically resolves it (tries API lookup, manual mapping, then
                email pass-through). Just pass "eduardo.falluh@syntax.com" or
                "Eduardo Falluh" and it works.
            description: Optional description.
            priority_id: Optional numeric priority (10/20/30/40).
            external_id: Optional free-text external reference.
            obsolete: Optional boolean to archive/unarchive the task.
            extra_fields: Optional dict of any other documented task fields to send
                verbatim (e.g. subStatus, scopeId, storyPoints, effort, workstream).
            acting_user_email: Optional email of the user performing this action
                (for CALM audit logs). The agent should pass the current user's email.

        Returns the updated task, or a confirmation of the fields sent.
        """
        ensure_writes_enabled()
        if not task_id:
            raise ValueError("task_id is required")
        h = get_calm_headers(ctx)

        # Smart assignee resolution - handles emails, names, UUIDs automatically
        resolved_assignee = assignee_id
        if assignee_id:
            # Need project_id for user lookup - extract from task if not in extra_fields
            proj_id = (extra_fields or {}).get("projectId")
            if not proj_id:
                # Fetch task to get project_id
                try:
                    task_data = client._get(
                        f"{client._base_url(h.base_url)}/api/calm-tasks/v1/tasks/{task_id}",
                        h.token
                    )
                    proj_id = task_data.get("projectId")
                except Exception:
                    pass  # Can't resolve, use email as-is

            if proj_id:
                resolved_assignee = resolve_assignee(
                    user_identifier=assignee_id,
                    project_id=proj_id,
                    token=h.token,
                    base_url=h.base_url,
                )

        return client.update_task(
            token=h.token,
            task_id=task_id,
            title=title,
            task_type=task_type,
            status=status,
            start_date=start_date,
            due_date=due_date,
            assignee_id=resolved_assignee,
            description=description,
            priority_id=priority_id,
            external_id=external_id,
            obsolete=obsolete,
            extra_fields=extra_fields,
            base_url=h.base_url, user_email=acting_user_email or h.user_email,
        )

    @mcp.tool()
    def delete_calm_task(task_id: str, ctx: Context) -> dict:
        """Delete a Cloud ALM task.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.
        Prefer `update_calm_task(obsolete=true)` to archive rather than hard-delete
        when you only want to hide the task.

        Args:
            task_id: ID of the task to delete.
        """
        ensure_writes_enabled()
        if not task_id:
            raise ValueError("task_id is required")
        h = get_calm_headers(ctx)
        return client.delete_task(token=h.token, task_id=task_id, base_url=h.base_url, user_email=h.user_email)

    # --- Task sub-entities --------------------------------------------------

    @mcp.tool()
    def create_calm_task_relation(
        task_id: str,
        relation_task_id: str,
        ctx: Context,
        relation_type: str = "0",
    ) -> dict:
        """Link a task to another task (creates a relation/dependency). Requires CALM_ENABLE_WRITES=true.

        Creates a directional relationship from task_id to relation_task_id. This is used for
        dependencies, blockers, related work, and other task-to-task connections.

        Args:
            task_id: The source task (the task the relation is created on).
            relation_task_id: The target task's ID (the related/dependent task).
            relation_type: Relation type code. Common types in SAP Cloud ALM:
                - "0" - Generic relation/related to (default)
                - "1" - Depends on (task_id depends on relation_task_id)
                - "2" - Blocks (task_id blocks relation_task_id)
                - "3" - Predecessor/Successor
                - "4" - Parent/Child (alternative to parent_id field)

                Note: The exact codes may vary by your CALM tenant configuration.
                Check your CALM UI's relation type dropdown for available types.

        Example - Create dependency:
            Task T-001 depends on Task T-002 being completed first:
            create_calm_task_relation(
                task_id="T-001",
                relation_task_id="T-002",
                relation_type="1"  # "depends on"
            )
            Result: T-001 cannot start until T-002 is done

        Example - Create blocker:
            Task T-003 blocks Task T-004:
            create_calm_task_relation(
                task_id="T-003",
                relation_task_id="T-004",
                relation_type="2"  # "blocks"
            )
            Result: T-004 is blocked by T-003

        Returns the created relation object with relation ID (for later deletion).
        """
        ensure_writes_enabled()
        if not task_id or not relation_task_id:
            raise ValueError("task_id and relation_task_id are required")
        h = get_calm_headers(ctx)
        return client.create_task_relation(
            token=h.token, task_id=task_id, relation_task_id=relation_task_id,
            relation_type=relation_type, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def delete_calm_task_relation(relation_id: str, ctx: Context) -> dict:
        """Delete a task relation by its relation ID. Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not relation_id:
            raise ValueError("relation_id is required")
        h = get_calm_headers(ctx)
        return client.delete_task_relation(token=h.token, relation_id=relation_id, base_url=h.base_url, user_email=h.user_email)

    @mcp.tool()
    def set_calm_task_tags(task_id: str, tags: list, ctx: Context) -> dict:
        """Replace a task's tag assignments. Requires CALM_ENABLE_WRITES=true.

        Args:
            task_id: The task to tag.
            tags: List of tag strings, each formatted "Group: Tag".
        """
        ensure_writes_enabled()
        if not task_id:
            raise ValueError("task_id is required")
        h = get_calm_headers(ctx)
        return client.set_task_tags(token=h.token, task_id=task_id, tags=tags, base_url=h.base_url, user_email=h.user_email)

    @mcp.tool()
    def create_calm_task_comment(
        task_id: str,
        ctx: Context,
        text: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Add a comment to a task. Requires CALM_ENABLE_WRITES=true.

        The comment body field is not fully documented; `text` is sent as-is and
        `extra_fields` can override/add fields if your tenant expects a different key.
        """
        ensure_writes_enabled()
        if not task_id:
            raise ValueError("task_id is required")
        h = get_calm_headers(ctx)
        return client.create_task_comment(
            token=h.token, task_id=task_id, text=text, extra_fields=extra_fields, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def update_calm_task_comment(
        comment_id: str,
        ctx: Context,
        text: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Update a task comment by its comment ID. Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not comment_id:
            raise ValueError("comment_id is required")
        h = get_calm_headers(ctx)
        return client.update_task_comment(
            token=h.token, comment_id=comment_id, text=text, extra_fields=extra_fields, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def delete_calm_task_comment(comment_id: str, ctx: Context) -> dict:
        """Delete a task comment by its comment ID. Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not comment_id:
            raise ValueError("comment_id is required")
        h = get_calm_headers(ctx)
        return client.delete_task_comment(token=h.token, comment_id=comment_id, base_url=h.base_url, user_email=h.user_email)

    # --- Requirements (tasks of type "Requirement") -------------------------

    @mcp.tool()
    def create_calm_requirement(
        project_id: str,
        title: str,
        ctx: Context,
        status: str | None = None,
        description: str | None = None,
        assignee_id: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        priority_id: int | None = None,
        sub_status: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Create a requirement (a task of type "Requirement"). Requires CALM_ENABLE_WRITES=true.

        Args:
            project_id: Target CALM project ID.
            title: Requirement title.
            status: Optional human label ("Open", "In Progress", "Blocked", "Done",
                "Not Relevant") — resolved to the requirement (CIPREQU*) codes.
            description / assignee_id (email) / start_date / due_date (YYYY-MM-DD) /
            priority_id (10/20/30/40): optional, as for tasks.
            sub_status: Optional requirement sub-status code — one of CREATED,
                TO_BE_APPROVED, IN_PLANNING, IN_REALIZATION, APPROVED_FOR_DEPLOYMENT,
                SUCCESSFULLY_TESTED, CONFIRMED, BLOCKED, NOT_PLANNED.
            extra_fields: Any other raw task fields.
        """
        ensure_writes_enabled()
        if not project_id:
            raise ValueError("project_id is required")
        if not title:
            raise ValueError("title is required")
        extra = dict(extra_fields or {})
        if sub_status is not None:
            extra["subStatus"] = sub_status
        h = get_calm_headers(ctx)
        return client.create_task(
            token=h.token, project_id=project_id, title=title, task_type="Requirement",
            status=status, start_date=start_date, due_date=due_date, assignee_id=assignee_id,
            description=description, priority_id=priority_id, extra_fields=extra or None,
            base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def update_calm_requirement(
        task_id: str,
        ctx: Context,
        title: str | None = None,
        status: str | None = None,
        description: str | None = None,
        assignee_id: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        priority_id: int | None = None,
        sub_status: str | None = None,
        obsolete: bool | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Update a requirement by task ID (partial). Requires CALM_ENABLE_WRITES=true.

        The type is pinned to "Requirement" so a human `status` label resolves to the
        correct requirement (CIPREQU*) code. `sub_status` sets the requirement
        sub-status code (see create_calm_requirement for values).
        """
        ensure_writes_enabled()
        if not task_id:
            raise ValueError("task_id is required")
        extra = dict(extra_fields or {})
        if sub_status is not None:
            extra["subStatus"] = sub_status
        h = get_calm_headers(ctx)
        return client.update_task(
            token=h.token, task_id=task_id, task_type="Requirement", title=title, status=status,
            start_date=start_date, due_date=due_date, assignee_id=assignee_id,
            description=description, priority_id=priority_id, obsolete=obsolete,
            extra_fields=extra or None, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def delete_calm_requirement(task_id: str, ctx: Context) -> dict:
        """Delete a requirement by its task ID. Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not task_id:
            raise ValueError("task_id is required")
        h = get_calm_headers(ctx)
        return client.delete_task(token=h.token, task_id=task_id, base_url=h.base_url, user_email=h.user_email)
