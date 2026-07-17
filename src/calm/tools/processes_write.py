"""Write tools for Cloud ALM business & solution processes (create / update).

Guarded by CALM_ENABLE_WRITES — every tool calls ensure_writes_enabled() first.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:

    # --- Business processes -------------------------------------------------

    @mcp.tool()
    def create_calm_business_process(
        name: str,
        ctx: Context,
        description: str | None = None,
    ) -> dict:
        """Create a new business process.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            name: Business process name.
            description: Optional description.

        Returns the created process (ID, Name, Description) or the submitted payload.
        """
        ensure_writes_enabled()
        if not name:
            raise ValueError("name is required")
        h = get_calm_headers(ctx)
        return client.create_business_process(
            token=h.token, name=name, description=description, base_url=h.base_url
        )

    @mcp.tool()
    def update_calm_business_process(
        business_process_id: str,
        ctx: Context,
        name: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Update fields of an existing business process (partial update).

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            business_process_id: ID of the business process to update.
            name: Optional new name.
            description: Optional new description.
        """
        ensure_writes_enabled()
        if not business_process_id:
            raise ValueError("business_process_id is required")
        h = get_calm_headers(ctx)
        return client.update_business_process(
            token=h.token,
            business_process_id=business_process_id,
            name=name,
            description=description,
            base_url=h.base_url,
        )

    # --- Solution processes -------------------------------------------------

    @mcp.tool()
    def create_calm_solution_process(
        name: str,
        ctx: Context,
        description: str | None = None,
        status: str | None = None,
        countries: list | None = None,
        state: str | None = None,
    ) -> dict:
        """Create a new solution process.

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            name: Solution process name.
            description: Optional description.
            status: Optional status string.
            countries: Optional list of country codes.
            state: Optional state string.

        Returns the created process (ID, Name, Description, Status, Countries, State)
        or the submitted payload.
        """
        ensure_writes_enabled()
        if not name:
            raise ValueError("name is required")
        h = get_calm_headers(ctx)
        return client.create_solution_process(
            token=h.token,
            name=name,
            description=description,
            status=status,
            countries=countries,
            state=state,
            base_url=h.base_url,
        )

    @mcp.tool()
    def update_calm_solution_process(
        solution_process_id: str,
        ctx: Context,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        countries: list | None = None,
        state: str | None = None,
    ) -> dict:
        """Update fields of an existing solution process (partial update).

        Requires CALM_ENABLE_WRITES=true on the server, otherwise returns an error.

        Args:
            solution_process_id: ID of the solution process to update.
            name: Optional new name.
            description: Optional new description.
            status: Optional status.
            countries: Optional list of country codes.
            state: Optional state.
        """
        ensure_writes_enabled()
        if not solution_process_id:
            raise ValueError("solution_process_id is required")
        h = get_calm_headers(ctx)
        return client.update_solution_process(
            token=h.token,
            solution_process_id=solution_process_id,
            name=name,
            description=description,
            status=status,
            countries=countries,
            state=state,
            base_url=h.base_url,
        )
