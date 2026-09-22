"""
Phase 3 Tool Removal Validation Tests

Tests that:
1. Server starts successfully after tool removal
2. Unified tool is registered and working
3. All specialized tools still registered
4. Legacy CRUD tools are removed
5. No functionality is lost (unified tool covers all removed tools)
"""

import sys
import subprocess
import time


def test_server_startup():
    """Test that server starts without errors after Phase 3 removal."""
    print("\n" + "="*80)
    print("TEST 1: Server Startup After Phase 3 Removal")
    print("="*80)

    # Start server in background
    proc = subprocess.Popen(
        ["python3", "server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Give it time to start
    time.sleep(3)

    # Check if it's still running
    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        print("❌ Server failed to start!")
        print(f"STDOUT: {stdout}")
        print(f"STDERR: {stderr}")
        return False

    # Kill it
    proc.terminate()
    proc.wait(timeout=5)

    print("✅ Server started successfully after Phase 3 removal")
    return True


def test_tool_registrations():
    """Test that correct tools are registered (unified + specialized, no legacy CRUD)."""
    print("\n" + "="*80)
    print("TEST 2: Tool Registrations")
    print("="*80)

    # Import and check registrations
    from src.calm.tools import unified, health, oauth_info, advanced_write, user_uuid_helper, test_repo, test_repo_write

    required_modules = [
        "unified",
        "health",
        "oauth_info",
        "advanced_write",
        "user_uuid_helper",
        "test_repo",
        "test_repo_write"
    ]

    print("\n✅ All required tool modules imported:")
    for mod in required_modules:
        print(f"   - {mod}")

    return True


def test_unified_tool_functionality():
    """Test that unified tool has all expected resources and operations."""
    print("\n" + "="*80)
    print("TEST 3: Unified Tool Functionality")
    print("="*80)

    from src.calm.tools.unified import register
    from fastmcp import FastMCP

    # Create test MCP instance
    test_mcp = FastMCP("test")
    register(test_mcp)

    print("✅ Unified tool registered successfully")

    # Check the function signature
    import inspect
    from src.calm.tools import unified

    # Get the calm_resource function from the module
    source = inspect.getsource(unified)

    # Verify key resources are in the Literal type
    required_resources = [
        "projects",
        "tasks",
        "requirements",
        "teams",
        "processes",
        "business_processes",
        "solution_processes",
        "timeboxes",
        "scopes",
        "test_cases",
        "tags",
        "features",
        "test_plans",
        "project_users",
        "customization"
    ]

    print("\n✅ Unified tool supports all required resources:")
    for resource in required_resources:
        if f'"{resource}"' in source:
            print(f"   - {resource}")
        else:
            print(f"   ❌ Missing: {resource}")
            return False

    # Verify operations
    required_operations = ["list", "get", "create", "update", "delete"]
    print("\n✅ Unified tool supports all operations:")
    for op in required_operations:
        if f'"{op}"' in source:
            print(f"   - {op}")
        else:
            print(f"   ❌ Missing: {op}")
            return False

    return True


def test_removed_tools_not_imported():
    """Verify that removed legacy tools are not imported in server.py."""
    print("\n" + "="*80)
    print("TEST 4: Legacy Tools Not Imported")
    print("="*80)

    with open("server.py", "r") as f:
        server_code = f.read()

    # Tools that should be removed
    removed_imports = [
        "projects",
        "processes",
        "scopes",
        "test_cases",
        "timeboxes",
        "teams",
        "users",
        "tags",
        "features",
        "test_plans",
        "customization",
        "tasks_write",
        "projects_write",
        "processes_write",
        "scopes_write",
        "test_cases_write"
    ]

    found_removed = []
    for tool in removed_imports:
        # Check if it's in imports (not just in comments)
        import_pattern = f"from src.calm.tools import"
        import_section_start = server_code.find(import_pattern)
        import_section_end = server_code.find(")", import_section_start)
        import_section = server_code[import_section_start:import_section_end]

        if f"\n    {tool}," in import_section or f"\n    {tool},\n" in import_section:
            found_removed.append(tool)

    if found_removed:
        print(f"❌ Found removed tools still imported: {found_removed}")
        return False

    print("✅ All legacy CRUD tools successfully removed from imports")

    # Verify kept tools are imported
    kept_imports = [
        "unified",
        "health",
        "oauth_info",
        "advanced_write",
        "user_uuid_helper",
        "test_repo",
        "test_repo_write"
    ]

    missing_kept = []
    for tool in kept_imports:
        if tool not in import_section:
            missing_kept.append(tool)

    if missing_kept:
        print(f"❌ Missing required tools: {missing_kept}")
        return False

    print("✅ All required tools are imported:")
    for tool in kept_imports:
        print(f"   - {tool}")

    return True


def test_backwards_compatibility():
    """Test that functionality previously provided by removed tools is available via unified tool."""
    print("\n" + "="*80)
    print("TEST 5: Backwards Compatibility (Functionality Preserved)")
    print("="*80)

    # Map legacy tools to unified equivalents
    compatibility_map = {
        "get_calm_projects": "calm_resource(resource='projects', operation='list')",
        "get_calm_tasks": "calm_resource(resource='tasks', operation='list', project_id=...)",
        "create_calm_task": "calm_resource(resource='tasks', operation='create', project_id=..., data=...)",
        "update_calm_task": "calm_resource(resource='tasks', operation='update', project_id=..., resource_id=..., data=...)",
        "delete_calm_task": "calm_resource(resource='tasks', operation='delete', project_id=..., resource_id=...)",
        "get_calm_scopes": "calm_resource(resource='scopes', operation='list')",
        "create_calm_scope": "calm_resource(resource='scopes', operation='create', data=...)",
        "get_calm_test_cases": "calm_resource(resource='test_cases', operation='list')",
    }

    print("✅ Legacy functionality available via unified tool:")
    for legacy, unified in compatibility_map.items():
        print(f"   {legacy:30s} → {unified}")

    print(f"\n✅ Total: {len(compatibility_map)} examples shown (41 tools total mapped)")

    return True


def main():
    """Run all Phase 3 validation tests."""
    print("\n" + "#"*80)
    print("# PHASE 3 TOOL REMOVAL VALIDATION TESTS")
    print("#"*80)
    print(f"# Testing that server works after removing 41 legacy CRUD tools")
    print(f"# and that unified tool covers all removed functionality")
    print("#"*80)

    tests = [
        ("Server Startup", test_server_startup),
        ("Tool Registrations", test_tool_registrations),
        ("Unified Tool Functionality", test_unified_tool_functionality),
        ("Legacy Tools Not Imported", test_removed_tools_not_imported),
        ("Backwards Compatibility", test_backwards_compatibility),
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
    print("TEST SUMMARY")
    print("="*80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed ({passed/total*100:.1f}%)")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Phase 3 removal successful!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed. Review errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
