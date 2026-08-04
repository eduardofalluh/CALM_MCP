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
