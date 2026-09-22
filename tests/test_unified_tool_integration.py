#!/usr/bin/env python3
"""Quick integration test for the unified calm_resource tool.

This test verifies that:
1. The unified tool can be called directly
2. It routes correctly to client functions
3. It returns expected data formats
4. Error handling works as expected

Run with: python3 tests/test_unified_tool_integration.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_unified_tool_projects():
    """Test that calm_resource can list projects."""
    from src.calm.tools.unified import register
    from fastmcp import FastMCP

    print("Test 1: List projects via unified tool...")

    # Create MCP instance and register unified tool
    mcp = FastMCP("test")
    register(mcp)

    # Create mock context
    ctx = MagicMock()
    ctx.meta = {
        "CALM_TOKEN": "test-token",
        "CALM_BASE_URL": "https://test.calm.cloud.sap"
    }

    # Mock the client function
    with patch("src.calm.client.get_projects") as mock_get_projects:
        mock_get_projects.return_value = [
            {"ID": "P001", "Name": "Test Project"}
        ]

        # Get the tool function
        tool_func = list(mcp._tools.values())[0]._func

        # Call it
        result = tool_func(ctx, resource="projects", operation="list")

        # Verify
        assert result == [{"ID": "P001", "Name": "Test Project"}]
        assert mock_get_projects.called
        print("  ✓ Projects list works")


def test_unified_tool_tasks():
    """Test that calm_resource can list tasks."""
    from src.calm.tools.unified import register
    from fastmcp import FastMCP

    print("Test 2: List tasks via unified tool...")

    mcp = FastMCP("test")
    register(mcp)

    ctx = MagicMock()
    ctx.meta = {
        "CALM_TOKEN": "test-token",
        "CALM_BASE_URL": "https://test.calm.cloud.sap"
    }

    with patch("src.calm.client.get_tasks") as mock_get_tasks:
        mock_get_tasks.return_value = [
            {"ID": "T001", "Title": "Test Task"}
        ]

        tool_func = list(mcp._tools.values())[0]._func
        result = tool_func(ctx, resource="tasks", operation="list", project_id="P001")

        assert result == [{"ID": "T001", "Title": "Test Task"}]
        mock_get_tasks.assert_called_once_with("P001", "test-token", "https://test.calm.cloud.sap", task_type=None)
        print("  ✓ Tasks list works")


def test_unified_tool_error_handling():
    """Test that calm_resource handles errors correctly."""
    from src.calm.tools.unified import register
    from fastmcp import FastMCP

    print("Test 3: Error handling...")

    mcp = FastMCP("test")
    register(mcp)

    ctx = MagicMock()
    ctx.meta = {
        "CALM_TOKEN": "test-token",
        "CALM_BASE_URL": "https://test.calm.cloud.sap"
    }

    tool_func = list(mcp._tools.values())[0]._func

    # Test missing required parameter
    try:
        tool_func(ctx, resource="tasks", operation="list")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "project_id is required" in str(e)
        print("  ✓ Missing parameter error works")

    # Test invalid resource
    try:
        tool_func(ctx, resource="invalid_resource", operation="list")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown resource type" in str(e)
        print("  ✓ Invalid resource error works")

    # Test unsupported operation in Phase 1
    try:
        tool_func(ctx, resource="projects", operation="create")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "not supported" in str(e) and "Phase 1" in str(e)
        print("  ✓ Phase 1 restriction works")


def test_unified_tool_teams():
    """Test that calm_resource handles teams correctly (with optional project_id)."""
    from src.calm.tools.unified import register
    from fastmcp import FastMCP

    print("Test 4: Teams with optional project filter...")

    mcp = FastMCP("test")
    register(mcp)

    ctx = MagicMock()
    ctx.meta = {
        "CALM_TOKEN": "test-token",
        "CALM_BASE_URL": "https://test.calm.cloud.sap"
    }

    tool_func = list(mcp._tools.values())[0]._func

    # Test without project_id (all teams)
    with patch("src.calm.client.get_teams") as mock_get_teams:
        mock_get_teams.return_value = [{"ID": "T001", "Name": "Team 1"}]
        result = tool_func(ctx, resource="teams", operation="list")
        assert mock_get_teams.called
        print("  ✓ All teams works")

    # Test with project_id (project teams)
    with patch("src.calm.client.get_project_teams") as mock_get_project_teams:
        mock_get_project_teams.return_value = [{"ID": "T002", "Name": "Project Team"}]
        result = tool_func(ctx, resource="teams", operation="list", project_id="P001")
        assert mock_get_project_teams.called
        print("  ✓ Project teams works")


def test_unified_tool_processes():
    """Test that calm_resource handles combined processes correctly."""
    from src.calm.tools.unified import register
    from fastmcp import FastMCP

    print("Test 5: Combined processes...")

    mcp = FastMCP("test")
    register(mcp)

    ctx = MagicMock()
    ctx.meta = {
        "CALM_TOKEN": "test-token",
        "CALM_BASE_URL": "https://test.calm.cloud.sap"
    }

    tool_func = list(mcp._tools.values())[0]._func

    with patch("src.calm.client.get_business_processes") as mock_business:
        with patch("src.calm.client.get_solution_processes") as mock_solution:
            mock_business.return_value = [{"ID": "BP1", "Name": "Business"}]
            mock_solution.return_value = [{"ID": "SP1", "Name": "Solution"}]

            result = tool_func(ctx, resource="processes", operation="list")

            assert len(result) == 2
            assert result[0]["ID"] == "BP1"
            assert result[1]["ID"] == "SP1"
            print("  ✓ Combined processes works")


def main():
    """Run all tests."""
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
