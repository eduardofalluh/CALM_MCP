"""Read-path tests for the unified consolidated ``calm_resource`` tool.

Validates that every read (list/get) resource type routes to the correct
``src.calm.client`` function with the right arguments, and that error handling
and the write guard behave correctly.

Write-path coverage lives in ``tests/test_unified_writes.py``.

Success criteria: 100% test pass rate.

Run with:  ./venv/bin/python -m pytest tests/test_consolidated_tools.py -q
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

TOKEN = "test-token-12345"
BASE_URL = "https://test.calm.cloud.sap"


class MockContext:
    """Plain context with no request_context — get_calm_headers falls through to env."""


@pytest.fixture(autouse=True)
def creds_env(monkeypatch):
    """Resolve credentials from env for every test (get_calm_headers reads env)."""
    monkeypatch.setenv("CALM_TOKEN", TOKEN)
    monkeypatch.setenv("CALM_BASE_URL", BASE_URL)
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("CALM_USER_EMAIL", raising=False)
    yield


@pytest.fixture
def mock_ctx():
    return MockContext()


def _tool_fn(name="calm_resource"):
    """Return the underlying tool function (FastMCP 4.x: get_tool is async, .fn is the callable)."""
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("test")
    register(mcp)
    return asyncio.run(mcp.get_tool(name)).fn


class TestUnifiedToolProjects:
    @patch("src.calm.client.get_projects")
    def test_list_projects(self, mock_get_projects, mock_ctx):
        mock_get_projects.return_value = [
            {"ID": "P001", "Name": "Test Project 1"},
            {"ID": "P002", "Name": "Test Project 2"},
        ]
        result = _tool_fn()(mock_ctx, resource="projects", operation="list")
        assert len(result) == 2
        assert result[0]["ID"] == "P001"
        mock_get_projects.assert_called_once_with(TOKEN, BASE_URL)


class TestUnifiedToolTasks:
    @patch("src.calm.client.get_tasks")
    def test_list_tasks(self, mock_get_tasks, mock_ctx):
        mock_get_tasks.return_value = [{"ID": "3-12345", "Title": "Test Task 1"}]
        result = _tool_fn()(mock_ctx, resource="tasks", operation="list", project_id="P001")
        assert len(result) == 1
        mock_get_tasks.assert_called_once_with("P001", TOKEN, BASE_URL, task_type=None)

    @patch("src.calm.client.get_tasks")
    def test_list_tasks_with_type_filter(self, mock_get_tasks, mock_ctx):
        mock_get_tasks.return_value = []
        _tool_fn()(mock_ctx, resource="tasks", operation="list", project_id="P001", task_type="User Story")
        mock_get_tasks.assert_called_once_with("P001", TOKEN, BASE_URL, task_type="User Story")

    def test_tasks_missing_project_id_raises_error(self, mock_ctx):
        with pytest.raises(ValueError, match="project_id is required"):
            _tool_fn()(mock_ctx, resource="tasks", operation="list")


class TestUnifiedToolRequirements:
    @patch("src.calm.client.get_tasks")
    def test_list_requirements(self, mock_get_tasks, mock_ctx):
        mock_get_tasks.return_value = [
            {"ID": "3-99999", "Title": "Requirement 1", "Type": "Requirement"},
        ]
        result = _tool_fn()(mock_ctx, resource="requirements", operation="list", project_id="P001")
        assert len(result) == 1
        mock_get_tasks.assert_called_once_with("P001", TOKEN, BASE_URL, task_type="Requirement")


class TestUnifiedToolTeams:
    @patch("src.calm.client.get_teams")
    def test_list_all_teams(self, mock_get_teams, mock_ctx):
        mock_get_teams.return_value = [{"ID": "T001", "Name": "Dev Team"}]
        result = _tool_fn()(mock_ctx, resource="teams", operation="list")
        assert len(result) == 1
        mock_get_teams.assert_called_once()

    @patch("src.calm.client.get_project_teams")
    def test_list_project_teams(self, mock_get_project_teams, mock_ctx):
        mock_get_project_teams.return_value = [{"ID": "T001", "Name": "Project Team"}]
        result = _tool_fn()(mock_ctx, resource="teams", operation="list", project_id="P001")
        assert len(result) == 1
        mock_get_project_teams.assert_called_once_with("P001", TOKEN, BASE_URL)


class TestUnifiedToolProcesses:
    @patch("src.calm.client.get_solution_processes")
    @patch("src.calm.client.get_business_processes")
    def test_list_all_processes_combined(self, mock_business, mock_solution, mock_ctx):
        mock_business.return_value = [{"ID": "BP1", "Name": "Business Process 1"}]
        mock_solution.return_value = [{"ID": "SP1", "Name": "Solution Process 1"}]
        result = _tool_fn()(mock_ctx, resource="processes", operation="list")
        assert len(result) == 2
        assert result[0]["ID"] == "BP1"
        assert result[1]["ID"] == "SP1"

    @patch("src.calm.client.get_business_processes")
    def test_list_business_processes_only(self, mock_business, mock_ctx):
        mock_business.return_value = [{"ID": "BP1"}]
        result = _tool_fn()(mock_ctx, resource="business_processes", operation="list")
        assert len(result) == 1

    @patch("src.calm.client.get_solution_processes")
    def test_list_solution_processes_only(self, mock_solution, mock_ctx):
        mock_solution.return_value = [{"ID": "SP1"}]
        result = _tool_fn()(mock_ctx, resource="solution_processes", operation="list")
        assert len(result) == 1


class TestUnifiedToolOtherResources:
    @patch("src.calm.client.get_timeboxes")
    def test_list_timeboxes(self, mock_get, mock_ctx):
        mock_get.return_value = [{"ID": "TB1"}]
        result = _tool_fn()(mock_ctx, resource="timeboxes", operation="list", project_id="P001")
        assert len(result) == 1

    @patch("src.calm.client.get_scopes")
    def test_list_scopes(self, mock_get, mock_ctx):
        mock_get.return_value = [{"ID": "S1"}]
        result = _tool_fn()(mock_ctx, resource="scopes", operation="list")
        assert len(result) == 1

    @patch("src.calm.client.get_test_cases")
    def test_list_test_cases(self, mock_get, mock_ctx):
        mock_get.return_value = [{"ID": "TC1"}]
        result = _tool_fn()(mock_ctx, resource="test_cases", operation="list")
        assert len(result) == 1

    @patch("src.calm.client.get_project_customization")
    def test_get_customization(self, mock_get, mock_ctx):
        mock_get.return_value = {"projectId": "P001"}
        result = _tool_fn()(mock_ctx, resource="customization", operation="get", project_id="P001")
        assert result["projectId"] == "P001"


class TestErrorHandling:
    def test_invalid_resource_type(self, mock_ctx):
        with pytest.raises(ValueError, match="Unknown resource type"):
            _tool_fn()(mock_ctx, resource="invalid_resource", operation="list")

    def test_write_guard_blocks_create_when_disabled(self, mock_ctx, monkeypatch):
        """Create is now supported, but must be refused when CALM_ENABLE_WRITES is off."""
        monkeypatch.setenv("CALM_ENABLE_WRITES", "")
        with pytest.raises(ValueError, match="Write operations are disabled"):
            _tool_fn()(mock_ctx, resource="projects", operation="create", data={"name": "X"})

    def test_customization_list_operation_error(self, mock_ctx):
        with pytest.raises(ValueError, match="Use operation='get' for customization"):
            _tool_fn()(mock_ctx, resource="customization", operation="list", project_id="P001")


class TestPhase3Architecture:
    """The server ships the consolidated surface: unified present, legacy CRUD removed."""

    def test_unified_registered_and_legacy_removed(self):
        from server import mcp

        tool_names = {t.name for t in asyncio.run(mcp.list_tools())}

        # Unified tool must be present.
        assert "calm_resource" in tool_names

        # Legacy per-resource CRUD tools were removed in Phase 3.
        removed_legacy = [
            "get_calm_projects",
            "get_calm_tasks",
            "create_calm_task",
            "get_calm_scopes",
            "create_calm_scope",
            "get_calm_test_cases",
        ]
        still_present = [t for t in removed_legacy if t in tool_names]
        assert not still_present, f"Legacy tools should have been removed: {still_present}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
