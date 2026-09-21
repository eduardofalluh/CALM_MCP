# Aggressive MCP Tool Consolidation Proposal

## Current State: 74 Tools

## Proposed Structure: ~25 Tools (66% reduction)

### Consolidation Strategy

Group by **resource type** with **operation parameter** instead of separate tools per action.

---

## Proposed Consolidated Tools

### 1. Core Resources (8 tools)

| New Tool | Replaces | Operations | Count |
|----------|----------|------------|-------|
| `calm_projects(op, data)` | get_calm_projects, create_calm_project, update_calm_project | get, create, update | 3→1 |
| `calm_tasks(op, data)` | get_calm_tasks, get_calm_requirements, create_calm_task, update_calm_task, delete_calm_task, create_calm_requirement, update_calm_requirement, delete_calm_requirement | get, create, update, delete (+ filter by type) | 8→1 |
| `calm_task_relations(op, data)` | create_calm_task_relation, delete_calm_task_relation, set_calm_task_tags | create, delete, set_tags | 3→1 |
| `calm_task_comments(op, data)` | create_calm_task_comment, update_calm_task_comment, delete_calm_task_comment | create, update, delete | 3→1 |
| `calm_test_cases(op, data)` | get_calm_test_cases, create_calm_test_case, update_calm_test_case, delete_calm_test_case | get, create, update, delete | 4→1 |
| `calm_test_activities(op, data)` | update_calm_test_activity, delete_calm_test_activity, create_calm_test_action, update_calm_test_action, delete_calm_test_action | All activity/action CRUD | 5→1 |
| `calm_processes(op, type, data)` | ALREADY DONE - get/create/update/delete business & solution processes | get, create, update, delete | 6→1 ✅ |
| `calm_scopes(op, data)` | get_calm_scopes, create_calm_scope, update_calm_scope, delete_calm_scope, assign_calm_scenario_versions, update_calm_scope_assignments | get, create, update, delete, assign | 6→1 |

### 2. Supporting Resources (5 tools)

| New Tool | Replaces | Operations |
|----------|----------|------------|
| `calm_teams(proj_id)` | ALREADY DONE | get (with optional filter) ✅ |
| `calm_users(project_id)` | get_calm_project_users, get_my_calm_user_uuid_instructions | get, get_uuid_help | 2→1 |
| `calm_timeboxes(op, data)` | get_calm_timeboxes, create_calm_timebox, update_calm_timebox, delete_calm_timebox | get, create, update, delete | 4→1 |
| `calm_tags(op, data)` | get_calm_tags, create_calm_tag | get, create | 2→1 |
| `calm_features(op, data)` | get_calm_features, create_calm_feature | get, create | 2→1 |

### 3. Test Management (3 tools)

| New Tool | Replaces | Operations |
|----------|----------|------------|
| `calm_test_plans(op, data)` | get_calm_test_plans, create_calm_test_plan, assign_calm_test_case_to_plan, link_calm_test_case_to_requirement | get, create, assign, link | 4→1 |
| `tm_test_cases(op, data)` | get_tm_test_cases, get_tm_test_case_full, create_tm_test_case, update_tm_test_case, delete_tm_test_case | All TM test case ops | 5→1 |
| `tm_requirements(op, data)` | get_tm_requirements, create_tm_requirement, delete_tm_requirement | get, create, delete | 3→1 |

### 4. Utility Tools (6 tools - keep as-is)

- `calm_health()` - Health check
- `get_calm_project_customization()` - Metadata
- `calm_api_write()` - Generic escape hatch
- `calm_api_delete()` - Generic delete
- `tm_health()` - TM health check
- `tm_odata_read/write/delete()` - TM generic operations
- OAuth tools (3) - Keep separate

### 5. Statistics (1 tool)

- `get_tm_statistics()` - Keep as-is

---

## Implementation Example

### Before (3 separate tools):
```python
@mcp.tool()
def create_calm_task(...): ...

@mcp.tool()
def update_calm_task(...): ...

@mcp.tool()
def delete_calm_task(...): ...
```

### After (1 consolidated tool):
```python
@mcp.tool()
def calm_tasks(
    ctx: Context,
    operation: Literal["get", "create", "update", "delete"],
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    task_type: Optional[str] = None,
    # ... other params as needed
) -> Union[list[dict], dict]:
    """Manage CALM tasks - get, create, update, or delete.
    
    Operations:
    - get: List tasks (requires project_id, optional task_type filter)
    - create: Create new task (requires project_id, title, task_type, ...)
    - update: Modify existing task (requires task_id, ...)
    - delete: Remove task (requires task_id)
    """
    h = get_calm_headers(ctx)
    
    if operation == "get":
        return client.get_tasks(project_id, h.token, h.base_url, task_type)
    elif operation == "create":
        return client.create_task(h.token, project_id, ...)
    elif operation == "update":
        return client.update_task(h.token, task_id, ...)
    elif operation == "delete":
        return client.delete_task(h.token, task_id, h.base_url)
```

---

## Benefits

### Quantitative
- **74 tools → ~25 tools** (66% reduction)
- Massive context savings for LLM agents
- Fewer tools to scan/understand per invocation

### Qualitative
- **Intuitive**: "I want to work with tasks" → Use `calm_tasks()`
- **Discoverable**: One tool per resource type
- **Consistent**: Same pattern across all resources
- **Flexible**: Generic tools still available for edge cases

---

## Migration Path

### Phase 1: Read Operations (Low Risk)
Consolidate all GET operations first - no data modification risk.

### Phase 2: Write Operations (Medium Risk)  
Consolidate CREATE/UPDATE operations with extra validation.

### Phase 3: Delete Operations (High Risk)
Consolidate DELETE operations last - most destructive.

### Phase 4: Deprecation
Keep old tools for 1 version with deprecation warnings, then remove.

---

## Risk Mitigation

1. **Parameter Validation**: Strict validation per operation
2. **Error Messages**: Clear messages like "operation='create' requires project_id"
3. **Testing**: Comprehensive tests for each operation
4. **Documentation**: Clear examples for each operation
5. **Backwards Compat**: Keep old tools during migration period

---

## Next Steps

1. **Approve scope**: Which consolidations to prioritize?
2. **Implement Phase 1**: Start with read-only operations
3. **Test thoroughly**: Ensure nothing breaks
4. **Deploy incrementally**: One resource type at a time
5. **Monitor usage**: Track before/after metrics

**Estimated effort**: 4-6 hours for Phase 1 (read operations)

---

## Questions for You

1. Should we consolidate this aggressively, or is it too radical?
2. Priority order: Start with tasks (highest tool count) or projects (most common)?
3. Keep backwards compatibility, or breaking change acceptable?
