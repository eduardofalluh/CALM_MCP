# CALM MCP Agent Instructions

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
