# Changelog - Effort Field Addition (2026-07-28)

## Summary

Added the **Effort** field to all task/requirement read operations in the SAP Cloud ALM MCP server. This field captures task effort estimates (e.g., "8 Hours") as displayed in the SAP Cloud ALM UI.

## Changes Made

### 1. Core Implementation
- **File**: `src/calm/client.py`
- **Function**: `_format_task()`
- **Change**: Added `"Effort": item.get("effort")` to the returned dictionary
- **Impact**: All task reads (`get_calm_tasks`, `get_calm_requirements`) now include the Effort field

### 2. Documentation Updates
- **File**: `src/calm/tools/projects.py`
  - Updated `get_calm_tasks` docstring to list Effort as a returned field
  - Added description: "Effort estimate (e.g., '8 Hours', may be null if not set)"

- **File**: `README.md`
  - Updated tools table to indicate Effort field is included in task responses

### 3. Testing
- All 39 existing unit tests pass with the new field
- Created `test_effort_field.py` to verify:
  - Effort is correctly returned when present in API response
  - Effort returns `None` when not set on a task
  - Both test cases pass ✅

### 4. Additional Documentation (Write Operations)
As part of this release, comprehensive write operations documentation was added:

- **ENABLING_WRITE_OPERATIONS.md**: Complete guide for enabling the 38 write tools
- **QUICK_START_WRITE_OPS.md**: Quick reference card for CALM owners
- **.env.example**: Enhanced with clear write guard explanation
- **README.md**: Added prominent write operations section with links

## API Field Mapping

The CALM Tasks API returns an `effort` field in task objects. This is now mapped to the `Effort` field in our formatted response:

```json
{
  "ID": "TASK-123",
  "Title": "Create Functional Spec for Enhancement SD-E-025",
  "Type": "Project Task",
  "Status": "Open",
  "Effort": "8 Hours",  // <-- NEW FIELD
  "StartDate": "2026-07-01",
  "DueDate": "2026-07-31",
  "AssigneeName": "John Doe"
}
```

## Backward Compatibility

✅ **Fully backward compatible**
- Existing integrations will see a new `Effort` field in responses
- When effort is not set, the field returns `None` (not an error)
- All existing fields remain unchanged
- No breaking changes to API contracts

## Deployment

Pushed to all repositories:
- ✅ GitHub `main` branch
- ✅ GitHub `final-read-only-mcp-server` branch
- ✅ GitLab `main` branch

Commit hash: `b400f68`

## Testing Recommendations

When deploying to production:

1. Verify Effort field appears in task responses:
   ```python
   tasks = get_calm_tasks(project_id="your-project-id")
   assert "Effort" in tasks[0]  # Field should exist
   ```

2. Test both cases:
   - Tasks with effort set (should return a value like "8 Hours")
   - Tasks without effort set (should return `None`)

3. Verify existing integrations still work (new field should not break parsing)

## Related Issues

This addresses the requirement to expose task effort estimates that are visible in the SAP Cloud ALM UI but were previously not returned by the MCP read tools.

---

**Author**: Eduardo Falluh  
**Date**: 2026-07-28  
**Commit**: b400f68
