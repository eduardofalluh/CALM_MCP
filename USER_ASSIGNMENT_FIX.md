# Fix: "Former Member" Issue When Assigning Tasks

## Problem

When creating or updating tasks via the CALM API with `assignee_id` set to an email address (e.g., `eduardo.falluh@syntax.com`), CALM sometimes displays "Former Member" instead of the user's actual name in the UI.

## Root Cause

The CALM API expects the **user's internal ID** (not their email address) as the `assignee_id`. When an email is passed directly, the API's email→user resolution may fail or map to an incorrect/inactive user record, resulting in "Former Member" being displayed.

## Solution

Use the new `get_calm_project_users` tool to **lookup the correct user ID first**, then pass that ID to `create_calm_task` or `update_calm_task`.

### Step-by-Step Workflow

#### 1. Get Project Users
```python
# Call the new tool to get all project team members
users = get_calm_project_users(project_id="P001")

# Example response:
# [
#   {
#     "ID": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
#     "Email": "eduardo.falluh@syntax.com",
#     "Name": "Eduardo Falluh",
#     "Role": "Project Manager",
#     "Active": True
#   },
#   {
#     "ID": "f9e8d7c6-b5a4-3210-9876-543210fedcba",
#     "Email": "jane.doe@syntax.com",
#     "Name": "Jane Doe",
#     "Role": "Developer",
#     "Active": True
#   }
# ]
```

#### 2. Find the User You Want
```python
# Search by email
target_user = next(
    (u for u in users if u["Email"] == "eduardo.falluh@syntax.com"),
    None
)

# Extract the ID field (NOT the email!)
assignee_id = target_user["ID"]  # e.g., "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

#### 3. Create/Update Task with Correct ID
```python
# ✅ CORRECT: Use the ID from get_calm_project_users
create_calm_task(
    project_id="P001",
    title="Test Invoice Generation",
    task_type="User Story",
    assignee_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"  # The ID field, NOT email
)

# ❌ WRONG: Don't pass email directly
create_calm_task(
    project_id="P001",
    title="Test Invoice Generation",
    task_type="User Story",
    assignee_id="eduardo.falluh@syntax.com"  # This may show "Former Member"
)
```

## For GenAI Agents

When a user asks to assign a task to someone by name or email, follow this pattern:

1. Call `get_calm_project_users` with the project_id
2. Search the returned list for the user (by Email or Name)
3. Extract the `ID` field from the matching user
4. Use that `ID` as the `assignee_id` parameter

### Example Agent Workflow

**User request:** "Create a user story for invoice generation and assign it to eduardo.falluh@syntax.com"

**Agent actions:**
```python
# Step 1: Get users
users = get_calm_project_users(project_id="P001")

# Step 2: Find Eduardo
eduardo = next(u for u in users if u["Email"] == "eduardo.falluh@syntax.com")

# Step 3: Create task with correct ID
result = create_calm_task(
    project_id="P001",
    title="Invoice Generation User Story",
    task_type="User Story",
    assignee_id=eduardo["ID"]  # Use ID, not email
)
```

**Result:** The task now shows "Eduardo Falluh" (not "Former Member") in the CALM UI.

## Active vs Inactive Users

The `get_calm_project_users` response includes an `Active` field:
- `Active: True` - Current team member (preferred)
- `Active: False` - Former member (usually shows as "Former Member" in UI)

When searching for a user, prefer active users:
```python
# Find active user by email
target = next(
    (u for u in users if u["Email"] == email and u["Active"]),
    None
)
```

## Testing

The fix is verified by Test 50 in `tests/test_server.py`:
```bash
python3 tests/test_server.py
# Test 50: get_calm_project_users returns assignable IDs
# ✅ All checks passed
```

## Deployment

This fix is available starting from commit `[COMMIT_HASH]`:
- New tool: `get_calm_project_users`
- New client function: `get_project_users`
- 71 tools now available (was 70)
- All 234 test checks passing
