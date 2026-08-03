# User Email Tracking for CALM Audit Logs

## Problem

SAP Cloud ALM shows "System Action" in audit logs instead of the actual user who performed the action via the MCP server. This makes it impossible to track who created/updated/deleted items.

## Solution

The MCP server now supports user email tracking through multiple methods:

### Method 1: HTTP Header (Recommended for GenAI Studio)

GenAI Studio or the calling application should inject the user's email in the request headers:

```
X-User-Email: user@company.com
```

Alternative header names supported:
- `X-User-Email` (primary)
- `X-Forwarded-User` (fallback)
- `X-Calm-User-Email` (CALM-specific)

### Method 2: Environment Variable (For stdio/local development)

Set the user email as an environment variable:

```bash
export CALM_USER_EMAIL=user@company.com
```

Or in `.env` file:
```bash
CALM_USER_EMAIL=user@company.com
```

### Method 3: GenAI Studio Configuration

In GenAI Studio MCP connection settings, add a custom header:

| Header Name | Value |
|-------------|-------|
| `X-User-Email` | `{{user.email}}` or the actual email |

GenAI Studio should automatically resolve `{{user.email}}` to the authenticated user's email.

## How It Works

1. **Header Resolution**: The MCP server reads the user email from request headers in this order:
   - `X-User-Email`
   - `X-Forwarded-User`  
   - `X-Calm-User-Email`

2. **Fallback**: If no header is provided, it falls back to `CALM_USER_EMAIL` environment variable

3. **Propagation**: The user email is included in all write requests to CALM APIs using these headers:
   - `X-User-Email: user@company.com`
   - `X-Forwarded-User: user@company.com`

4. **CALM Processing**: SAP Cloud ALM should recognize these headers and use them for audit logging instead of showing "System Action"

## Implementation Details

### Files Modified

- `src/calm/models.py`: Added `user_email` field to `CALMHeaders`
- `src/calm/dependencies.py`: Extract user email from request headers or env var
- `src/calm/client.py`: 
  - Updated `_write()` to accept and send `user_email` in headers
  - Updated `_delete()` to accept and send `user_email` in headers

### All Write Operations Include User Email

When `user_email` is provided, **all 48 write tools** automatically include it in requests:
- Tasks (create/update/delete)
- Projects (create/update)
- Processes (create/update/delete)
- Scopes (create/update/delete)
- Test Cases (create/update/delete)
- All sub-entities

## Testing

### Test with curl (HTTP mode)

```bash
curl -X POST http://localhost:8000/mcp/tools/call \
  -H "Content-Type: application/json" \
  -H "X-User-Email: john.doe@company.com" \
  -H "X-Calm-Client-ID: your-client-id" \
  -H "X-Calm-Client-Secret: your-client-secret" \
  -d '{
    "tool": "create_calm_task",
    "arguments": {
      "project_id": "P001",
      "title": "Test Task",
      "task_type": "Project Task"
    }
  }'
```

### Test with environment variable (stdio mode)

```bash
export CALM_USER_EMAIL=john.doe@company.com
export CALM_ENABLE_WRITES=true
python server.py
```

## Expected Result

After implementation, CALM audit logs should show:
- ✅ **Before**: "Created by: System Action"
- ✅ **After**: "Created by: john.doe@company.com" (or user's name if CALM maps email to user)

## Notes

1. **SAP Cloud ALM Compatibility**: SAP Cloud ALM needs to be configured to recognize and use the `X-User-Email` or `X-Forwarded-User` headers. Check with your SAP administrator if this feature is enabled.

2. **GenAI Studio Integration**: The GenAI Studio team needs to:
   - Add support for `X-User-Email` header in MCP requests
   - Automatically populate it with the authenticated user's email
   - Document this in their MCP connection guide

3. **Security**: The user email is only used for audit logging. Authentication still uses OAuth2 tokens.

4. **Backward Compatibility**: If no user email is provided, the system continues to work as before (showing "System Action").

## Configuration Examples

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "sap-cloud-alm": {
      "command": "python3",
      "args": ["/path/to/CALM_MCP/server.py"],
      "env": {
        "CALM_CLIENT_ID": "your-client-id",
        "CALM_CLIENT_SECRET": "your-client-secret",
        "CALM_ENABLE_WRITES": "true",
        "CALM_USER_EMAIL": "your.email@company.com"
      }
    }
  }
}
```

### GenAI Studio Deployment

Add environment variables:
```yaml
environment:
  - CALM_CLIENT_ID=your-client-id
  - CALM_CLIENT_SECRET=your-secret
  - CALM_ENABLE_WRITES=true
  - CALM_USER_EMAIL=default-user@company.com  # Fallback if header not provided
```

And configure MCP connection to inject header:
```
Custom Headers:
  X-User-Email: {{user.email}}
```

---

**Status**: Implemented but requires SAP Cloud ALM configuration to recognize the headers  
**Date**: 2026-07-28
