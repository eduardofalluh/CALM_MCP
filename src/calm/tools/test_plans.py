"""Test plan read/write tools for SAP Cloud ALM MCP server."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:
    """Register test plan-related MCP tools."""

    @mcp.tool()
    def get_calm_test_plans(project_id: str, ctx: Context) -> list[dict]:
        """List all test plans for a Cloud ALM project.

        Test plans organize test cases into execution sets. Each plan can be
        assigned to testers and tracked separately.

        Args:
            project_id: Target project ID
        """
        if not project_id:
            raise ValueError("project_id is required")
        h = get_calm_headers(ctx)
        return client.get_test_plans(project_id, h.token, h.base_url)

    @mcp.tool()
    def create_calm_test_plan(
        project_id: str,
        name: str,
        ctx: Context,
        description: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Create a new test plan in a Cloud ALM project.

        Test plans group test cases for execution tracking. Used to organize
        customer enablement scripts and other test scenarios.
        Requires CALM_ENABLE_WRITES=true.

        Args:
            project_id: Target project ID
            name: Test plan name
            description: Optional description
            extra_fields: Additional API fields
        """
        ensure_writes_enabled()
        if not project_id:
            raise ValueError("project_id is required")
        if not name:
            raise ValueError("name is required")
        h = get_calm_headers(ctx)
        return client.create_test_plan(
            token=h.token,
            project_id=project_id,
            name=name,
            description=description,
            extra_fields=extra_fields,
            base_url=h.base_url,
            user_email=h.user_email,
        )

    @mcp.tool()
    def assign_calm_test_case_to_plan(
        test_plan_id: str,
        test_case_id: str,
        ctx: Context,
        tester_email: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Assign a test case to a test plan, optionally with a tester.

        Requires CALM_ENABLE_WRITES=true.

        Args:
            test_plan_id: Target test plan ID
            test_case_id: Test case to assign
            tester_email: Optional email of assigned tester
            extra_fields: Additional API fields
        """
        ensure_writes_enabled()
        if not test_plan_id:
            raise ValueError("test_plan_id is required")
        if not test_case_id:
            raise ValueError("test_case_id is required")
        h = get_calm_headers(ctx)
        return client.assign_test_case_to_plan(
            token=h.token,
            test_plan_id=test_plan_id,
            test_case_id=test_case_id,
            tester_email=tester_email,
            extra_fields=extra_fields,
            base_url=h.base_url,
            user_email=h.user_email,
        )

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
