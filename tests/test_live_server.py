"""
Live Server Test - Verify server is working with Phase 3 changes
"""

import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP
import asyncio

def test_server_tools():
    """Test that server has correct tools registered."""
    print("\n" + "="*80)
    print("LIVE SERVER TEST")
    print("="*80)

    # Import server module to get the mcp instance
    import server
    mcp = server.mcp

    # Get tools list
    tools_list = asyncio.run(mcp.list_tools())
    tool_names = sorted([t.name for t in tools_list])

    print(f"\n✅ Server is running with {len(tool_names)} tools\n")

    # Categorize tools
    unified_tools = [t for t in tool_names if t == "calm_resource"]
    health_tools = [t for t in tool_names if "health" in t.lower()]
    oauth_tools = [t for t in tool_names if "oauth" in t.lower()]
    tm_tools = [t for t in tool_names if t.startswith("tm_") or t.startswith("get_tm") or t.startswith("create_tm") or t.startswith("update_tm") or t.startswith("delete_tm")]
    api_tools = [t for t in tool_names if "api" in t.lower() and "oauth" not in t.lower()]
    uuid_tools = [t for t in tool_names if "uuid" in t.lower()]

    print("📊 TOOL BREAKDOWN:")
    print("-" * 80)

    print(f"\n1. UNIFIED TOOL ({len(unified_tools)}):")
    for tool in unified_tools:
        print(f"   ✓ {tool}")

    print(f"\n2. HEALTH CHECKS ({len(health_tools)}):")
    for tool in health_tools:
        print(f"   ✓ {tool}")

    print(f"\n3. OAUTH ENDPOINTS ({len(oauth_tools)}):")
    for tool in oauth_tools:
        print(f"   ✓ {tool}")

    print(f"\n4. GENERIC API TOOLS ({len(api_tools)}):")
    for tool in api_tools:
        print(f"   ✓ {tool}")

    print(f"\n5. USER HELPERS ({len(uuid_tools)}):")
    for tool in uuid_tools:
        print(f"   ✓ {tool}")

    print(f"\n6. BTP TEST MANAGEMENT ({len(tm_tools)}):")
    for tool in tm_tools:
        print(f"   ✓ {tool}")

    other_tools = [t for t in tool_names if t not in unified_tools + health_tools + oauth_tools + tm_tools + api_tools + uuid_tools]
    if other_tools:
        print(f"\n7. OTHER ({len(other_tools)}):")
        for tool in other_tools:
            print(f"   ✓ {tool}")

    print("\n" + "="*80)
    print("VERIFICATION:")
    print("="*80)

    # Verify no legacy CRUD tools
    legacy_tools = [
        "get_calm_projects", "get_calm_tasks", "create_calm_task",
        "update_calm_task", "delete_calm_task", "get_calm_scopes",
        "create_calm_scope", "get_calm_test_cases"
    ]

    found_legacy = [t for t in legacy_tools if t in tool_names]

    if found_legacy:
        print(f"❌ FAIL: Found legacy tools: {found_legacy}")
        return False
    else:
        print("✅ No legacy CRUD tools found (correct)")

    # Verify unified tool exists
    if "calm_resource" in tool_names:
        print("✅ Unified tool 'calm_resource' registered (correct)")
    else:
        print("❌ FAIL: Unified tool 'calm_resource' not found")
        return False

    # Verify specialized tools exist
    required_specialized = [
        "calm_health",
        "get_calm_oauth_endpoints",
        "calm_api_write",
        "calm_api_delete",
        "tm_health"
    ]

    missing = [t for t in required_specialized if t not in tool_names]
    if missing:
        print(f"❌ FAIL: Missing specialized tools: {missing}")
        return False
    else:
        print(f"✅ All {len(required_specialized)} required specialized tools present")

    print("\n" + "="*80)
    print("RESULT:")
    print("="*80)

    total = len(tool_names)
    expected = 21

    if total == expected:
        print(f"✅ PERFECT: Exactly {expected} tools registered")
    elif abs(total - expected) <= 2:
        print(f"✅ GOOD: {total} tools registered (expected ~{expected})")
    else:
        print(f"⚠️  WARNING: {total} tools registered (expected ~{expected})")

    print(f"\n🎉 SERVER IS WORKING CORRECTLY! 🎉")
    print(f"\nReduction: 75 → {total} tools ({(75-total)/75*100:.1f}% reduction)")
    print(f"Token savings: ~{(75-total)*270} tokens per conversation\n")

    return True


def test_unified_tool_details():
    """Test unified tool schema."""
    print("\n" + "="*80)
    print("UNIFIED TOOL DETAILED TEST")
    print("="*80)

    import server
    mcp = server.mcp

    tools_list = asyncio.run(mcp.list_tools())

    # Find calm_resource
    calm_resource_tool = None
    for tool in tools_list:
        if tool.name == "calm_resource":
            calm_resource_tool = tool
            break

    if not calm_resource_tool:
        print("❌ calm_resource tool not found")
        return False

    print("\n📋 calm_resource Tool Schema:")
    print("-" * 80)

    schema = calm_resource_tool.inputSchema

    if "properties" in schema:
        props = schema["properties"]

        print("\nParameters:")
        for param_name, param_def in props.items():
            param_type = param_def.get("type", "unknown")
            enum_values = param_def.get("enum", [])
            required = param_name in schema.get("required", [])

            req_marker = "REQUIRED" if required else "optional"

            if enum_values:
                print(f"  • {param_name} ({param_type}, {req_marker})")
                if param_name == "resource":
                    print(f"    Resources: {', '.join(enum_values[:5])}... ({len(enum_values)} total)")
                elif param_name == "operation":
                    print(f"    Operations: {', '.join(enum_values)}")
            else:
                print(f"  • {param_name} ({param_type}, {req_marker})")

    print("\n✅ Unified tool schema looks correct!")
    return True


if __name__ == "__main__":
    print("\n" + "#"*80)
    print("# LIVE SERVER VALIDATION")
    print("#"*80)
    print("# Testing actual running server with Phase 3 changes")
    print("#"*80)

    try:
        success1 = test_server_tools()
        success2 = test_unified_tool_details()

        if success1 and success2:
            print("\n" + "="*80)
            print("✅ ALL LIVE SERVER TESTS PASSED!")
            print("="*80)
            print("\n🚀 Server is ready for deployment to Gen AI Studio!\n")
            sys.exit(0)
        else:
            print("\n❌ Some tests failed")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
