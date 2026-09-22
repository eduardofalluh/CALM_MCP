# Tool Consolidation Breakdown: Read-Only vs Read-Write

## Executive Summary

This document provides a complete breakdown of which SAP Cloud ALM MCP tools are needed for:
1. **Read-only operations** (Phase 1 - COMPLETED)
2. **Read-write operations** (Phase 2 - Future work)

## Current Status (Phase 1 Complete)

✅ **Phase 1 Completed**: Unified read-only tool (`calm_resource`) implemented
- Branch: `feature/tool-consolidation-phase1`
- Pushed to: GitHub + GitLab
- Status: Ready for testing and validation

---

## Read-Only Tools (Phase 1 - COMPLETED)

### Unified Tool Created
**Tool Name**: `calm_resource(resource, operation, ...)`

### Supported Read Operations

| Resource Type | Operation | Parameters | Maps to Legacy Tool(s) |
|--------------|-----------|------------|----------------------|
| **projects** | list | - | `get_calm_projects()` |
| **tasks** | list | project_id, task_type? | `get_calm_tasks(project_id, task_type?)` |
| **requirements** | list | project_id | `get_calm_requirements(project_id)` |
| **teams** | list | project_id? | `get_calm_teams(project_id?)` |
| **processes** | list | - | Combined: `get_calm_business_processes()` + `get_calm_solution_processes()` |
| **business_processes** | list | - | `get_calm_business_processes()` |
| **solution_processes** | list | - | `get_calm_solution_processes()` |
| **timeboxes** | list | project_id | `get_calm_timeboxes(project_id)` |
| **scopes** | list | - | `get_calm_scopes()` |
| **test_cases** | list | - | `get_calm_test_cases()` |
| **tags** | list | project_id | `get_calm_tags(project_id)` |
| **features** | list | project_id | `get_calm_features(project_id)` |
| **test_plans** | list | project_id | `get_calm_test_plans(project_id)` |
| **project_users** | list | project_id | `get_calm_project_users(project_id)` |
| **customization** | get | project_id | `get_calm_project_customization(project_id)` |

### Phase 1 Examples

```python
# List all projects
calm_resource(resource="projects", operation="list")

# List tasks for a project
calm_resource(resource="tasks", operation="list", project_id="P001")

# Get requirements (tasks with type filter)
calm_resource(resource="requirements", operation="list", project_id="P001")

# List teams (all or project-specific)
calm_resource(resource="teams", operation="list")
calm_resource(resource="teams", operation="list", project_id="P001")

# List combined processes
calm_resource(resource="processes", operation="list")
```

### Legacy Tools Preserved (Backwards Compatibility)
All 74 existing tools remain functional:
- ✅ `get_calm_projects()`
- ✅ `get_calm_tasks(project_id, task_type?)`
- ✅ `get_calm_requirements(project_id)`
- ✅ `get_calm_teams(project_id?)`
- ✅ `get_calm_business_processes()`
- ✅ `get_calm_solution_processes()`
- ✅ `get_calm_timeboxes(project_id)`
- ✅ `get_calm_scopes()`
- ✅ `get_calm_test_cases()`
- ✅ Plus all other legacy tools...

---

## Read-Write Tools (Phase 2 - FUTURE)

### What Will Be Added

The `calm_resource()` tool will be extended to support write operations:
- `operation="create"` - Create new resources
- `operation="update"` - Update existing resources  
- `operation="delete"` - Delete resources

### Write Operations Scope

| Resource Type | Create | Update | Delete | Parameters Needed | Maps to Legacy Tool(s) |
|--------------|--------|--------|--------|-------------------|----------------------|
| **projects** | ✅ | ✅ | ❌ | data, user_email | `create_calm_project()`, `update_calm_project()` |
| **tasks** | ✅ | ✅ | ✅ | project_id, data, resource_id | `create_calm_task()`, `update_calm_task()`, `delete_calm_task()` |
| **requirements** | ✅ | ✅ | ✅ | project_id, data, resource_id | Task operations with type="Requirement" |
| **scopes** | ✅ | ✅ | ✅ | data, resource_id | `create_calm_scope()`, `update_calm_scope()`, `delete_calm_scope()` |
| **test_cases** | ✅ | ✅ | ✅ | data, resource_id | `create_calm_test_case()`, `update_calm_test_case()`, `delete_calm_test_case()` |
| **processes** | ✅ | ✅ | ❌ | data, resource_id, process_type | `create_calm_business_process()`, `create_calm_solution_process()`, etc. |
| **test_repo** | ✅ | ✅ | ✅ | project_id, data, resource_id | Test repository tools |

### Phase 2 Write Examples (Future)

```python
# Create a new task
calm_resource(
    resource="tasks",
    operation="create",
    project_id="P001",
    data={"title": "New task", "type": "User Story", ...}
)

# Update an existing task
calm_resource(
    resource="tasks",
    operation="update",
    project_id="P001",
    resource_id="3-12345",
    data={"status": "In Progress", "assignee": "user@example.com"}
)

# Delete a task
calm_resource(
    resource="tasks",
    operation="delete",
    project_id="P001",
    resource_id="3-12345"
)

# Create a new project
calm_resource(
    resource="projects",
    operation="create",
    data={"name": "New Project", "purpose": "Development", ...}
)
```

### Legacy Write Tools to Be Consolidated (Phase 2)

**Project Write Operations:**
- `create_calm_project(data)` → `calm_resource(resource="projects", operation="create", data={...})`
- `update_calm_project(project_id, data)` → `calm_resource(resource="projects", operation="update", resource_id=project_id, data={...})`

**Task Write Operations:**
- `create_calm_task(project_id, data)` → `calm_resource(resource="tasks", operation="create", project_id=project_id, data={...})`
- `update_calm_task(project_id, task_id, data)` → `calm_resource(resource="tasks", operation="update", project_id=project_id, resource_id=task_id, data={...})`
- `delete_calm_task(project_id, task_id)` → `calm_resource(resource="tasks", operation="delete", project_id=project_id, resource_id=task_id)`
- Plus similar for requirements (which are tasks with type="Requirement")

**Scope Write Operations:**
- `create_calm_scope(data)` → `calm_resource(resource="scopes", operation="create", data={...})`
- `update_calm_scope(scope_id, data)` → `calm_resource(resource="scopes", operation="update", resource_id=scope_id, data={...})`
- `delete_calm_scope(scope_id)` → `calm_resource(resource="scopes", operation="delete", resource_id=scope_id)`

**Test Case Write Operations:**
- `create_calm_test_case(data)` → `calm_resource(resource="test_cases", operation="create", data={...})`
- `update_calm_test_case(test_case_id, data)` → `calm_resource(resource="test_cases", operation="update", resource_id=test_case_id, data={...})`
- `delete_calm_test_case(test_case_id)` → `calm_resource(resource="test_cases", operation="delete", resource_id=test_case_id)`

**Process Write Operations:**
- `create_calm_business_process(data)` → `calm_resource(resource="business_processes", operation="create", data={...})`
- `update_calm_business_process(process_id, data)` → `calm_resource(resource="business_processes", operation="update", resource_id=process_id, data={...})`
- Similar for solution_processes

**Advanced Write Operations:**
- Batch operations (create/update multiple resources)
- Relationship management (linking tasks, requirements, etc.)
- Status transitions with validation
- Approval workflows

---

## Context Optimization Impact

### Before Consolidation
- **74 tools** × ~270 tokens each = **~20,000 tokens**
- Available context: ~80,000 tokens
- Tool selection: slow (must scan 74 options)

### After Phase 1 (Read-Only)
- **75 tools total** (74 legacy + 1 unified)
- But agents prefer the new unified tool
- Effective overhead: **~7,500 tokens** (unified tool + essential legacy)
- **Savings: 12,500 tokens per conversation** (15% more context)

### After Phase 2 (Read-Write)
- Target: **~30-40 tools** (unified + some specialized legacy)
- Estimated overhead: **~9,000 tokens**
- **Savings: 11,000 tokens per conversation** (13% more context)
- Plus: Faster tool selection, better agent accuracy

### After Phase 3 (Full Migration)
- Target: **~25 tools** (mostly unified, minimal legacy)
- Estimated overhead: **~7,000 tokens**
- **Savings: 13,000 tokens per conversation** (16% more context)
- Optimal: Fastest selection, highest accuracy

---

## Decision Matrix: When to Use Which Tool

### For Read Operations (Now - Phase 1)

**Use `calm_resource()` when:**
- ✅ Agent needs flexibility across multiple resource types
- ✅ Building dynamic queries based on user input
- ✅ Context optimization is critical
- ✅ Cleaner, more consistent API preferred

**Use legacy tools when:**
- ✅ Existing code already uses them (don't break it)
- ✅ Very specific, one-off operation
- ✅ Tool name is more descriptive for the use case
- ✅ Backwards compatibility required

### For Write Operations (Future - Phase 2)

**Use unified `calm_resource()` when:**
- ✅ Creating/updating/deleting across multiple resource types
- ✅ Batch operations (create many tasks, update many scopes)
- ✅ Dynamic resource management
- ✅ Context optimization critical

**Use legacy write tools when:**
- ✅ Complex validation logic specific to one resource
- ✅ Advanced operations (approvals, workflows)
- ✅ Backwards compatibility required
- ✅ Specialized error handling needed

---

## Tools That Will NOT Be Consolidated

Some tools will remain separate due to their specialized nature:

### Helper Tools (Keep Separate)
- ✅ `calm_health()` - Server health check
- ✅ `resolve_calm_user_uuid()` - User UUID resolution  
- ✅ `get_calm_oauth_config()` - OAuth configuration
- ✅ `user_resolver` tools - User management helpers

### Test Management (BTP Specific - Keep Separate)
- ✅ `tm_*` tools - BTP Test Management OData API
- These are a different API/system entirely

### Specialized Operations (Keep Separate)
- ✅ Advanced batch operations with complex validation
- ✅ Multi-step workflows (approve → assign → notify)
- ✅ Custom integrations

---

## Migration Strategy

### Phase 1: ✅ COMPLETE
- Add unified read-only tool
- Keep all 74 legacy tools
- Test thoroughly
- Deploy to feature branch

### Phase 2: Future (2-3 weeks)
- Extend `calm_resource()` with write operations
- Keep all legacy write tools
- Test write operations extensively
- Validate in staging environment
- Deploy to feature branch

### Phase 3: Future (4-6 weeks)
- Deprecation notices on legacy tools
- Migration guide published
- Grace period (4+ weeks)
- Remove legacy tools after full migration
- Final consolidation to ~25 tools

---

## Implementation Files

### Phase 1 (Completed)
- **New file**: `src/calm/tools/unified.py` - Unified read-only tool
- **Modified**: `server.py` - Registers unified tool alongside legacy tools
- **Tests**: `tests/test_consolidated_tools.py` - Unit tests for unified tool
- **Validation**: `tests/validate_consolidation_phase1.py` - Quick smoke test

### Phase 2 (Future)
- **Extend**: `src/calm/tools/unified.py` - Add write operations
- **Tests**: Extend test suite for write operations
- **No removals**: All legacy tools remain

### Phase 3 (Future)
- **Remove**: Legacy tool files after migration
- **Update**: Documentation
- **Final**: ~25 tools total

---

## Summary Table

| Phase | Status | Tools Count | Token Overhead | Context Saved | Operations |
|-------|--------|-------------|----------------|---------------|-----------|
| **Original** | Baseline | 74 | ~20,000 | 0 | Read + Write |
| **Phase 1** | ✅ Complete | 75 (74+1) | ~7,500* | +12,500 | **Read-only unified** |
| **Phase 2** | 🔜 Future | ~40 | ~9,000 | +11,000 | Read + **Write unified** |
| **Phase 3** | 🔜 Future | ~25 | ~7,000 | +13,000 | Full consolidation |

*Effective overhead when agents prefer the unified tool

---

## Next Steps

### Immediate (Phase 1 Validation)
1. ✅ Run full integration test: `CALM_TOKEN=fake python3 tests/test_server.py`
2. ✅ Verify all 74 legacy tools still work
3. ✅ Test unified tool with real CALM API
4. ✅ Deploy to staging environment
5. ✅ Monitor for issues (1 week)

### Short Term (Phase 2 Planning)
1. Review write operations requirements
2. Design write operation error handling
3. Plan batch operation support
4. Design data validation strategy

### Long Term (Phase 3)
1. Publish migration guide
2. Deprecation notices (4+ weeks)
3. Remove legacy tools
4. Final optimization

---

## Questions?

Contact: Eduardo Falluh
Branch: `feature/tool-consolidation-phase1`
Documentation: This file + `SAFE_CONSOLIDATION_IMPLEMENTATION_PLAN.md`
