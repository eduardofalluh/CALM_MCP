from __future__ import annotations

from typing import Literal, Optional

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def get_calm_processes(
        ctx: Context,
        process_type: Optional[Literal["business", "solution"]] = None
    ) -> list[dict]:
        """List CALM processes - business processes, solution processes, or both.

        Business processes: High-level workflows {ID, Name, Description}
        Solution processes: Technical implementations {ID, Name, Description, Status, Countries, State}

        Args:
            process_type: Filter by type:
                - "business": Only business processes
                - "solution": Only solution processes
                - None: Both types (default)

        Returns list with Type field ("Business Process" or "Solution Process") when both types requested.
        """
        h = get_calm_headers(ctx)

        if process_type == "business":
            return client.get_business_processes(h.token, h.base_url)
        elif process_type == "solution":
            return client.get_solution_processes(h.token, h.base_url)
        else:
            business = client.get_business_processes(h.token, h.base_url)
            solution = client.get_solution_processes(h.token, h.base_url)
            for bp in business:
                bp["Type"] = "Business Process"
            for sp in solution:
                sp["Type"] = "Solution Process"
            return business + solution
