"""Write tools for Cloud ALM tasks (create / update).

Guarded by CALM_ENABLE_WRITES — every tool calls ensure_writes_enabled() first,
so the tools are advertised but refuse to run unless writes are explicitly on.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


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
            assignee_id: Optional assignee — the user's EMAIL address.
            description: Optional task description.
            priority_id: Optional numeric priority (10/20/30/40 = Very High/High/
                Medium/Low).
            external_id: Optional free-text external reference.
            parent_id: Optional parent task ID (required for sub-tasks).
            extra_fields: Optional dict of any other documented task fields to send
                verbatim (e.g. {"scopeId": "...", "storyPoints": 5, "effort": 8.5,
                "workstream": "WS001,WS002", "classificationId": "US_GAP"}).

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
        return client.create_task(
            token=h.token,
            project_id=project_id,
            title=title,
            task_type=task_type,
            status=status,
            start_date=start_date,
            due_date=due_date,
            assignee_id=assignee_id,
            description=description,
            priority_id=priority_id,
            external_id=external_id,
            parent_id=parent_id,
            extra_fields=extra_fields,
            base_url=h.base_url,
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
            assignee_id: Optional assignee — the user's EMAIL address.
            description: Optional description.
            priority_id: Optional numeric priority (10/20/30/40).
            external_id: Optional free-text external reference.
            obsolete: Optional boolean to archive/unarchive the task.
            extra_fields: Optional dict of any other documented task fields to send
                verbatim (e.g. subStatus, scopeId, storyPoints, effort, workstream).

        Returns the updated task, or a confirmation of the fields sent.
        """
        ensure_writes_enabled()
        if not task_id:
            raise ValueError("task_id is required")
        h = get_calm_headers(ctx)
        return client.update_task(
            token=h.token,
            task_id=task_id,
            title=title,
            task_type=task_type,
            status=status,
            start_date=start_date,
            due_date=due_date,
            assignee_id=assignee_id,
            description=description,
            priority_id=priority_id,
            external_id=external_id,
            obsolete=obsolete,
            extra_fields=extra_fields,
            base_url=h.base_url,
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
        return client.delete_task(token=h.token, task_id=task_id, base_url=h.base_url)

    # --- Task sub-entities --------------------------------------------------

    @mcp.tool()
    def create_calm_task_relation(
        task_id: str,
        relation_task_id: str,
        ctx: Context,
        relation_type: str = "0",
    ) -> dict:
        """Link a task to another task (relation). Requires CALM_ENABLE_WRITES=true.

        Args:
            task_id: The task the relation is created on.
            relation_task_id: The related task's ID.
            relation_type: Relation type code (default "0").
        """
        ensure_writes_enabled()
        if not task_id or not relation_task_id:
            raise ValueError("task_id and relation_task_id are required")
        h = get_calm_headers(ctx)
        return client.create_task_relation(
            token=h.token, task_id=task_id, relation_task_id=relation_task_id,
            relation_type=relation_type, base_url=h.base_url,
        )

    @mcp.tool()
    def delete_calm_task_relation(relation_id: str, ctx: Context) -> dict:
        """Delete a task relation by its relation ID. Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not relation_id:
            raise ValueError("relation_id is required")
        h = get_calm_headers(ctx)
        return client.delete_task_relation(token=h.token, relation_id=relation_id, base_url=h.base_url)

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
        return client.set_task_tags(token=h.token, task_id=task_id, tags=tags, base_url=h.base_url)

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
            token=h.token, task_id=task_id, text=text, extra_fields=extra_fields, base_url=h.base_url,
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
            token=h.token, comment_id=comment_id, text=text, extra_fields=extra_fields, base_url=h.base_url,
        )

    @mcp.tool()
    def delete_calm_task_comment(comment_id: str, ctx: Context) -> dict:
        """Delete a task comment by its comment ID. Requires CALM_ENABLE_WRITES=true."""
        ensure_writes_enabled()
        if not comment_id:
            raise ValueError("comment_id is required")
        h = get_calm_headers(ctx)
        return client.delete_task_comment(token=h.token, comment_id=comment_id, base_url=h.base_url)
