# Enabling Write Operations in SAP Cloud ALM MCP Server

## Overview

The MCP server includes **38 write tools** (create, update, delete) that are **disabled by default** as a safety guard. This prevents accidental modifications to the SAP Cloud ALM tenant.

## Prerequisites

✅ **Your OAuth scopes are already configured correctly!** The authorities you provided include all necessary permissions:

```json
"authorities": [
    "$XSMASTERAPPNAME.calm-api.tasks.write",
    "$XSMASTERAPPNAME.calm-api.tasks.read",
    "$XSMASTERAPPNAME.calm-api.projects.write",
    "$XSMASTERAPPNAME.calm-api.projects.read",
    "$XSMASTERAPPNAME.calm-api.processauthoring.write",
    "$XSMASTERAPPNAME.calm-api.processauthoring.delete",
    "$XSMASTERAPPNAME.calm-api.processmanagement.write",
    "$XSMASTERAPPNAME.calm-api.processmanagement.delete",
    "$XSMASTERAPPNAME.calm-api.testcases.write",
    "$XSMASTERAPPNAME.calm-api.testcases.delete",
    "$XSMASTERAPPNAME.calm-api.testcases.force-delete"
]
```

## How to Enable Write Operations

### Option 1: Environment Variable (Recommended)

Set the environment variable **`CALM_ENABLE_WRITES=true`** before starting the MCP server.

#### For Local Development (`.env` file):
```bash
# In CALM_MCP directory
echo "CALM_ENABLE_WRITES=true" >> .env
```

Or manually edit `.env`:
```bash
# --- Write tools safety guard ---
CALM_ENABLE_WRITES=true
```

#### For Shell/Terminal:
```bash
export CALM_ENABLE_WRITES=true
python3 server.py
```

#### For Claude Desktop (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "sap-cloud-alm": {
      "command": "python3",
      "args": ["/path/to/CALM_MCP/server.py"],
      "env": {
        "IDENTITY_ZONE": "your-identity-zone",
        "REGION_ZONE": "your-region-zone",
        "CALM_CLIENT_ID": "your-client-id",
        "CALM_CLIENT_SECRET": "your-client-secret",
        "CALM_ENABLE_WRITES": "true"
      }
    }
  }
}
```

#### For Syntax GenAI Studio (Deployment):
Add `CALM_ENABLE_WRITES=true` to the deployment environment variables/secrets.

### Option 2: Docker/Container Deployment

In your `docker-compose.yml` or deployment manifest:
```yaml
environment:
  - CALM_ENABLE_WRITES=true
  - CALM_CLIENT_ID=your-client-id
  - CALM_CLIENT_SECRET=your-client-secret
  - IDENTITY_ZONE=your-identity-zone
  - REGION_ZONE=your-region-zone
```

## What Gets Enabled

When `CALM_ENABLE_WRITES=true` is set, **38 write tools** become functional:

### Create Operations (15 tools)
- `create_calm_project`, `create_calm_timebox`
- `create_calm_task`, `create_calm_requirement`, `create_calm_task_relation`, `create_calm_task_comment`
- `create_calm_business_process`, `create_calm_solution_process`
- `create_calm_scope`
- `create_calm_test_case`, `create_calm_test_action`
- `calm_api_write` (generic POST/PATCH)

### Update Operations (13 tools)
- `update_calm_project`, `update_calm_timebox`
- `update_calm_task`, `update_calm_requirement`, `update_calm_task_comment`
- `update_calm_business_process`, `update_calm_solution_process`
- `update_calm_scope`, `assign_calm_scenario_versions`, `update_calm_scope_assignments`
- `update_calm_test_case`, `update_calm_test_activity`, `update_calm_test_action`

### Delete Operations (10 tools)
- `delete_calm_timebox`
- `delete_calm_task`, `delete_calm_requirement`, `delete_calm_task_relation`, `delete_calm_task_comment`
- `delete_calm_business_process`, `delete_calm_solution_process`
- `delete_calm_scope`
- `delete_calm_test_case`, `delete_calm_test_activity`, `delete_calm_test_action`
- `calm_api_delete` (generic DELETE)

## Verification

### 1. Check if writes are enabled:
Call the `calm_health` tool:
```json
{
  "server": "sap-cloud-alm",
  "writes_enabled": true,  // <-- Should be true
  "token_configured": true,
  "...": "..."
}
```

### 2. Test with a safe create/delete cycle:
```bash
# Create a clearly labeled test task
create_calm_task(
  project_id="your-project-id",
  title="MCP Test - Safe to Delete - 2026-07-28",
  task_type="Project Task"
)

# Immediately delete it using the returned task_id
delete_calm_task(task_id="returned-task-id")
```

## Safety Recommendations

⚠️ **Important Safety Notes:**

1. **Test in a non-production tenant first** if possible
2. **Only delete items you explicitly created** for testing (labeled "MCP Test")
3. **Never delete existing production data** without explicit authorization
4. **Deletions are typically permanent** (no undo in most cases)
5. **Set `CALM_ENABLE_WRITES=false`** (or unset it) when writes are not needed

## Troubleshooting

### Problem: Write tools return error "Write operations are disabled"
**Solution:** Set `CALM_ENABLE_WRITES=true` and restart the MCP server.

### Problem: Write tools return "Insufficient scopes" or 403 errors
**Solution:** Your OAuth client needs write/delete scopes. Verify with your BTP administrator that all the authorities listed above are granted.

### Problem: Changes work but aren't persisted
**Solution:** Check for ETag errors (412 Precondition Failed). Some operations require `If-Match` headers - the typed tools handle this automatically by fetching ETags first.

## Reference

- **Code location:** `src/calm/dependencies.py` → `writes_enabled()` function
- **Guard check:** `ensure_writes_enabled()` called by every write tool
- **Default behavior:** Writes DISABLED (read-only server)
- **Accepted values:** `true`, `1`, `yes`, `on` (case-insensitive)

---

## Summary for CALM Owner

**To enable write operations:**

1. ✅ OAuth scopes are already correctly configured (no changes needed in SAP BTP)
2. ✅ Set environment variable: `CALM_ENABLE_WRITES=true`
3. ✅ Restart the MCP server
4. ✅ Verify with `calm_health` tool (check `writes_enabled: true`)
5. ✅ Test with a safe create → delete cycle using clearly labeled test items

**No code changes required** - this is purely an environment configuration.
