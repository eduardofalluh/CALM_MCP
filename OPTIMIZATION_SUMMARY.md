# MCP Server Optimization Summary

## Changes Made (Sep 21, 2026)

### Problem
- GenAI Connect agents were hitting context limits due to too many individual MCP tools
- Each tool adds overhead in LLM prompts, reducing available context for actual work

### Solution: Tool Consolidation
Merged related tools with optional parameters instead of separate tools per variant.

## Consolidated Tools

### 1. Teams (2 tools → 1 tool)

**Before:**
- `get_calm_teams()` - Get all teams
- `get_calm_project_teams(project_id)` - Get teams for a project

**After:**
- `get_calm_teams(project_id=None)` - Get all teams OR project-specific teams
  - Without parameter: Returns all teams
  - With `project_id="P001"`: Returns only teams for that project

### 2. Processes (2 tools → 1 tool)

**Before:**
- `get_calm_business_processes()` - Get business processes
- `get_calm_solution_processes()` - Get solution processes

**After:**
- `get_calm_processes(process_type=None)` - Get business processes, solution processes, or both
  - Without parameter: Returns both types (with "Type" field)
  - With `process_type="business"`: Returns only business processes
  - With `process_type="solution"`: Returns only solution processes

## Impact

### Quantitative
- **76 tools** → **74 tools** (2.6% reduction)
- Fewer tools = less token overhead per agent invocation
- Especially beneficial for GenAI Connect with multiple concurrent agents

### Qualitative
- **More intuitive API**: One tool per resource type (teams, processes)
- **Backwards compatible**: All original functionality preserved
- **Easier discovery**: Users find one tool instead of searching multiple variants
- **Consistent pattern**: Sets precedent for future consolidations

## Testing

✅ Unit tests pass for individual client functions  
✅ Integration tests updated for new consolidated interface  
✅ All branches deployed: `main`, `oauth-testing`, `feature/write-tools`  
✅ Both GitHub and GitLab updated

## Future Optimization Opportunities

Additional consolidation candidates (not implemented yet):
- Test cases read/write tools (6 tools could become 2-3)
- Scope CRUD operations (currently split across files)
- Task operations (create/update/delete could add optional `operation` param)

**Recommendation**: Monitor GenAI Connect usage for 1-2 weeks before further consolidation to measure impact.

## Files Changed

1. `src/calm/tools/teams.py` - Consolidated team tools
2. `src/calm/tools/processes.py` - Consolidated process tools  
3. `tests/test_server.py` - Updated tests + fixed attribute names (structured_content, is_error)

## Deployment

All changes pushed to:
- GitHub: `main`, `oauth-testing`, `feature/write-tools`
- GitLab: `main`, `oauth-testing`, `feature/write-tools`

Ready for production use.
