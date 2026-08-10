# Task Relations & Dependencies Guide

## Overview

SAP Cloud ALM supports **task-to-task relations** for creating dependencies, blockers, and other connections between tasks. This enables workflow management and dependency tracking.

---

## ✅ Available Tool

**`create_calm_task_relation(task_id, relation_task_id, relation_type="0")`**

Creates a directional relationship from one task to another.

---

## 🔗 Relation Types

SAP Cloud ALM typically supports these relation type codes:

| Code | Relation Type | Description | Example Use Case |
|------|--------------|-------------|------------------|
| **"0"** | **Related To** | Generic association between tasks | "These two tasks are related" |
| **"1"** | **Depends On** | Source task depends on target task | "Task A cannot start until Task B is done" |
| **"2"** | **Blocks** | Source task blocks target task | "Task A blocks Task B from proceeding" |
| **"3"** | **Predecessor/Successor** | Sequential workflow ordering | "Task A must complete before Task B" |
| **"4"** | **Parent/Child** | Hierarchical relationship (alternative to parent_id) | "Task A is a subtask of Task B" |

**⚠️ Important:** The exact relation type codes may vary by your CALM tenant configuration. Check your CALM UI to see what's available.

---

## 📋 How to Find Your Tenant's Relation Types

### Method 1: Check CALM UI
1. Open any task in CALM
2. Look for "Relations" section
3. Click "Add Relation"
4. The dropdown shows available relation types
5. Map the displayed names to numeric codes (usually 0, 1, 2, etc.)

### Method 2: Test with MCP
Create test relations with different codes and observe the result in CALM UI:

```python
# Test relation type "1"
create_calm_task_relation(
    task_id="TEST-001",
    relation_task_id="TEST-002",
    relation_type="1"
)
# Check CALM UI to see what type it created
```

---

## 💡 Common Use Cases

### Use Case 1: Create Dependency Chain

**Scenario:** Task T-002 cannot start until Task T-001 is completed.

```python
create_calm_task_relation(
    task_id="T-002",           # Dependent task
    relation_task_id="T-001",  # Must complete first
    relation_type="1"          # "depends on"
)
```

**Result in CALM:**
- T-002 shows: "Depends on T-001"
- T-001 shows: "T-002 depends on this"

---

### Use Case 2: Block a Task

**Scenario:** Task T-003 (bug) blocks Task T-004 (feature deployment).

```python
create_calm_task_relation(
    task_id="T-003",           # The blocker (bug)
    relation_task_id="T-004",  # What gets blocked (deployment)
    relation_type="2"          # "blocks"
)
```

**Result in CALM:**
- T-003 shows: "Blocks T-004"
- T-004 shows: "Blocked by T-003"
- T-004 may have visual warning/status indicator

---

### Use Case 3: Multi-Task Dependency Tree

**Scenario:** Create a complex dependency chain for a feature rollout.

```
Integration Test (T-005)
  ↑ depends on
Unit Tests (T-004)
  ↑ depends on
Code Implementation (T-003)
  ↑ depends on
Design Document (T-002)
  ↑ depends on
Requirements (T-001)
```

**Implementation:**

```python
# T-002 depends on T-001
create_calm_task_relation(
    task_id="T-002",
    relation_task_id="T-001",
    relation_type="1"
)

# T-003 depends on T-002
create_calm_task_relation(
    task_id="T-003",
    relation_task_id="T-002",
    relation_type="1"
)

# T-004 depends on T-003
create_calm_task_relation(
    task_id="T-004",
    relation_task_id="T-003",
    relation_type="1"
)

# T-005 depends on T-004
create_calm_task_relation(
    task_id="T-005",
    relation_task_id="T-004",
    relation_type="1"
)
```

**Result:** CALM enforces the workflow order and shows dependency chains.

---

### Use Case 4: Cross-Team Dependencies

**Scenario:** Backend team's task depends on Frontend team's API definition.

```python
# Backend task depends on Frontend API spec
create_calm_task_relation(
    task_id="BACK-023",        # Backend implementation
    relation_task_id="FRONT-015",  # API spec definition
    relation_type="1"
)
```

**Result:** Backend team sees they're waiting on Frontend; Frontend team sees their work is blocking Backend.

---

## 🗑️ Remove a Relation

Use `delete_calm_task_relation(relation_id)` with the relation ID returned from creation:

```python
# Create relation and save the ID
result = create_calm_task_relation(
    task_id="T-001",
    relation_task_id="T-002",
    relation_type="1"
)
relation_id = result.get("id")  # Save this

# Later, remove the relation
delete_calm_task_relation(relation_id)
```

---

## 🤖 What the Agent Can Do

### Example 1: Automatic Dependency Detection

**User prompt:**
> "Create 5 tasks for the user authentication feature: requirements, design, implementation, testing, deployment. Set them up with dependencies in the correct order."

**Agent executes:**

```
✅ create_calm_task("Requirements Analysis", type="Project Task")
   → T-001

✅ create_calm_task("Technical Design", type="Project Task")
   → T-002

✅ create_calm_task("Code Implementation", type="Project Task")
   → T-003

✅ create_calm_task("QA Testing", type="Project Task")
   → T-004

✅ create_calm_task("Production Deployment", type="Project Task")
   → T-005

✅ Create dependency chain:
   → T-002 depends on T-001
   → T-003 depends on T-002
   → T-004 depends on T-003
   → T-005 depends on T-004

Result: Complete workflow with enforced order
```

---

### Example 2: Blocker Management

**User prompt:**
> "There's a critical bug in task BUG-042. Find all tasks related to the payment module and mark them as blocked by this bug."

**Agent executes:**

```
✅ get_calm_tasks(project_id="P-001", task_type="Project Task")
   → Found 47 tasks

🔍 Filter to payment module (title contains "payment", "invoice", "billing"):
   → Found 8 payment-related tasks

✅ Create blocker relations:
   → create_calm_task_relation(BUG-042, PAY-015, relation_type="2")
   → create_calm_task_relation(BUG-042, PAY-019, relation_type="2")
   → create_calm_task_relation(BUG-042, PAY-023, relation_type="2")
   ... (8 relations created)

Result: All payment tasks now show "Blocked by BUG-042" in CALM
```

---

### Example 3: Dependency Validation

**User prompt:**
> "Check if task DEP-001 has any circular dependencies and show me the dependency chain."

**Agent executes:**

```
✅ get_calm_tasks(project_id="P-001")
   → Found all tasks

🔍 Build dependency graph:
   DEP-001 depends on DEP-002
   DEP-002 depends on DEP-003
   DEP-003 depends on DEP-001  ⚠️ CIRCULAR!

❌ Circular Dependency Detected:
   DEP-001 → DEP-002 → DEP-003 → DEP-001 (back to start)

💡 Recommendation:
   Break the cycle by removing one relation:
   - Option 1: Remove DEP-003 → DEP-001
   - Option 2: Remove DEP-001 → DEP-002
   - Option 3: Restructure to parallel execution
```

---

## 🎯 Summary

| Feature | Status | Tool |
|---------|--------|------|
| Create task relation/dependency | ✅ Supported | `create_calm_task_relation` |
| Delete task relation | ✅ Supported | `delete_calm_task_relation` |
| Multiple relation types | ✅ Supported | Use `relation_type` parameter |
| Dependency chains | ✅ Supported | Create multiple relations |
| Cross-team dependencies | ✅ Supported | Link tasks across projects |
| Blocker management | ✅ Supported | Use relation_type="2" |
| Parent/child hierarchy | ✅ Supported | Use `parent_id` OR relation_type="4" |

---

## 📞 Need Help?

1. **Check your CALM UI** for available relation types
2. **Test with small examples** first
3. **Contact SAP support** for tenant-specific relation type codes
4. **Refer to SAP Cloud ALM documentation** for your version

---

**Yes, dependencies and task relations are fully supported!** 🎉
