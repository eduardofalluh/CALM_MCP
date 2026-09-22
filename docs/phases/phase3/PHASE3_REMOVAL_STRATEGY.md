# Phase 3C: Tool Removal Strategy - SAFE REMOVAL ONLY

## Critical Analysis: What Can Be Safely Removed?

### Tools COVERED by calm_resource() - SAFE TO REMOVE

These basic CRUD tools are fully covered by `calm_resource()`:

#### Read Tools (can remove - covered by unified):
1. ✅ `get_calm_projects` → `calm_resource(resource="projects", operation="list")`
2. ✅ `get_calm_tasks` → `calm_resource(resource="tasks", operation="list", project_id=...)`
3. ✅ `get_calm_requirements` → `calm_resource(resource="requirements", operation="list", project_id=...)`
4. ✅ `get_calm_teams` → `calm_resource(resource="teams", operation="list")`
5. ✅ `get_calm_business_processes` → `calm_resource(resource="business_processes", operation="list")`
6. ✅ `get_calm_solution_processes` → `calm_resource(resource="solution_processes", operation="list")`
7. ✅ `get_calm_processes` → `calm_resource(resource="processes", operation="list")`
8. ✅ `get_calm_timeboxes` → `calm_resource(resource="timeboxes", operation="list", project_id=...)`
9. ✅ `get_calm_scopes` → `calm_resource(resource="scopes", operation="list")`
10. ✅ `get_calm_test_cases` → `calm_resource(resource="test_cases", operation="list")`
11. ✅ `get_calm_tags` → `calm_resource(resource="tags", operation="list", project_id=...)`
12. ✅ `get_calm_features` → `calm_resource(resource="features", operation="list", project_id=...)`
13. ✅ `get_calm_test_plans` → `calm_resource(resource="test_plans", operation="list", project_id=...)`
14. ✅ `get_calm_project_users` → `calm_resource(resource="project_users", operation="list", project_id=...)`
15. ✅ `get_calm_project_customization` → `calm_resource(resource="customization", operation="get", project_id=...)`

#### Write Tools (can remove - covered by unified):
1. ✅ `create_calm_project` → `calm_resource(resource="projects", operation="create", data=...)`
2. ✅ `update_calm_project` → `calm_resource(resource="projects", operation="update", resource_id=..., data=...)`
3. ✅ `create_calm_task` → `calm_resource(resource="tasks", operation="create", project_id=..., data=...)`
4. ✅ `update_calm_task` → `calm_resource(resource="tasks", operation="update", project_id=..., resource_id=..., data=...)`
5. ✅ `delete_calm_task` → `calm_resource(resource="tasks", operation="delete", project_id=..., resource_id=...)`
6. ✅ `create_calm_requirement` → `calm_resource(resource="requirements", operation="create", project_id=..., data=...)`
7. ✅ `update_calm_requirement` → `calm_resource(resource="requirements", operation="update", project_id=..., resource_id=..., data=...)`
8. ✅ `delete_calm_requirement` → `calm_resource(resource="requirements", operation="delete", project_id=..., resource_id=...)`
9. ✅ `create_calm_scope` → `calm_resource(resource="scopes", operation="create", data=...)`
10. ✅ `update_calm_scope` → `calm_resource(resource="scopes", operation="update", resource_id=..., data=...)`
11. ✅ `delete_calm_scope` → `calm_resource(resource="scopes", operation="delete", resource_id=...)`
12. ✅ `create_calm_test_case` → `calm_resource(resource="test_cases", operation="create", data=...)`
13. ✅ `update_calm_test_case` → `calm_resource(resource="test_cases", operation="update", resource_id=..., data=...)`
14. ✅ `delete_calm_test_case` → `calm_resource(resource="test_cases", operation="delete", resource_id=...)`
15. ✅ `create_calm_timebox` → `calm_resource(resource="timeboxes", operation="create", data=...)`
16. ✅ `update_calm_timebox` → `calm_resource(resource="timeboxes", operation="update", resource_id=..., data=...)`
17. ✅ `delete_calm_timebox` → `calm_resource(resource="timeboxes", operation="delete", resource_id=...)`
18. ✅ `create_calm_business_process` → `calm_resource(resource="business_processes", operation="create", data=...)`
19. ✅ `update_calm_business_process` → `calm_resource(resource="business_processes", operation="update", resource_id=..., data=...)`
20. ✅ `delete_calm_business_process` → `calm_resource(resource="business_processes", operation="delete", resource_id=...)`
21. ✅ `create_calm_solution_process` → `calm_resource(resource="solution_processes", operation="create", data=...)`
22. ✅ `update_calm_solution_process` → `calm_resource(resource="solution_processes", operation="update", resource_id=..., data=...)`
23. ✅ `delete_calm_solution_process` → `calm_resource(resource="solution_processes", operation="delete", resource_id=...)`
24. ✅ `create_calm_tag` → `calm_resource(resource="tags", operation="create", data=...)`
25. ✅ `create_calm_feature` → `calm_resource(resource="features", operation="create", data=...)`
26. ✅ `create_calm_test_plan` → `calm_resource(resource="test_plans", operation="create", data=...)`

**Total to Remove: 41 tools (15 read + 26 write)**

### Tools NOT COVERED by calm_resource() - MUST KEEP

These specialized tools provide functionality NOT in unified tool:

#### Helper/Utility Tools (KEEP):
1. ❌ `calm_health` - Health check endpoint
2. ❌ `get_calm_oauth_endpoints` - OAuth discovery
3. ❌ `get_calm_oauth_metadata` - OAuth configuration
4. ❌ `get_calm_authorization_server_metadata` - OAuth server info
5. ❌ `get_my_calm_user_uuid_instructions` - User UUID helper

#### Advanced Write Operations (KEEP):
6. ❌ `calm_api_write` - Generic POST/PATCH escape hatch
7. ❌ `calm_api_delete` - Generic DELETE escape hatch

#### BTP Test Management (Separate System - KEEP ALL):
8. ❌ `tm_health` - TM health check
9. ❌ `get_tm_statistics` - TM statistics
10. ❌ `get_tm_test_cases` - TM test cases
11. ❌ `get_tm_test_case_full` - TM single test case
12. ❌ `get_tm_requirements` - TM requirements
13. ❌ `create_tm_test_case` - TM create
14. ❌ `update_tm_test_case` - TM update
15. ❌ `delete_tm_test_case` - TM delete
16. ❌ `create_tm_requirement` - TM requirement
17. ❌ `delete_tm_requirement` - TM delete requirement
18. ❌ `tm_odata_read` - TM generic read
19. ❌ `tm_odata_write` - TM generic write
20. ❌ `tm_odata_delete` - TM generic delete

**Total to Keep: ~20 specialized tools**

### Module Removal Plan

Can remove these entire module registrations from server.py:

1. ✅ `projects.register(mcp)` - Basic project read (get_calm_projects)
2. ✅ `processes.register(mcp)` - Basic process reads
3. ✅ `scopes.register(mcp)` - Basic scope read
4. ✅ `test_cases.register(mcp)` - Basic test case read
5. ✅ `timeboxes.register(mcp)` - Basic timebox read
6. ✅ `teams.register(mcp)` - Basic team read
7. ✅ `tags.register(mcp)` - Basic tag read
8. ✅ `features.register(mcp)` - Basic feature read
9. ✅ `test_plans.register(mcp)` - Basic test plan read
10. ✅ `customization.register(mcp)` - Basic customization read
11. ✅ `users.register(mcp)` - Basic project users read
12. ✅ `tasks_write.register(mcp)` - Task CRUD
13. ✅ `projects_write.register(mcp)` - Project CU
14. ✅ `processes_write.register(mcp)` - Process CUD
15. ✅ `scopes_write.register(mcp)` - Scope CUD
16. ✅ `test_cases_write.register(mcp)` - Test case CUD

Keep these module registrations:

1. ❌ `unified.register(mcp)` - THE UNIFIED TOOL
2. ❌ `health.register(mcp)` - Health checks
3. ❌ `oauth_info.register(mcp)` - OAuth discovery
4. ❌ `user_uuid_helper.register(mcp)` - User helpers
5. ❌ `advanced_write.register(mcp)` - Generic escape hatches
6. ❌ `test_repo.register(mcp)` - TM reads
7. ❌ `test_repo_write.register(mcp)` - TM writes

## Implementation Steps

1. ✅ Update server.py to remove 16 module registrations
2. ✅ Keep the module files (don't delete them - for rollback)
3. ✅ Run comprehensive tests
4. ✅ Verify unified tool covers all removed functionality
5. ✅ Document what was removed

## Expected Result

**Before**: 75 tools (74 legacy + 1 unified)  
**After**: ~28 tools (1 unified + ~20 specialized + ~7 TM)  
**Reduction**: 47 tools removed (62.7%)

## Safety Checklist

- ✅ Only removing tools with unified equivalents
- ✅ Keeping all specialized/advanced tools
- ✅ Module files remain (easy rollback)
- ✅ Tests will validate nothing breaks
- ✅ Unified tool tested in Phase 1 & 2

## Rollback Plan

If issues discovered:
1. Restore removed registrations in server.py
2. Restart server
3. All tools back immediately
