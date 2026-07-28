from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calm_projects(ctx: Context) -> list[dict]:
        """List all Cloud ALM projects visible to the configured tenant.

        Returns projects with fields: ID, Name, Status, Purpose, OperationalStatus.
        - Status: "Active" or "Hidden" (project visibility)
        - OperationalStatus: Current operational state of the project
        """
        h = get_calm_headers(ctx)
        return client.get_projects(h.token, h.base_url)

    @mcp.tool()
    def get_calm_tasks(project_id: str, ctx: Context, task_type: str | None = None) -> list[dict]:
        """Return tasks for a Cloud ALM project, optionally filtered by type.

        Args:
            project_id: The CALM project ID (use `get_calm_projects` to discover).
            task_type: Optional type filter — human label ("Requirement", "Project
                Task", "User Story", "Defect", "Risk", …) or a raw CALM code. Omit
                for all tasks. (Requirements are tasks with type "Requirement".)

        Returns tasks with fields: ID, Display ID, Title, Type, Status, StartDate,
        DueDate, AssigneeName, ApprovalState, Obsolete, Effort.
        - ID: Internal CALM ID (e.g., "3-43248")
        - Display ID: Human-readable ID shown in UI (e.g., "4000", may be null)
        - Type: Roadmap Task, Project Task, User Story, Sub-task, Requirement,
          Defect, Quality Gate, Checklist Item, or Risk
        - Status: Open, In Progress, Blocked, Done, or Not Relevant
        - ApprovalState: Approved, Rejected, Ready for Approval, or No Approval Required
        - Obsolete: Boolean indicating if task is archived
        - Effort: Effort estimate (e.g., "8 Hours", may be null if not set)
        """
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.get_tasks(project_id, h.token, h.base_url, task_type=task_type)

    @mcp.tool()
    def get_calm_requirements(project_id: str, ctx: Context) -> list[dict]:
        """Return the requirements of a Cloud ALM project.

        Requirements are tasks of type "Requirement" served by the Tasks API; this
        is a convenience wrapper over `get_calm_tasks` with the type pinned.

        Args:
            project_id: The CALM project ID.

        Returns the same fields as `get_calm_tasks` (Type will be "Requirement").
        """
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.get_tasks(project_id, h.token, h.base_url, task_type="Requirement")
