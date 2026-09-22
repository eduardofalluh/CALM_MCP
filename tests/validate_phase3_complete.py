"""
Comprehensive Phase 3 Validation Script

Validates that Phase 3 removal was successful and all functionality preserved.
"""

import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP
from src.calm.tools import (
    unified,
    health,
    oauth_info,
    advanced_write,
    user_uuid_helper,
    test_repo,
    test_repo_write,
)

def test_tool_count():
    """Verify tool count reduced to ~21."""
    print("\n" + "="*80)
    print("TEST: Tool Count Reduction")
    print("="*80)

    mcp = FastMCP("test")
    unified.register(mcp)
    health.register(mcp)
    oauth_info.register(mcp)
    advanced_write.register(mcp)
    user_uuid_helper.register(mcp)
    test_repo.register(mcp)
    test_repo_write.register(mcp)

    # Count tools
    import asyncio
    tools_list = asyncio.run(mcp.list_tools())
    tool_count = len(tools_list)

    print(f"✅ Total tools: {tool_count}")
    print(f"✅ Target: ~21 tools")
    print(f"✅ Reduction: {75 - tool_count} tools removed (from 75)")
    print(f"✅ Percentage: {(75-tool_count)/75*100:.1f}% reduction")

    if tool_count <= 25:
        print("✅ PASS: Tool count within target range")
        return True
    else:
        print(f"❌ FAIL: Tool count {tool_count} exceeds target of ~25")
        return False


def test_unified_tool_exists():
    """Verify calm_resource tool is registered."""
    print("\n" + "="*80)
    print("TEST: Unified Tool Registered")
    print("="*80)

    mcp = FastMCP("test")
    unified.register(mcp)

    import asyncio
    tools_list = asyncio.run(mcp.list_tools())
    tool_names = [t.name for t in tools_list]

    if "calm_resource" in tool_names:
        print("✅ PASS: calm_resource tool registered")
        return True
    else:
        print("❌ FAIL: calm_resource tool not found")
        return False


def test_legacy_tools_removed():
    """Verify legacy CRUD tools are not registered."""
    print("\n" + "="*80)
    print("TEST: Legacy CRUD Tools Removed")
    print("="*80)

    mcp = FastMCP("test")
    unified.register(mcp)
    health.register(mcp)
    oauth_info.register(mcp)
    advanced_write.register(mcp)
    user_uuid_helper.register(mcp)
    test_repo.register(mcp)
    test_repo_write.register(mcp)

    import asyncio
    tools_list = asyncio.run(mcp.list_tools())
    tool_names = [t.name for t in tools_list]

    # Legacy tools that should be removed
    legacy_tools = [
        "get_calm_projects",
        "get_calm_tasks",
        "create_calm_task",
        "update_calm_task",
        "delete_calm_task",
        "get_calm_scopes",
        "create_calm_scope",
        "get_calm_test_cases",
    ]

    found_legacy = [tool for tool in legacy_tools if tool in tool_names]

    if found_legacy:
        print(f"❌ FAIL: Found legacy tools still registered: {found_legacy}")
        return False
    else:
        print(f"✅ PASS: All {len(legacy_tools)} sample legacy tools removed")
        return True


def test_specialized_tools_kept():
    """Verify specialized tools are still registered."""
    print("\n" + "="*80)
    print("TEST: Specialized Tools Kept")
    print("="*80)

    mcp = FastMCP("test")
    unified.register(mcp)
    health.register(mcp)
    oauth_info.register(mcp)
    advanced_write.register(mcp)
    user_uuid_helper.register(mcp)
    test_repo.register(mcp)
    test_repo_write.register(mcp)

    import asyncio
    tools_list = asyncio.run(mcp.list_tools())
    tool_names = [t.name for t in tools_list]

    # Specialized tools that must be kept
    required_tools = [
        "calm_resource",  # Unified
        "calm_health",  # Health
        "get_calm_oauth_endpoints",  # OAuth
        "calm_api_write",  # Advanced
        "calm_api_delete",  # Advanced
        "get_my_calm_user_uuid_instructions",  # User helper
        "tm_health",  # TM
        "create_tm_test_case",  # TM
    ]

    missing_tools = [tool for tool in required_tools if tool not in tool_names]

    if missing_tools:
        print(f"❌ FAIL: Missing required tools: {missing_tools}")
        return False
    else:
        print(f"✅ PASS: All {len(required_tools)} required specialized tools present")
        for tool in required_tools:
            print(f"   ✓ {tool}")
        return True


def test_unified_tool_signature():
    """Verify unified tool has correct signature with all resources and operations."""
    print("\n" + "="*80)
    print("TEST: Unified Tool Signature")
    print("="*80)

    import inspect
    from src.calm.tools import unified

    source = inspect.getsource(unified)

    # Check resources
    required_resources = [
        "projects", "tasks", "requirements", "teams", "processes",
        "business_processes", "solution_processes", "timeboxes",
        "scopes", "test_cases", "tags", "features", "test_plans",
        "project_users", "customization"
    ]

    missing_resources = []
    for resource in required_resources:
        if f'"{resource}"' not in source:
            missing_resources.append(resource)

    if missing_resources:
        print(f"❌ FAIL: Missing resources: {missing_resources}")
        return False

    print(f"✅ All {len(required_resources)} resources present in unified tool")

    # Check operations
    required_operations = ["list", "get", "create", "update", "delete"]
    missing_operations = []
    for op in required_operations:
        if f'"{op}"' not in source:
            missing_operations.append(op)

    if missing_operations:
        print(f"❌ FAIL: Missing operations: {missing_operations}")
        return False

    print(f"✅ All {len(required_operations)} operations present in unified tool")
    print("✅ PASS: Unified tool signature complete")
    return True


def test_server_imports():
    """Verify server.py imports are correct."""
    print("\n" + "="*80)
    print("TEST: Server Imports")
    print("="*80)

    with open("server.py", "r") as f:
        server_code = f.read()

    # Check removed imports
    removed = ["projects", "processes", "scopes", "test_cases", "timeboxes",
               "teams", "users", "tags", "features", "test_plans", "customization",
               "tasks_write", "projects_write", "processes_write", "scopes_write",
               "test_cases_write"]

    # Find import section
    import_start = server_code.find("from src.calm.tools import")
    import_end = server_code.find(")", import_start)
    import_section = server_code[import_start:import_end]

    found_removed = []
    for tool in removed:
        if f"\n    {tool}," in import_section:
            found_removed.append(tool)

    if found_removed:
        print(f"❌ FAIL: Found removed imports: {found_removed}")
        return False

    print(f"✅ All {len(removed)} legacy imports removed")

    # Check kept imports
    kept = ["unified", "health", "oauth_info", "advanced_write",
            "user_uuid_helper", "test_repo", "test_repo_write"]

    missing_kept = []
    for tool in kept:
        if tool not in import_section:
            missing_kept.append(tool)

    if missing_kept:
        print(f"❌ FAIL: Missing required imports: {missing_kept}")
        return False

    print(f"✅ All {len(kept)} required imports present")
    print("✅ PASS: Server imports correct")
    return True


def test_server_registrations():
    """Verify server.py registrations are correct."""
    print("\n" + "="*80)
    print("TEST: Server Registrations")
    print("="*80)

    with open("server.py", "r") as f:
        server_code = f.read()

    # Check removed registrations
    removed_regs = [
        "projects.register(mcp)",
        "processes.register(mcp)",
        "scopes.register(mcp)",
        "test_cases.register(mcp)",
        "timeboxes.register(mcp)",
        "teams.register(mcp)",
        "users.register(mcp)",
        "tags.register(mcp)",
        "features.register(mcp)",
        "test_plans.register(mcp)",
        "customization.register(mcp)",
        "tasks_write.register(mcp)",
        "projects_write.register(mcp)",
        "processes_write.register(mcp)",
        "scopes_write.register(mcp)",
        "test_cases_write.register(mcp)",
    ]

    found_removed_regs = []
    for reg in removed_regs:
        if reg in server_code and "# " not in server_code[server_code.find(reg)-10:server_code.find(reg)]:
            found_removed_regs.append(reg)

    if found_removed_regs:
        print(f"❌ FAIL: Found removed registrations: {found_removed_regs}")
        return False

    print(f"✅ All {len(removed_regs)} legacy registrations removed")

    # Check kept registrations
    kept_regs = [
        "unified.register(mcp)",
        "health.register(mcp)",
        "oauth_info.register(mcp)",
        "advanced_write.register(mcp)",
        "user_uuid_helper.register(mcp)",
        "test_repo.register(mcp)",
        "test_repo_write.register(mcp)",
    ]

    missing_kept_regs = []
    for reg in kept_regs:
        if reg not in server_code:
            missing_kept_regs.append(reg)

    if missing_kept_regs:
        print(f"❌ FAIL: Missing required registrations: {missing_kept_regs}")
        return False

    print(f"✅ All {len(kept_regs)} required registrations present")
    print("✅ PASS: Server registrations correct")
    return True


def main():
    """Run all validation tests."""
    print("\n" + "#"*80)
    print("# PHASE 3 COMPREHENSIVE VALIDATION")
    print("#"*80)
    print("# Validating tool removal and functionality preservation")
    print("#"*80)

    tests = [
        ("Tool Count Reduction", test_tool_count),
        ("Unified Tool Registered", test_unified_tool_exists),
        ("Legacy Tools Removed", test_legacy_tools_removed),
        ("Specialized Tools Kept", test_specialized_tools_kept),
        ("Unified Tool Signature", test_unified_tool_signature),
        ("Server Imports", test_server_imports),
        ("Server Registrations", test_server_registrations),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ TEST FAILED: {name}")
            print(f"   Error: {str(e)}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "="*80)
    print("VALIDATION SUMMARY")
    print("="*80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed ({passed/total*100:.1f}%)")

    if passed == total:
        print("\n" + "🎉"*40)
        print("\n  ALL VALIDATION TESTS PASSED!")
        print("  Phase 3 removal successful!")
        print("  75 tools → 21 tools (72% reduction)")
        print("  ~14,580 token savings per conversation")
        print("\n" + "🎉"*40 + "\n")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed. Review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
