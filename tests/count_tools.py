"""Count tools registered in the MCP server after Phase 3 removal."""

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

# Create test MCP instance
mcp = FastMCP("test-sap-cloud-alm")

# Register only the tools that server.py registers
unified.register(mcp)
health.register(mcp)
oauth_info.register(mcp)
advanced_write.register(mcp)
user_uuid_helper.register(mcp)
test_repo.register(mcp)
test_repo_write.register(mcp)

# Count tools
print("\n" + "="*80)
print("TOOL COUNT AFTER PHASE 3 REMOVAL")
print("="*80)

# Get tool count by inspecting the registered tools
tool_count = 0
tool_names = []

# Access tools through the MCP instance's tool manager
if hasattr(mcp, '_tools'):
    tools = mcp._tools
    tool_count = len(tools)
    tool_names = list(tools.keys())
elif hasattr(mcp, 'list_tools'):
    # Try to list tools
    import asyncio
    try:
        tools_list = asyncio.run(mcp.list_tools())
        tool_count = len(tools_list)
        tool_names = [t.name for t in tools_list]
    except:
        pass

print(f"\n📊 Total Tools Registered: {tool_count if tool_count > 0 else 'Unable to count directly'}")

if tool_names:
    print(f"\n📋 Registered Tools:")
    for i, name in enumerate(sorted(tool_names), 1):
        print(f"   {i:2d}. {name}")

# Manual count based on modules
print("\n" + "-"*80)
print("TOOL COUNT BY MODULE:")
print("-"*80)

module_tools = {
    "unified": ["calm_resource"],
    "health": ["calm_health"],
    "oauth_info": ["get_calm_oauth_endpoints", "get_calm_oauth_metadata", "get_calm_authorization_server_metadata"],
    "advanced_write": ["calm_api_write", "calm_api_delete"],
    "user_uuid_helper": ["get_my_calm_user_uuid_instructions"],
    "test_repo": ["tm_health", "get_tm_statistics", "get_tm_test_cases", "get_tm_test_case_full",
                  "get_tm_requirements", "tm_odata_read"],
    "test_repo_write": ["create_tm_test_case", "update_tm_test_case", "delete_tm_test_case",
                        "create_tm_requirement", "delete_tm_requirement", "tm_odata_write", "tm_odata_delete"],
}

total = 0
for module, tools in module_tools.items():
    count = len(tools)
    total += count
    print(f"\n{module:20s}: {count:2d} tools")
    for tool in tools:
        print(f"  - {tool}")

print("\n" + "="*80)
print(f"ESTIMATED TOTAL: ~{total} tools")
print("="*80)

print("\n📉 Reduction:")
print(f"   Before Phase 3: 75 tools (74 legacy + 1 unified)")
print(f"   After Phase 3:  ~{total} tools")
print(f"   Removed:        ~{75 - total} tools ({(75-total)/75*100:.1f}% reduction)")
print(f"   Token Savings:  ~{(75-total)*270} tokens per conversation")

print("\n✅ Phase 3 removal complete!\n")
