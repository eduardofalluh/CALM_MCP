#!/usr/bin/env python3
"""Quick test to verify the Effort field is included in task responses."""

from src.calm.client import _format_task

# Test with effort field present
task_with_effort = {
    "id": "TASK-123",
    "title": "Create Functional Spec",
    "type": "CALMTASK",
    "status": "CIPTKOPEN",
    "startDate": "2026-07-01",
    "dueDate": "2026-07-31",
    "assigneeName": "John Doe",
    "approvalState": "NO_APPR_REQ",
    "obsolete": False,
    "effort": "8 Hours",  # <-- The field we're testing
}

# Test with effort field absent (null/missing)
task_without_effort = {
    "id": "TASK-456",
    "title": "Another Task",
    "type": "CALMTASK",
    "status": "CIPTKINP",
}

print("Test 1: Task with Effort field")
result1 = _format_task(task_with_effort)
print(f"  Title: {result1['Title']}")
print(f"  Effort: {result1['Effort']}")
assert result1["Effort"] == "8 Hours", "Effort should be '8 Hours'"
print("  ✅ PASS: Effort field is correctly included\n")

print("Test 2: Task without Effort field (should be None)")
result2 = _format_task(task_without_effort)
print(f"  Title: {result2['Title']}")
print(f"  Effort: {result2['Effort']}")
assert result2["Effort"] is None, "Effort should be None when not present"
print("  ✅ PASS: Missing Effort field returns None\n")

print("=" * 60)
print("All effort field tests passed! ✅")
print("=" * 60)
print("\nThe Effort field is now included in all task responses.")
print("When a task has an effort estimate, it will be returned (e.g., '8 Hours').")
print("When a task has no effort set, the field will be None.")
