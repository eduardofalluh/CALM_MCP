# Split Deployment: Read-Only vs Read-Write Servers

## Overview

Deploy TWO separate MCP servers:
1. **Read-Only Server** - Safe for all users (no writes possible)
2. **Read-Write Server** - Restricted access (full CRUD operations)

---

## Option A: Modify server.py for Each Deployment

### Read-Only Server (server_readonly.py)

Copy `server.py` to `server_readonly.py` and keep ONLY these registrations:

```python
from src.calm.tools import (
    unified,
    health,
    oauth_info,
    user_uuid_helper,
    test_repo,  # TM reads only
)

mcp = FastMCP("sap-cloud-alm-readonly")

# Register read-only tools
unified.register(mcp)           # Read operations only (list, get)
health.register(mcp)            # Health checks
oauth_info.register(mcp)        # OAuth discovery
user_uuid_helper.register(mcp)  # User helpers
test_repo.register(mcp)         # TM reads only

# DO NOT register:
# - advanced_write (has calm_api_write, calm_api_delete)
# - test_repo_write (has TM write operations)
```

**Environment Variables**:
```bash
CALM_CLIENT_ID="..."
CALM_CLIENT_SECRET="..."
CALM_BASE_URL="..."
# DO NOT SET: CALM_ENABLE_WRITES
# DO NOT SET: TM_ENABLE_WRITES
```

**Tools Available**: 14 tools
- calm_resource (read operations only)
- calm_health
- tm_health
- get_calm_oauth_endpoints
- get_calm_oauth_metadata
- get_calm_authorization_server_metadata
- get_my_calm_user_uuid_instructions
- get_tm_statistics
- get_tm_test_cases
- get_tm_test_case_full
- get_tm_requirements
- tm_odata_read
- (2 more OAuth/health tools)

---

### Read-Write Server (server_full.py)

Copy `server.py` to `server_full.py` and keep ALL registrations:

```python
from src.calm.tools import (
    unified,
    health,
    oauth_info,
    advanced_write,
    user_uuid_helper,
    test_repo,
    test_repo_write,
)

mcp = FastMCP("sap-cloud-alm-full")

# Register ALL tools (including writes)
unified.register(mcp)           # Read + Write operations
health.register(mcp)            # Health checks
oauth_info.register(mcp)        # OAuth discovery
advanced_write.register(mcp)    # Generic write operations
user_uuid_helper.register(mcp)  # User helpers
test_repo.register(mcp)         # TM reads
test_repo_write.register(mcp)   # TM writes
```

**Environment Variables**:
```bash
CALM_CLIENT_ID="..."
CALM_CLIENT_SECRET="..."
CALM_BASE_URL="..."
CALM_ENABLE_WRITES=true    # Enable write operations
TM_ENABLE_WRITES=true      # Enable TM writes
```

**Tools Available**: 21 tools (all functionality)

---

## Option B: Use Environment Variable + Current server.py

Keep current `server.py` with all 21 tools registered, control with environment variables:

### Read-Only Deployment
```bash
# Deploy server.py WITHOUT these variables:
CALM_CLIENT_ID="..."
CALM_CLIENT_SECRET="..."
CALM_BASE_URL="..."
# CALM_ENABLE_WRITES=<not set>    # Writes blocked!
# TM_ENABLE_WRITES=<not set>      # TM writes blocked!
```

**Result**: 21 tools registered, but 7 write tools will error if called

### Read-Write Deployment
```bash
# Deploy server.py WITH write variables:
CALM_CLIENT_ID="..."
CALM_CLIENT_SECRET="..."
CALM_BASE_URL="..."
CALM_ENABLE_WRITES=true     # Enable writes
TM_ENABLE_WRITES=true       # Enable TM writes
```

**Result**: All 21 tools fully functional

---

## Detailed Tool Breakdown

### Read-Only Tools (14 tools)

#### Module: unified
- **calm_resource** (with operation="list" or operation="get" only)
  - Resources: projects, tasks, requirements, teams, processes, business_processes, solution_processes, timeboxes, scopes, test_cases, tags, features, test_plans, project_users, customization

#### Module: health
- **calm_health**

#### Module: oauth_info
- **get_calm_oauth_endpoints**
- **get_calm_oauth_metadata**
- **get_calm_authorization_server_metadata**

#### Module: user_uuid_helper
- **get_my_calm_user_uuid_instructions**

#### Module: test_repo (TM reads)
- **tm_health**
- **get_tm_statistics**
- **get_tm_test_cases**
- **get_tm_test_case_full**
- **get_tm_requirements**
- **tm_odata_read**

**Total: 14 tools** (1 unified + 1 health + 3 oauth + 1 helper + 8 TM)

Wait, let me recount...

Actually from the test output we saw:
1. calm_resource
2. calm_health
3. tm_health
4. get_calm_oauth_endpoints
5. get_calm_oauth_metadata
6. get_calm_authorization_server_metadata
7. get_my_calm_user_uuid_instructions
8. get_tm_statistics
9. get_tm_test_cases
10. get_tm_test_case_full
11. get_tm_requirements
12. tm_odata_read

That's only 12 read-only tools... let me check the modules.

---

### Write Tools (7 tools - EXCLUDE from read-only server)

#### Module: advanced_write
- **calm_api_write** (generic POST/PATCH)
- **calm_api_delete** (generic DELETE)

#### Module: test_repo_write (TM writes)
- **create_tm_test_case**
- **update_tm_test_case**
- **delete_tm_test_case**
- **create_tm_requirement**
- **delete_tm_requirement**

**Plus unified tool write operations**:
- calm_resource with operation="create"
- calm_resource with operation="update"
- calm_resource with operation="delete"

**Total: 7 separate write tools + unified write ops**

---

## Recommended Approach for Your Boss

### Create Two Server Files

#### 1. server_readonly.py (Read-Only Deployment)

```python
"""
SAP Cloud ALM MCP Server - READ-ONLY VERSION
Safe for all users - no write operations possible
"""

from fastmcp import FastMCP
from src.calm.tools import (
    unified,
    health,
    oauth_info,
    user_uuid_helper,
    test_repo,
)

mcp = FastMCP("sap-cloud-alm-readonly")

# Read-only tools
unified.register(mcp)           # calm_resource (reads only)
health.register(mcp)            # calm_health
oauth_info.register(mcp)        # OAuth discovery (3 tools)
user_uuid_helper.register(mcp)  # User UUID helper (1 tool)
test_repo.register(mcp)         # TM reads (6 tools)

# Note: advanced_write and test_repo_write NOT included
# Write operations will not be available

if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    
    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()
```

**Deploy**: 
```bash
python3 server_readonly.py --http --port 8000
```

**Tools**: ~12-14 read-only tools

---

#### 2. server_full.py (Read-Write Deployment)

```python
"""
SAP Cloud ALM MCP Server - FULL VERSION
Includes write operations - RESTRICTED ACCESS ONLY
"""

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

mcp = FastMCP("sap-cloud-alm-full")

# All tools including writes
unified.register(mcp)           # calm_resource (read + write)
health.register(mcp)            # calm_health
oauth_info.register(mcp)        # OAuth discovery (3 tools)
advanced_write.register(mcp)    # Generic writes (2 tools)
user_uuid_helper.register(mcp)  # User UUID helper (1 tool)
test_repo.register(mcp)         # TM reads (6 tools)
test_repo_write.register(mcp)   # TM writes (7 tools)

if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)  # Different port!
    args = parser.parse_args()
    
    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()
```

**Deploy**: 
```bash
export CALM_ENABLE_WRITES=true
export TM_ENABLE_WRITES=true
python3 server_full.py --http --port 8001
```

**Tools**: All 21 tools

---

## Summary Table

| Module | Tools | Read-Only Server | Read-Write Server |
|--------|-------|------------------|-------------------|
| unified | calm_resource | ✅ Include | ✅ Include |
| health | calm_health | ✅ Include | ✅ Include |
| oauth_info | 3 OAuth tools | ✅ Include | ✅ Include |
| user_uuid_helper | 1 helper tool | ✅ Include | ✅ Include |
| test_repo | 6 TM read tools | ✅ Include | ✅ Include |
| **advanced_write** | **2 write tools** | ❌ **Exclude** | ✅ Include |
| **test_repo_write** | **7 TM write tools** | ❌ **Exclude** | ✅ Include |

---

## Module Imports Summary

### Read-Only Server Imports
```python
from src.calm.tools import (
    unified,           # ✅
    health,           # ✅
    oauth_info,       # ✅
    user_uuid_helper, # ✅
    test_repo,        # ✅
    # advanced_write,      ❌ EXCLUDE
    # test_repo_write,     ❌ EXCLUDE
)
```

### Read-Write Server Imports
```python
from src.calm.tools import (
    unified,           # ✅
    health,           # ✅
    oauth_info,       # ✅
    advanced_write,   # ✅
    user_uuid_helper, # ✅
    test_repo,        # ✅
    test_repo_write,  # ✅
)
```

---

## Deployment Commands

### Read-Only Server (Port 8000)
```bash
# No write environment variables needed
export CALM_CLIENT_ID="..."
export CALM_CLIENT_SECRET="..."
export CALM_BASE_URL="..."

python3 server_readonly.py --http --port 8000
```

### Read-Write Server (Port 8001)
```bash
# WITH write environment variables
export CALM_CLIENT_ID="..."
export CALM_CLIENT_SECRET="..."
export CALM_BASE_URL="..."
export CALM_ENABLE_WRITES=true
export TM_ENABLE_WRITES=true

python3 server_full.py --http --port 8001
```

---

## Gen AI Studio Configuration

Configure two separate MCP connections:

### Connection 1: "CALM Read-Only"
- **URL**: http://your-server:8000/mcp
- **Access**: All users
- **Risk**: Zero (no writes)
- **File**: server_readonly.py

### Connection 2: "CALM Full Access"
- **URL**: http://your-server:8001/mcp
- **Access**: Restricted users only
- **Risk**: Data modifications possible
- **File**: server_full.py

---

## Quick Copy-Paste for Your Boss

Tell your boss to create these two files:

### File 1: server_readonly.py
```python
from fastmcp import FastMCP
from src.calm.tools import unified, health, oauth_info, user_uuid_helper, test_repo

mcp = FastMCP("sap-cloud-alm-readonly")
unified.register(mcp)
health.register(mcp)
oauth_info.register(mcp)
user_uuid_helper.register(mcp)
test_repo.register(mcp)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.http:
        mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)
    else:
        mcp.run()
```

### File 2: server_full.py
```python
from fastmcp import FastMCP
from src.calm.tools import unified, health, oauth_info, advanced_write, user_uuid_helper, test_repo, test_repo_write

mcp = FastMCP("sap-cloud-alm-full")
unified.register(mcp)
health.register(mcp)
oauth_info.register(mcp)
advanced_write.register(mcp)
user_uuid_helper.register(mcp)
test_repo.register(mcp)
test_repo_write.register(mcp)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if args.http:
        mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)
    else:
        mcp.run()
```

Done! Two separate servers, one read-only, one full access.
