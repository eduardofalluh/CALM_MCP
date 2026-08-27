# CALM MCP Agent Instructions

## Critical: User Email Tracking (MANDATORY)

**YOU MUST ALWAYS pass the acting_user_email parameter on EVERY write operation.**

This is NOT optional. Every create/update tool call MUST include it.

### How to Get the User's Email

The user's email is in the GenAI Studio session context. You can:
1. Ask the user: "What is your email address?"
2. Extract from their profile if available
3. Use the email they mention when they say "assign to me" (means them)

### Apply to ALL Write Tools

```python
# Tasks
create_calm_task(..., acting_user_email="eduardo.falluh@syntax.com")
update_calm_task(..., acting_user_email="eduardo.falluh@syntax.com")

# Requirements  
create_calm_requirement(..., acting_user_email="eduardo.falluh@syntax.com")
update_calm_requirement(..., acting_user_email="eduardo.falluh@syntax.com")

# Test Cases
create_calm_test_case(..., acting_user_email="eduardo.falluh@syntax.com")

# Projects
create_calm_project(..., acting_user_email="eduardo.falluh@syntax.com")

# ALL write operations - ALWAYS include acting_user_email!
```

### Why This Matters

Without it, CALM audit logs show "API" instead of the actual user's name.
With it, CALM logs show "Eduardo Falluh" or "eduardo.falluh@syntax.com".

This is critical for compliance, audit trails, and user tracking.

**If you don't know the user's email, ASK THEM before creating anything.**

## Critical: Assignee/Responsible Assignment

**DO NOT BLOCK writes when get_calm_project_users fails with 403.**

### The Rule

When assigning a task to someone (create_calm_task or update_calm_task with assignee_id):

1. **Try to look up the user ID** with `get_calm_project_users(project_id)`
   - If it returns users: extract the ID and use it ✅
   
2. **If get_calm_project_users fails with 403:**
   - **PROCEED ANYWAY** - use the email address directly as assignee_id
   - CALM API will resolve the email to the correct user
   - Do NOT refuse the write
   - Do NOT tell the user it "might show Former Member"
   - Just do it ✅

### Example

User says: "Assign task 3-57344 to eduardo.falluh@syntax.com"

```python
# Try lookup first
try:
    users = get_calm_project_users("9dd45151-4393-4b06-9998-208ef3cd66c6")
    eduardo = next(u for u in users if "eduardo.falluh" in u["Email"].lower())
    assignee = eduardo["ID"]
except:
    # 403 or not found? Use email directly - it will work
    assignee = "eduardo.falluh@syntax.com"

# Always proceed with the write
update_calm_task(
    task_id="3-57344",
    assignee_id=assignee
)
```

### Why This Works

CALM's API accepts emails in the assignee_id field and resolves them internally. The 403 on user lookup is a permission issue on the read endpoint, but the write endpoint still works fine with emails.

**Bottom line: If the user wants someone assigned, assign them. Don't block on a 403.**
