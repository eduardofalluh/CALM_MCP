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
            assignee_id: Optional assignee user ID.
            description: Optional task description.

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
        obsolete: bool | None = None,
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
            assignee_id: Optional assignee user ID.
            description: Optional description.
            obsolete: Optional boolean to archive/unarchive the task.

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
            obsolete=obsolete,
            base_url=h.base_url,
        )
