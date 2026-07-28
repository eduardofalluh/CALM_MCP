from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calm_timeboxes(project_id: str, ctx: Context) -> list[dict]:
        """List all timeboxes (sprints/iterations) for a Cloud ALM project.

        Timeboxes are time-bounded periods used to organize project work
        (e.g., Sprint 1, Q2 2026, Release 3.0).

        Args:
            project_id: The CALM project ID (use `get_calm_projects` to discover).

        Returns timeboxes with fields: ID, Project ID, Name, Type, StartDate,
        EndDate, Closed.
        - Type: Numeric type code (e.g., 0 for sprint)
        - Closed: Boolean indicating if the timebox is closed/completed
        - StartDate/EndDate: ISO date strings (YYYY-MM-DD) or null
        """
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.get_timeboxes(project_id, h.token, h.base_url)
