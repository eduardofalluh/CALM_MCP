#!/usr/bin/env python3
"""Quick integration smoke test for the unified calm_resource tool.

Verifies that:
1. The unified tool can be called directly.
2. It routes reads to the correct client functions.
3. Error handling works as expected.
4. The write guard blocks writes when CALM_ENABLE_WRITES is off.

Full read coverage is in tests/test_consolidated_tools.py and write coverage is
in tests/test_unified_writes.py; this file is a fast standalone sanity check.

Run with: ./venv/bin/python tests/test_unified_tool_integration.py
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

TOKEN = "test-token"
BASE_URL = "https://test.calm.cloud.sap"


class Ctx:
    """Plain context — get_calm_headers falls through to env credentials."""


def _tool_fn(name="calm_resource"):
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("test")
    register(mcp)
    return asyncio.run(mcp.get_tool(name)).fn


def _set_creds():
    os.environ["CALM_TOKEN"] = TOKEN
    os.environ["CALM_BASE_URL"] = BASE_URL
    os.environ.pop("CALM_CLIENT_ID", None)
    os.environ.pop("CALM_CLIENT_SECRET", None)


def test_unified_tool_projects():
    print("Test 1: List projects via unified tool...")
    _set_creds()
    with patch("src.calm.client.get_projects") as mock_get_projects:
        mock_get_projects.return_value = [{"ID": "P001", "Name": "Test Project"}]
        result = _tool_fn()(Ctx(), resource="projects", operation="list")
        assert result == [{"ID": "P001", "Name": "Test Project"}]
        assert mock_get_projects.called
        print("  ✓ Projects list works")


def test_unified_tool_tasks():
    print("Test 2: List tasks via unified tool...")
    _set_creds()
    with patch("src.calm.client.get_tasks") as mock_get_tasks:
        mock_get_tasks.return_value = [{"ID": "T001", "Title": "Test Task"}]
        result = _tool_fn()(Ctx(), resource="tasks", operation="list", project_id="P001")
        assert result == [{"ID": "T001", "Title": "Test Task"}]
        mock_get_tasks.assert_called_once_with("P001", TOKEN, BASE_URL, task_type=None)
        print("  ✓ Tasks list works")


def test_unified_tool_error_handling():
    print("Test 3: Error handling...")
    _set_creds()

    # Missing required parameter
    try:
        _tool_fn()(Ctx(), resource="tasks", operation="list")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "project_id is required" in str(e)
        print("  ✓ Missing parameter error works")

    # Invalid resource
    try:
        _tool_fn()(Ctx(), resource="invalid_resource", operation="list")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown resource type" in str(e)
        print("  ✓ Invalid resource error works")

    # Write guard: create is supported but blocked when writes are disabled
    os.environ["CALM_ENABLE_WRITES"] = ""
    try:
        _tool_fn()(Ctx(), resource="projects", operation="create", data={"name": "X"})
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Write operations are disabled" in str(e)
        print("  ✓ Write guard blocks create when disabled")


def test_unified_tool_teams():
    print("Test 4: Teams with optional project filter...")
    _set_creds()
    with patch("src.calm.client.get_teams") as mock_get_teams:
        mock_get_teams.return_value = [{"ID": "T001", "Name": "Team 1"}]
        _tool_fn()(Ctx(), resource="teams", operation="list")
        assert mock_get_teams.called
        print("  ✓ All teams works")

    with patch("src.calm.client.get_project_teams") as mock_get_project_teams:
        mock_get_project_teams.return_value = [{"ID": "T002", "Name": "Project Team"}]
        _tool_fn()(Ctx(), resource="teams", operation="list", project_id="P001")
        assert mock_get_project_teams.called
        print("  ✓ Project teams works")


def test_unified_tool_processes():
    print("Test 5: Combined processes...")
    _set_creds()
    with patch("src.calm.client.get_business_processes") as mock_business:
        with patch("src.calm.client.get_solution_processes") as mock_solution:
            mock_business.return_value = [{"ID": "BP1", "Name": "Business"}]
            mock_solution.return_value = [{"ID": "SP1", "Name": "Solution"}]
            result = _tool_fn()(Ctx(), resource="processes", operation="list")
            assert len(result) == 2
            assert result[0]["ID"] == "BP1"
            assert result[1]["ID"] == "SP1"
            print("  ✓ Combined processes works")


def main():
    print("=" * 70)
    print("Unified Tool Integration Tests")
    print("=" * 70)
    print()

    try:
        test_unified_tool_projects()
        test_unified_tool_tasks()
        test_unified_tool_error_handling()
        test_unified_tool_teams()
        test_unified_tool_processes()

        print()
        print("=" * 70)
        print("✅ All unified tool integration tests PASSED")
        print("=" * 70)
        return 0

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
