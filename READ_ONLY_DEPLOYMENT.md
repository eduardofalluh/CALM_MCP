# Read-Only Deployment Guide

## 🔒 Safe Read-Only Deployment for Gen AI Studio

**Purpose**: Deploy MCP server with ONLY read operations enabled  
**Safety**: Zero risk - no data modifications possible  
**Tools Available**: 21 tools (1 unified + 20 specialized)

---

## Quick Start: Read-Only Mode

### Deploy with These Environment Variables ONLY:

```bash
# Required for authentication
CALM_CLIENT_ID=<your-client-id>
CALM_CLIENT_SECRET=<your-client-secret>
CALM_BASE_URL=<your-calm-url>

# DO NOT SET THESE (keeps writes disabled):
# CALM_ENABLE_WRITES=true    ❌ DON'T SET THIS
# TM_ENABLE_WRITES=true      ❌ DON'T SET THIS
```

**Result**: All write operations are automatically blocked. Only reads work.

---

## Read-Only Tools (21 Total)

### 1. Unified Read-Only Tool (1 tool)

**Tool**: `calm_resource`

**Read Operations Available**:
```python
# List resources
calm_resource(resource="projects", operation="list")
calm_resource(resource="tasks", operation="list", project_id="P001")
calm_resource(resource="requirements", operation="list", project_id="P001")
calm_resource(resource="teams", operation="list")
calm_resource(resource="scopes", operation="list")
calm_resource(resource="test_cases", operation="list")
calm_resource(resource="timeboxes", operation="list", project_id="P001")
calm_resource(resource="business_processes", operation="list")
calm_resource(resource="solution_processes", operation="list")
calm_resource(resource="processes", operation="list")  # Combined
calm_resource(resource="tags", operation="list", project_id="P001")
calm_resource(resource="features", operation="list", project_id="P001")
calm_resource(resource="test_plans", operation="list", project_id="P001")
calm_resource(resource="project_users", operation="list", project_id="P001")

# Get specific resource
calm_resource(resource="customization", operation="get", project_id="P001")
```

**Write Operations** (BLOCKED in read-only mode):
```python
# These will raise error: "Write operations disabled (CALM_ENABLE_WRITES not set)"
calm_resource(resource="tasks", operation="create", ...)  # ❌ Blocked
calm_resource(resource="tasks", operation="update", ...)  # ❌ Blocked
calm_resource(resource="tasks", operation="delete", ...)  # ❌ Blocked
```

**Resources Available** (15):
1. projects
2. tasks
3. requirements
4. teams
5. processes (combined business + solution)
6. business_processes
7. solution_processes
8. timeboxes
9. scopes
10. test_cases
11. tags
12. features
13. test_plans
14. project_users
15. customization

---

### 2. Health Check Tools (2 tools)

**Read-Only Tools**:
- `calm_health` - Check CALM API health
- `tm_health` - Check Test Management health

**Usage**:
```python
calm_health()  # Returns CALM API status
tm_health()    # Returns TM API status
```

---

### 3. OAuth Discovery Tools (3 tools)

**Read-Only Tools**:
- `get_calm_oauth_endpoints` - Get OAuth endpoint URLs
- `get_calm_oauth_metadata` - Get OAuth configuration
- `get_calm_authorization_server_metadata` - Get OAuth server details

**Usage**:
```python
get_calm_oauth_endpoints()  # Returns OAuth URLs
```

---

### 4. User Helper Tools (1 tool)

**Read-Only Tool**:
- `get_my_calm_user_uuid_instructions` - Instructions for getting user UUID

---

### 5. BTP Test Management READ Tools (6 tools)

**Read-Only Tools**:
- `get_tm_statistics` - Get TM statistics
- `get_tm_test_cases` - List test cases
- `get_tm_test_case_full` - Get detailed test case
- `get_tm_requirements` - List requirements
- `tm_odata_read` - Generic TM read operations
- `tm_health` - TM health check

**Usage**:
```python
get_tm_statistics()
get_tm_test_cases()
get_tm_test_case_full(test_case_id="TC001")
```

---

### 6. Advanced Tools (2 tools - WRITES BLOCKED)

**Tools** (read-capable, writes blocked):
- `calm_api_write` - Generic POST/PATCH (BLOCKED without CALM_ENABLE_WRITES)
- `calm_api_delete` - Generic DELETE (BLOCKED without CALM_ENABLE_WRITES)

**Status in Read-Only Mode**: ❌ Both blocked (will error if called)

---

### 7. BTP Test Management WRITE Tools (7 tools - BLOCKED)

**Tools** (BLOCKED without TM_ENABLE_WRITES):
- `create_tm_test_case` - ❌ Blocked
- `update_tm_test_case` - ❌ Blocked
- `delete_tm_test_case` - ❌ Blocked
- `create_tm_requirement` - ❌ Blocked
- `delete_tm_requirement` - ❌ Blocked
- `tm_odata_write` - ❌ Blocked
- `tm_odata_delete` - ❌ Blocked

**Status in Read-Only Mode**: ❌ All blocked (will error if called)

---

## Summary: Read-Only Deployment

### Tools Fully Functional (14 tools)
✅ 1 unified read tool (calm_resource with read operations)  
✅ 2 health check tools  
✅ 3 OAuth discovery tools  
✅ 1 user helper tool  
✅ 6 TM read tools  
✅ 1 TM health check  

**Total Functional**: 14 tools

### Tools Blocked/Error (7 tools)
❌ 2 advanced write tools (calm_api_write, calm_api_delete)  
❌ 5 TM write tools (create/update/delete operations)  

**Total Blocked**: 7 tools (will error if called)

---

## Deployment Commands

### 1. Set Environment Variables (Read-Only)

```bash
# Required
export CALM_CLIENT_ID="your-client-id"
export CALM_CLIENT_SECRET="your-client-secret"
export CALM_BASE_URL="https://your-tenant.region.alm.cloud.sap"

# Optional (for certificate-based auth)
export CALM_CLIENT_CERT="/path/to/cert.pem"
export CALM_CLIENT_KEY="/path/to/key.pem"

# DO NOT SET (keeps writes disabled):
# export CALM_ENABLE_WRITES=true    ❌ Leave unset!
# export TM_ENABLE_WRITES=true      ❌ Leave unset!
```

### 2. Start Server

```bash
# For Gen AI Studio (HTTP mode):
python3 server.py --http --port 8000

# For Claude Desktop (stdio mode):
python3 server.py
```

### 3. Verify Read-Only Mode

```bash
# Test that reads work:
# Use calm_resource(resource="projects", operation="list")
# Should return list of projects ✅

# Test that writes are blocked:
# Use calm_resource(resource="projects", operation="create", data={...})
# Should raise error: "Write operations disabled" ✅
```

---

## What Happens When Write is Attempted?

### Error Message:
```
ValueError: Write operations disabled. Set CALM_ENABLE_WRITES=true to enable.
```

### Example:
```python
# This will work (read):
projects = calm_resource(resource="projects", operation="list")
# ✅ Returns list of projects

# This will error (write):
new_project = calm_resource(
    resource="projects",
    operation="create",
    data={"name": "New Project"}
)
# ❌ Raises: ValueError: Write operations disabled
```

---

## Migration Path: Read-Only → Full Access

When ready to enable writes:

### Step 1: Add Environment Variable
```bash
export CALM_ENABLE_WRITES=true
```

### Step 2: Restart Server
```bash
# Server will now allow write operations
python3 server.py --http --port 8000
```

### Step 3: (Optional) Enable TM Writes
```bash
export TM_ENABLE_WRITES=true
```

**No code changes needed!** Just environment variables.

---

## Safety Features in Read-Only Mode

### ✅ What's Protected:
1. **No data modifications** - All create/update/delete blocked
2. **No accidental writes** - Guards at code level
3. **Clear error messages** - Users know writes are disabled
4. **Easy to enable** - Just set environment variable when ready

### ✅ What Still Works:
1. **All read operations** - List and get data
2. **Health checks** - Monitor system status
3. **OAuth discovery** - Authentication setup
4. **TM reads** - View test management data

---

## Read-Only Tools Summary Table

| Tool | Type | Read-Only Status | Notes |
|------|------|------------------|-------|
| calm_resource | Unified | ✅ Partial | Reads work, writes blocked |
| calm_health | Health | ✅ Full | Read-only by nature |
| tm_health | Health | ✅ Full | Read-only by nature |
| get_calm_oauth_endpoints | OAuth | ✅ Full | Read-only by nature |
| get_calm_oauth_metadata | OAuth | ✅ Full | Read-only by nature |
| get_calm_authorization_server_metadata | OAuth | ✅ Full | Read-only by nature |
| get_my_calm_user_uuid_instructions | Helper | ✅ Full | Read-only by nature |
| get_tm_statistics | TM Read | ✅ Full | Read-only by nature |
| get_tm_test_cases | TM Read | ✅ Full | Read-only by nature |
| get_tm_test_case_full | TM Read | ✅ Full | Read-only by nature |
| get_tm_requirements | TM Read | ✅ Full | Read-only by nature |
| tm_odata_read | TM Read | ✅ Full | Read-only by nature |
| calm_api_write | Advanced | ❌ Blocked | Requires CALM_ENABLE_WRITES |
| calm_api_delete | Advanced | ❌ Blocked | Requires CALM_ENABLE_WRITES |
| create_tm_test_case | TM Write | ❌ Blocked | Requires TM_ENABLE_WRITES |
| update_tm_test_case | TM Write | ❌ Blocked | Requires TM_ENABLE_WRITES |
| delete_tm_test_case | TM Write | ❌ Blocked | Requires TM_ENABLE_WRITES |
| create_tm_requirement | TM Write | ❌ Blocked | Requires TM_ENABLE_WRITES |
| delete_tm_requirement | TM Write | ❌ Blocked | Requires TM_ENABLE_WRITES |
| tm_odata_write | TM Write | ❌ Blocked | Requires TM_ENABLE_WRITES |
| tm_odata_delete | TM Write | ❌ Blocked | Requires TM_ENABLE_WRITES |

---

## Recommendation for Boss

### Phase 1: Read-Only Deployment (SAFE)
✅ Deploy NOW with only read operations  
✅ Zero risk - no data modifications possible  
✅ 14 fully functional tools  
✅ Users can explore and query data safely  
✅ Test integration with Gen AI Studio  

### Phase 2: Enable Writes (Later)
⏳ After read-only validation (1-2 weeks)  
⏳ Set CALM_ENABLE_WRITES=true  
⏳ Restart server  
⏳ All 21 tools become fully functional  

---

## Quick Reference

**✅ Safe for Production**: Read-only mode  
**✅ Tools Available**: 14 fully functional + 7 blocked  
**✅ Risk Level**: ZERO (no writes possible)  
**✅ Setup Time**: 5 minutes  

**Deploy Command**:
```bash
# Set auth vars only (no CALM_ENABLE_WRITES)
export CALM_CLIENT_ID="..."
export CALM_CLIENT_SECRET="..."
export CALM_BASE_URL="..."

# Start server
python3 server.py --http --port 8000
```

**Result**: Safe, read-only access to all CALM data!

---

**Created**: 2026-09-22  
**Status**: READY FOR READ-ONLY DEPLOYMENT ✅  
**Risk**: ZERO (no write operations possible)
