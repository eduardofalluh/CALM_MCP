"""Test-case → requirement linking tool for SAP Cloud ALM MCP server.

Test plans are intentionally NOT modelled here: SAP Cloud ALM's public
Test Management API (``calm-testmanagement/v1`` / ExternalTestCaseServiceAPI)
exposes test *cases* only — there is no test-plan entity, no plan navigation
property on test cases, and the ``/projects/{id}/testPlans`` path returns 404.
Plan membership can therefore only be obtained from a CALM UI export.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:
    """Register test-case linking MCP tools."""

    @mcp.tool()
    def link_calm_test_case_to_requirement(
        test_case_id: str,
        requirement_id: str,
        ctx: Context,
        link_type: str = "covers",
    ) -> dict:
        """Link a test case to a requirement for traceability and coverage tracking.

        Creates a reference from the test case to the requirement. This is the
        standard way to establish test coverage in CALM - showing which test cases
        verify which requirements.

        Requires CALM_ENABLE_WRITES=true.

        Args:
            test_case_id: UUID of the test case (36-char UUID from get_calm_test_cases or create_calm_test_case)
            requirement_id: Task ID of the requirement (from get_calm_requirements or create_calm_requirement)
            link_type: Type of link (default "covers"). Options: "covers", "validates", "references"

        Example:
            test_case_id: "550e8400-e29b-41d4-a716-446655440000"
            requirement_id: "6e76781e-8fd5-4c14-9e7e-2958a4b11a2c"
            link_type: "covers"

        This creates a traceability link visible in CALM UI showing test coverage.
        """
        ensure_writes_enabled()
        if not test_case_id:
            raise ValueError("test_case_id is required")
        if not requirement_id:
            raise ValueError("requirement_id is required")
        h = get_calm_headers(ctx)
        return client.link_test_case_to_requirement(
            token=h.token,
            test_case_id=test_case_id,
            requirement_id=requirement_id,
            link_type=link_type,
            base_url=h.base_url,
            user_email=h.user_email,
        )
