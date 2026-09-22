# Changelog - Timeboxes and Teams Read Functions (2026-07-28)

## Summary

Added read operations for **Timeboxes** and **Teams** entities that were previously only available through write operations (timebox) or not available at all (teams).

## New Read Tools Added

### 1. `get_calm_timeboxes(project_id)`
Returns all timeboxes (sprints, iterations, releases) for a given project.

**Returns:**
```json
[
  {
    "ID": "TB1",
    "Project ID": "P001",
    "Name": "Sprint 1",
    "Type": 0,
    "StartDate": "2026-07-01",
    "EndDate": "2026-07-14",
    "Closed": false
  }
]
```

**Use Case:** List all timeboxes to see project planning periods, check which are open/closed, find date ranges.

### 2. `get_calm_teams()`
Returns all teams visible to the authenticated tenant.

**Returns:**
```json
[
  {
    "ID": "TEAM1",
    "Name": "Development Team",
    "Description": "Backend developers",
    "Project ID": "P001"
  }
]
```

**Use Case:** List available teams for assignment, discover team structures, find teams by project.

## Changes Made

### Core Implementation
- **File**: `src/calm/client.py`
  - Added `get_timeboxes(project_id, token, base_url)` function
  - Added `get_teams(token, base_url)` function
  - Both follow existing patterns for list endpoints

### Tool Wrappers
- **New File**: `src/calm/tools/timeboxes.py`
  - Registered `get_calm_timeboxes` MCP tool
  - Requires `project_id` parameter
  
- **New File**: `src/calm/tools/teams.py`
  - Registered `get_calm_teams` MCP tool
  - No parameters (returns all teams)

### Server Registration
- **File**: `server.py`
  - Imported `timeboxes` and `teams` modules
  - Registered both tools with FastMCP

### Testing
- **File**: `tests/test_server.py`
  - Added Test 40: `get_calm_timeboxes` validation
  - Added Test 41: `get_calm_teams` validation
  - Updated expected tool count from 7 to 9 read tools
  - All 41 tests pass ✅

### Documentation
- **File**: `README.md`
  - Added both new tools to tools table
  - Updated project layout to show new tool files
  - Updated tool count references

## API Endpoints Used

| Tool | Endpoint |
|------|----------|
| `get_calm_timeboxes` | `GET /api/calm-projects/v1/projects/{project_id}/timeboxes` |
| `get_calm_teams` | `GET /api/calm-projects/v1/teams` |

## Complete Read-Only Tool Set

The MCP server now exposes **10 read-only tools** (up from 8):

1. ✅ `get_calm_projects`
2. ✅ `get_calm_tasks`
3. ✅ `get_calm_requirements`
4. ✅ `get_calm_business_processes`
5. ✅ `get_calm_solution_processes`
6. ✅ `get_calm_scopes`
7. ✅ `get_calm_test_cases`
8. ✅ `get_calm_timeboxes` ← NEW
9. ✅ `get_calm_teams` ← NEW
10. ✅ `calm_health`

## Backward Compatibility

✅ **Fully backward compatible**
- All existing tools remain unchanged
- New tools are purely additive
- No breaking changes to existing API contracts

## Deployment

Will be pushed to all repositories:
- GitHub `main` branch
- GitHub `final-read-only-mcp-server` branch
- GitLab `main` branch

## Testing Recommendations

When deploying to production:

1. **Test Timeboxes:**
   ```python
   timeboxes = get_calm_timeboxes(project_id="your-project-id")
   assert len(timeboxes) > 0
   assert "Name" in timeboxes[0]
   assert "Closed" in timeboxes[0]
   ```

2. **Test Teams:**
   ```python
   teams = get_calm_teams()
   assert len(teams) > 0
   assert "Name" in teams[0]
   assert "Description" in teams[0]
   ```

## Notes

- **Timebox**: Previously only write operations (`create_calm_timebox`, `update_calm_timebox`, `delete_calm_timebox`) existed. Now read is available.
- **Team**: Completely new - no previous read or write operations existed.
- Both follow the established patterns for CALM API integration.

---

**Author**: Eduardo Falluh  
**Date**: 2026-07-28  
**Test Results**: 41/41 tests passing
