"""Test suite for unified consolidated MCP tools (Phase 1).

This test suite validates:
1. New unified calm_resource() tool works correctly
2. All resource types are properly routed to client functions
3. Error handling is consistent
4. Phase 1 restrictions (read-only) are enforced

Success criteria: 100% test pass rate
"""

from unittest.mock import MagicMock, patch

import pytest


class MockContext:
    """Mock FastMCP context with CALM credentials."""
    def __init__(self):
        self.meta = {
            "CALM_TOKEN": "test-token-12345",
            "CALM_BASE_URL": "https://test.calm.cloud.sap",
        }


@pytest.fixture
def mock_ctx():
    """Create a mock context."""
    return MockContext()


class TestUnifiedToolProjects:
    """Test unified tool for projects resource."""

    @patch("src.calm.client.get_projects")
    def test_list_projects(self, mock_get_projects, mock_ctx):
        """Test listing projects via unified tool."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get_projects.return_value = [
            {"ID": "P001", "Name": "Test Project 1"},
            {"ID": "P002", "Name": "Test Project 2"},
        ]

        # Get the tool function
        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="projects", operation="list")

        assert len(result) == 2
        assert result[0]["ID"] == "P001"
        mock_get_projects.assert_called_once_with("test-token-12345", "https://test.calm.cloud.sap")


class TestUnifiedToolTasks:
    """Test unified tool for tasks resource."""

    @patch("src.calm.client.get_tasks")
    def test_list_tasks(self, mock_get_tasks, mock_ctx):
        """Test listing tasks via unified tool."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get_tasks.return_value = [
            {"ID": "3-12345", "Title": "Test Task 1"},
        ]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="tasks", operation="list", project_id="P001")

        assert len(result) == 1
        mock_get_tasks.assert_called_once_with("P001", "test-token-12345", "https://test.calm.cloud.sap", task_type=None)

    @patch("src.calm.client.get_tasks")
    def test_list_tasks_with_type_filter(self, mock_get_tasks, mock_ctx):
        """Test listing tasks with type filter."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get_tasks.return_value = []

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="tasks", operation="list", project_id="P001", task_type="User Story")

        mock_get_tasks.assert_called_once_with("P001", "test-token-12345", "https://test.calm.cloud.sap", task_type="User Story")

    def test_tasks_missing_project_id_raises_error(self, mock_ctx):
        """Test that missing project_id raises appropriate error."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_func = mcp._tool_manager._tools["calm_resource"]._func

        with pytest.raises(ValueError, match="project_id is required"):
            tool_func(mock_ctx, resource="tasks", operation="list")


class TestUnifiedToolRequirements:
    """Test unified tool for requirements resource."""

    @patch("src.calm.client.get_tasks")
    def test_list_requirements(self, mock_get_tasks, mock_ctx):
        """Test listing requirements via unified tool."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get_tasks.return_value = [
            {"ID": "3-99999", "Title": "Requirement 1", "Type": "Requirement"},
        ]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="requirements", operation="list", project_id="P001")

        assert len(result) == 1
        # Requirements should call get_tasks with task_type="Requirement"
        mock_get_tasks.assert_called_once_with("P001", "test-token-12345", "https://test.calm.cloud.sap", task_type="Requirement")


class TestUnifiedToolTeams:
    """Test unified tool for teams resource."""

    @patch("src.calm.client.get_teams")
    def test_list_all_teams(self, mock_get_teams, mock_ctx):
        """Test listing all teams."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get_teams.return_value = [
            {"ID": "T001", "Name": "Dev Team"},
        ]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="teams", operation="list")

        assert len(result) == 1
        mock_get_teams.assert_called_once()

    @patch("src.calm.client.get_project_teams")
    def test_list_project_teams(self, mock_get_project_teams, mock_ctx):
        """Test listing project-specific teams."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get_project_teams.return_value = [
            {"ID": "T001", "Name": "Project Team"},
        ]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="teams", operation="list", project_id="P001")

        assert len(result) == 1
        mock_get_project_teams.assert_called_once_with("P001", "test-token-12345", "https://test.calm.cloud.sap")


class TestUnifiedToolProcesses:
    """Test unified tool for processes resource."""

    @patch("src.calm.client.get_solution_processes")
    @patch("src.calm.client.get_business_processes")
    def test_list_all_processes_combined(self, mock_business, mock_solution, mock_ctx):
        """Test listing combined business + solution processes."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_business.return_value = [{"ID": "BP1", "Name": "Business Process 1"}]
        mock_solution.return_value = [{"ID": "SP1", "Name": "Solution Process 1"}]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="processes", operation="list")

        # Should combine both types
        assert len(result) == 2
        assert result[0]["ID"] == "BP1"
        assert result[1]["ID"] == "SP1"

    @patch("src.calm.client.get_business_processes")
    def test_list_business_processes_only(self, mock_business, mock_ctx):
        """Test listing only business processes."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_business.return_value = [{"ID": "BP1"}]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="business_processes", operation="list")

        assert len(result) == 1

    @patch("src.calm.client.get_solution_processes")
    def test_list_solution_processes_only(self, mock_solution, mock_ctx):
        """Test listing only solution processes."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_solution.return_value = [{"ID": "SP1"}]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="solution_processes", operation="list")

        assert len(result) == 1


class TestUnifiedToolOtherResources:
    """Test unified tool for other resource types."""

    @patch("src.calm.client.get_timeboxes")
    def test_list_timeboxes(self, mock_get, mock_ctx):
        """Test listing timeboxes."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get.return_value = [{"ID": "TB1"}]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="timeboxes", operation="list", project_id="P001")

        assert len(result) == 1

    @patch("src.calm.client.get_scopes")
    def test_list_scopes(self, mock_get, mock_ctx):
        """Test listing scopes."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get.return_value = [{"ID": "S1"}]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="scopes", operation="list")

        assert len(result) == 1

    @patch("src.calm.client.get_test_cases")
    def test_list_test_cases(self, mock_get, mock_ctx):
        """Test listing test cases."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get.return_value = [{"ID": "TC1"}]

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="test_cases", operation="list")

        assert len(result) == 1

    @patch("src.calm.client.get_project_customization")
    def test_get_customization(self, mock_get, mock_ctx):
        """Test getting project customization."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        mock_get.return_value = {"projectId": "P001"}

        tool_func = mcp._tool_manager._tools["calm_resource"]._func
        result = tool_func(mock_ctx, resource="customization", operation="get", project_id="P001")

        assert result["projectId"] == "P001"


class TestErrorHandling:
    """Test error handling in unified tool."""

    def test_invalid_resource_type(self, mock_ctx):
        """Test that invalid resource type raises clear error."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_func = mcp._tool_manager._tools["calm_resource"]._func

        with pytest.raises(ValueError, match="Unknown resource type"):
            tool_func(mock_ctx, resource="invalid_resource", operation="list")

    def test_unsupported_operation_in_phase1(self, mock_ctx):
        """Test that write operations raise appropriate error in Phase 1."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_func = mcp._tool_manager._tools["calm_resource"]._func

        with pytest.raises(ValueError, match="not supported.*Phase 1"):
            tool_func(mock_ctx, resource="projects", operation="create")

    def test_customization_list_operation_error(self, mock_ctx):
        """Test that customization with list operation gives helpful error."""
        from src.calm.tools.unified import register
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_func = mcp._tool_manager._tools["calm_resource"]._func

        with pytest.raises(ValueError, match="Use operation='get' for customization"):
            tool_func(mock_ctx, resource="customization", operation="list", project_id="P001")


class TestBackwardsCompatibility:
    """Test that legacy tools are still registered and functional."""

    def test_legacy_tools_still_registered(self):
        """Verify that all legacy tools are still registered alongside unified tool."""
        from server import mcp

        # Check that both unified and legacy tools exist
        tools = list(mcp._tool_manager._tools.keys())

        # Unified tool should exist
        assert "calm_resource" in tools

        # Legacy tools should still exist
        legacy_tools = [
            "get_calm_projects",
            "get_calm_tasks",
            "get_calm_requirements",
            "get_calm_teams",
            "get_calm_timeboxes",
            "get_calm_scopes",
            "get_calm_test_cases",
        ]

        for tool in legacy_tools:
            assert tool in tools, f"Legacy tool {tool} missing - backwards compatibility broken!"


if __name__ == "__main__":
    # Allow running directly with: python3 tests/test_consolidated_tools.py
    pytest.main([__file__, "-v", "--tb=short"])
