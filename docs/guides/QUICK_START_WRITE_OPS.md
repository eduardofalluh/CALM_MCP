# Quick Start: Enabling Write Operations

## TL;DR

Your OAuth scopes are **already configured correctly** ✅

To enable write operations, simply:

```bash
# Add this line to your .env file:
CALM_ENABLE_WRITES=true

# Then restart the MCP server
```

That's it! No code changes, no scope changes needed.

---

## Complete Example (.env file)

```bash
# Your existing credentials
IDENTITY_ZONE=illumiti-corp-cloudalm
REGION_ZONE=eu10
CALM_CLIENT_ID=sb-cloud-alm-api!b175722|sapcloudalm!b16907
CALM_CLIENT_SECRET=your-secret-here

# Add this line to enable writes:
CALM_ENABLE_WRITES=true
```

---

## Verification

After restarting the server, call the `calm_health` tool:

```json
{
  "writes_enabled": true  // ✅ Should be true
}
```

---

## Safe Testing

```bash
# 1. Create a test task with clear label
create_calm_task(
  project_id: "your-project-id",
  title: "MCP Test - DELETE ME - 2026-07-28",
  task_type: "Project Task"
)
# Returns: { "ID": "abc123", ... }

# 2. Immediately delete it
delete_calm_task(task_id: "abc123")

# 3. Verify it's gone
get_calm_tasks(project_id: "your-project-id")
```

---

## What You Get

- **15 Create tools** (projects, tasks, processes, scopes, test cases)
- **13 Update tools** (partial updates with automatic ETag handling)
- **10 Delete tools** (including force-delete for test cases)
- **2 Generic tools** (`calm_api_write`, `calm_api_delete` for any endpoint)

**Total: 38 write operations + 8 read-only tools = 46 tools**

---

## Documentation

📖 Full details: [ENABLING_WRITE_OPERATIONS.md](./ENABLING_WRITE_OPERATIONS.md)
📖 Complete API reference: [README.md](./README.md)

---

## Safety

- ✅ Write guard prevents accidental changes (off by default)
- ✅ OAuth scopes verified (you have all necessary permissions)
- ✅ ETag conflicts handled automatically by typed tools
- ✅ Clear error messages when writes are disabled
- ⚠️ Always test in non-production first
- ⚠️ Only delete items you created for testing
