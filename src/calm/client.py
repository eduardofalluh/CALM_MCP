"""
Cloud ALM HTTP client.

1:1 port of the standalone functions from the existing Syntax GenAI Studio agent.
Token is received from the caller (resolved by the dependency layer) — no
credentials are stored or fetched here.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import requests

from .config import build_base_url

REQUEST_TIMEOUT = 30  # seconds

# ---------------------------------------------------------------------------
# Mappings (taken verbatim from the existing agent)
# ---------------------------------------------------------------------------

TASK_STATUS_MAP = {
    "CIPTKOPEN": "Open", "CIPTKINP": "In Progress", "CIPTKBLK": "Blocked",
    "CIPTKCLOSE": "Done", "CIPTKNO": "Not Relevant",
    "CIPUSOPEN": "Open", "CIPUSINP": "In Progress", "CIPUSBLK": "Blocked",
    "CIPUSCLOSE": "Done", "CIPUSNO": "Not Relevant",
    "CIPREQUOPEN": "Open", "CIPREQUINP": "In Progress", "CIPREQUBLK": "Blocked",
    "CIPREQUCLOSE": "Done", "CIPREQUNO": "Not Relevant",
    "CIPDFCTOPEN": "Open", "CIPDFCTINP": "In Progress", "CIPDFCTBLK": "Blocked",
    "CIPDFCTDONE": "Done",
    "CIPQGOPEN": "Open", "CIPQGBLK": "Blocked", "CIPQGNR": "Not Relevant",
    "CIPQGDONE": "Done",
}

TASK_TYPE_MAP = {
    "CALMTMPL": "Roadmap Task",
    "CALMTASK": "Project Task",
    "CALMUS": "User Story",
    "CALMST": "Sub-task",
    "CALMREQU": "Requirement",
    "CALMDEF": "Defect",
    "CALMQGATE": "Quality Gate",
    "CALMCHKLI": "Checklist Item",
}

TASK_APPROVAL_STATE_MAP = {
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
    "READY_4_APPR": "Ready for Approval",
    "NO_APPR_REQ": "No Approval Required",
}

PROJECT_STATUS_MAP = {"O": "Active", "C": "Hidden"}

TESTCASE_PRIORITY_MAP = {
    "10": "Very High",
    "20": "High",
    "30": "Medium",
    "40": "Low",
}

# ---------------------------------------------------------------------------
# Reverse mappings for writes (human label -> CALM code)
#
# The CALM status code depends on the task *type* (CIPTK* for project tasks,
# CIPUS* for user stories, etc.), so status resolution is type-aware. Callers
# may also pass a raw CALM code directly, in which case it is used unchanged.
# ---------------------------------------------------------------------------

TASK_TYPE_REVERSE_MAP = {label.lower(): code for code, label in TASK_TYPE_MAP.items()}

# Human status label -> CALM code, grouped by task type code.
STATUS_CODE_BY_TYPE = {
    "CALMTASK": {"open": "CIPTKOPEN", "in progress": "CIPTKINP", "blocked": "CIPTKBLK",
                 "done": "CIPTKCLOSE", "not relevant": "CIPTKNO"},
    "CALMTMPL": {"open": "CIPTKOPEN", "in progress": "CIPTKINP", "blocked": "CIPTKBLK",
                 "done": "CIPTKCLOSE", "not relevant": "CIPTKNO"},
    "CALMUS": {"open": "CIPUSOPEN", "in progress": "CIPUSINP", "blocked": "CIPUSBLK",
               "done": "CIPUSCLOSE", "not relevant": "CIPUSNO"},
    "CALMST": {"open": "CIPUSOPEN", "in progress": "CIPUSINP", "blocked": "CIPUSBLK",
               "done": "CIPUSCLOSE", "not relevant": "CIPUSNO"},
    "CALMREQU": {"open": "CIPREQUOPEN", "in progress": "CIPREQUINP", "blocked": "CIPREQUBLK",
                 "done": "CIPREQUCLOSE", "not relevant": "CIPREQUNO"},
    "CALMDEF": {"open": "CIPDFCTOPEN", "in progress": "CIPDFCTINP", "blocked": "CIPDFCTBLK",
                "done": "CIPDFCTDONE"},
    "CALMQGATE": {"open": "CIPQGOPEN", "blocked": "CIPQGBLK", "not relevant": "CIPQGNR",
                  "done": "CIPQGDONE"},
}

# All known status codes, so a raw code passed by the caller is recognised.
_KNOWN_STATUS_CODES = set(TASK_STATUS_MAP)


def resolve_task_type_code(value: str) -> str:
    """Accept a human label ("User Story") or a raw code ("CALMUS") and return the code."""
    if value in TASK_TYPE_MAP:  # already a raw code
        return value
    code = TASK_TYPE_REVERSE_MAP.get(value.strip().lower())
    if not code:
        raise ValueError(
            f"Unknown task type '{value}'. Use one of: "
            f"{', '.join(sorted(TASK_TYPE_MAP.values()))} (or a raw CALM code)."
        )
    return code


def resolve_status_code(value: str, type_code: str) -> str:
    """Resolve a human status label to the type-specific CALM code.

    A raw CALM status code is accepted and returned unchanged.
    """
    if value in _KNOWN_STATUS_CODES:  # already a raw code
        return value
    by_type = STATUS_CODE_BY_TYPE.get(type_code, {})
    code = by_type.get(value.strip().lower())
    if not code:
        allowed = ", ".join(sorted(by_type)) or "(none for this type)"
        raise ValueError(
            f"Unknown status '{value}' for task type '{type_code}'. "
            f"Allowed labels: {allowed} (or a raw CALM code)."
        )
    return code


PROJECT_STATUS_REVERSE_MAP = {label.lower(): code for code, label in PROJECT_STATUS_MAP.items()}
TESTCASE_PRIORITY_REVERSE_MAP = {label.lower(): code for code, label in TESTCASE_PRIORITY_MAP.items()}


def resolve_project_status(value: str) -> str:
    """Accept "Active"/"Hidden" or a raw code ("O"/"C") and return the code."""
    if value in PROJECT_STATUS_MAP:  # already a raw code
        return value
    code = PROJECT_STATUS_REVERSE_MAP.get(value.strip().lower())
    if not code:
        raise ValueError(
            f"Unknown project status '{value}'. Use "
            f"{', '.join(sorted(PROJECT_STATUS_MAP.values()))} (or raw code O/C)."
        )
    return code


def resolve_testcase_priority(value: str) -> str:
    """Accept a label ("High") or a raw code ("20") and return the code string."""
    value = str(value)
    if value in TESTCASE_PRIORITY_MAP:  # already a raw code
        return value
    code = TESTCASE_PRIORITY_REVERSE_MAP.get(value.strip().lower())
    if not code:
        raise ValueError(
            f"Unknown test case priority '{value}'. Use "
            f"{', '.join(TESTCASE_PRIORITY_MAP.values())} (or raw code 10/20/30/40)."
        )
    return code


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _get(url: str, token: str) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    payload = json.dumps({"session_id": str(uuid.uuid4())})
    resp = requests.get(url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _write(method: str, url: str, token: str, body: dict) -> Any:
    """Send a JSON write request (POST/PATCH) and return the parsed response.

    Returns the parsed JSON body, or {} when the API responds with no content
    (e.g. 204 on a PATCH).
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.request(
        method, url, headers=headers, data=json.dumps(body), timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    if resp.status_code == 204 or not (resp.text or "").strip():
        return {}
    return resp.json()


def _base_url(base_url: str | None = None) -> str:
    return base_url or build_base_url()


# ---------------------------------------------------------------------------
# CALM read functions
# ---------------------------------------------------------------------------

def get_tasks(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks?projectId={project_id}"
    result = _get(url, token)
    return [
        {
            "ID": item.get("id"),
            "Title": item.get("title"),
            "Type": TASK_TYPE_MAP.get(item.get("type"), item.get("type")),
            "Status": TASK_STATUS_MAP.get(item.get("status"), item.get("status")),
            "StartDate": item.get("startDate"),
            "DueDate": item.get("dueDate"),
            "AssigneeName": item.get("assigneeName"),
            "ApprovalState": TASK_APPROVAL_STATE_MAP.get(item.get("approvalState"), item.get("approvalState")),
            "Obsolete": item.get("obsolete"),
        }
        for item in result
    ]


def get_projects(token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects"
    result = _get(url, token)
    return [
        {
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Status": PROJECT_STATUS_MAP.get(item.get("status"), item.get("status")),
            "Purpose": item.get("purpose"),
            "OperationalStatus": item.get("operationalStatus"),
        }
        for item in result
    ]


def get_business_processes(token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses"
    result = _get(url, token)
    return [
        {
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Description": item.get("description"),
        }
        for item in result.get("value", [])
    ]


def get_solution_processes(token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses"
    result = _get(url, token)
    return [
        {
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Description": item.get("description"),
            "Status": item.get("status"),
            "Countries": item.get("countries"),
            "State": item.get("state"),
        }
        for item in result.get("value", [])
    ]


def get_scopes(token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes"
    result = _get(url, token)
    return [
        {
            "ID": item.get("id"),
            "Project ID": item.get("projectId"),
            "Name": item.get("name"),
            "Description": item.get("description"),
        }
        for item in result.get("value", [])
    ]


def get_test_cases(token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases"
    result = _get(url, token)
    parsed = []
    for item in result.get("value", []):
        priority_code = str(item.get("priorityCode"))
        parsed.append({
            "Project ID": item.get("projectId"),
            "Scope ID": item.get("scopeId"),
            "Solution Process ID": item.get("solutionProcessId"),
            "Title": item.get("title"),
            "Prepared": item.get("isPrepared"),
            "Priority": TESTCASE_PRIORITY_MAP.get(priority_code, priority_code),
        })
    return parsed


# ---------------------------------------------------------------------------
# CALM write functions
#
# Payloads use the same camelCase field names the read functions parse back,
# so create/read stay consistent. Field contracts should be confirmed against
# the target tenant; raw CALM codes are accepted for `type`/`status` so callers
# can bypass label mapping if a tenant differs.
# ---------------------------------------------------------------------------

def _format_task(item: dict) -> dict:
    """Format a single raw task the same way get_tasks() formats a list item."""
    return {
        "ID": item.get("id"),
        "Title": item.get("title"),
        "Type": TASK_TYPE_MAP.get(item.get("type"), item.get("type")),
        "Status": TASK_STATUS_MAP.get(item.get("status"), item.get("status")),
        "StartDate": item.get("startDate"),
        "DueDate": item.get("dueDate"),
        "AssigneeName": item.get("assigneeName"),
        "ApprovalState": TASK_APPROVAL_STATE_MAP.get(item.get("approvalState"), item.get("approvalState")),
        "Obsolete": item.get("obsolete"),
    }


def create_task(
    token: str,
    project_id: str,
    title: str,
    task_type: str,
    status: str | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    assignee_id: str | None = None,
    description: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a task in a Cloud ALM project. Returns the created task, formatted."""
    type_code = resolve_task_type_code(task_type)
    body: dict[str, Any] = {
        "projectId": project_id,
        "title": title,
        "type": type_code,
    }
    if status is not None:
        body["status"] = resolve_status_code(status, type_code)
    if start_date is not None:
        body["startDate"] = start_date
    if due_date is not None:
        body["dueDate"] = due_date
    if assignee_id is not None:
        body["assigneeId"] = assignee_id
    if description is not None:
        body["description"] = description

    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks"
    result = _write("POST", url, token, body)
    return _format_task(result) if isinstance(result, dict) and result else {"submitted": body}


def update_task(
    token: str,
    task_id: str,
    title: str | None = None,
    task_type: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    assignee_id: str | None = None,
    description: str | None = None,
    obsolete: bool | None = None,
    base_url: str | None = None,
) -> dict:
    """Update fields of an existing task (partial PATCH). Only provided fields are sent.

    `status` needs the task type to resolve a human label to a code; pass
    `task_type` alongside a human status, or pass a raw CALM status code.
    """
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if task_type is not None:
        body["type"] = resolve_task_type_code(task_type)
    if status is not None:
        # If a human label is given we need the type to pick the right code.
        type_code = body.get("type") or (resolve_task_type_code(task_type) if task_type else None)
        if status in _KNOWN_STATUS_CODES or type_code:
            body["status"] = resolve_status_code(status, type_code or "")
        else:
            raise ValueError(
                "Updating status by human label requires `task_type`; "
                "or pass a raw CALM status code."
            )
    if start_date is not None:
        body["startDate"] = start_date
    if due_date is not None:
        body["dueDate"] = due_date
    if assignee_id is not None:
        body["assigneeId"] = assignee_id
    if description is not None:
        body["description"] = description
    if obsolete is not None:
        body["obsolete"] = obsolete

    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}"
    result = _write("PATCH", url, token, body)
    return _format_task(result) if isinstance(result, dict) and result else {"updated": task_id, "fields": body}


# --- Projects ---------------------------------------------------------------

def _format_project(item: dict) -> dict:
    return {
        "ID": item.get("id"),
        "Name": item.get("name"),
        "Status": PROJECT_STATUS_MAP.get(item.get("status"), item.get("status")),
        "Purpose": item.get("purpose"),
        "OperationalStatus": item.get("operationalStatus"),
    }


def create_project(
    token: str,
    name: str,
    status: str | None = None,
    purpose: str | None = None,
    operational_status: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a Cloud ALM project. Returns the created project, formatted."""
    body: dict[str, Any] = {"name": name}
    if status is not None:
        body["status"] = resolve_project_status(status)
    if purpose is not None:
        body["purpose"] = purpose
    if operational_status is not None:
        body["operationalStatus"] = operational_status

    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects"
    result = _write("POST", url, token, body)
    return _format_project(result) if isinstance(result, dict) and result else {"submitted": body}


def update_project(
    token: str,
    project_id: str,
    name: str | None = None,
    status: str | None = None,
    purpose: str | None = None,
    operational_status: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a project. Only provided fields are sent."""
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if status is not None:
        body["status"] = resolve_project_status(status)
    if purpose is not None:
        body["purpose"] = purpose
    if operational_status is not None:
        body["operationalStatus"] = operational_status
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}"
    result = _write("PATCH", url, token, body)
    return _format_project(result) if isinstance(result, dict) and result else {"updated": project_id, "fields": body}


# --- Business processes -----------------------------------------------------

def _format_business_process(item: dict) -> dict:
    return {
        "ID": item.get("id"),
        "Name": item.get("name"),
        "Description": item.get("description"),
    }


def create_business_process(
    token: str,
    name: str,
    description: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a business process. Returns the created process, formatted."""
    body: dict[str, Any] = {"name": name}
    if description is not None:
        body["description"] = description

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses"
    result = _write("POST", url, token, body)
    return _format_business_process(result) if isinstance(result, dict) and result else {"submitted": body}


def update_business_process(
    token: str,
    business_process_id: str,
    name: str | None = None,
    description: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a business process. Only provided fields are sent."""
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses/{business_process_id}"
    result = _write("PATCH", url, token, body)
    return _format_business_process(result) if isinstance(result, dict) and result else {"updated": business_process_id, "fields": body}


# --- Solution processes -----------------------------------------------------

def _format_solution_process(item: dict) -> dict:
    return {
        "ID": item.get("id"),
        "Name": item.get("name"),
        "Description": item.get("description"),
        "Status": item.get("status"),
        "Countries": item.get("countries"),
        "State": item.get("state"),
    }


def create_solution_process(
    token: str,
    name: str,
    description: str | None = None,
    status: str | None = None,
    countries: list | None = None,
    state: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a solution process. Returns the created process, formatted."""
    body: dict[str, Any] = {"name": name}
    if description is not None:
        body["description"] = description
    if status is not None:
        body["status"] = status
    if countries is not None:
        body["countries"] = countries
    if state is not None:
        body["state"] = state

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses"
    result = _write("POST", url, token, body)
    return _format_solution_process(result) if isinstance(result, dict) and result else {"submitted": body}


def update_solution_process(
    token: str,
    solution_process_id: str,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    countries: list | None = None,
    state: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a solution process. Only provided fields are sent."""
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if status is not None:
        body["status"] = status
    if countries is not None:
        body["countries"] = countries
    if state is not None:
        body["state"] = state
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses/{solution_process_id}"
    result = _write("PATCH", url, token, body)
    return _format_solution_process(result) if isinstance(result, dict) and result else {"updated": solution_process_id, "fields": body}


# --- Scopes -----------------------------------------------------------------

def _format_scope(item: dict) -> dict:
    return {
        "ID": item.get("id"),
        "Project ID": item.get("projectId"),
        "Name": item.get("name"),
        "Description": item.get("description"),
    }


def create_scope(
    token: str,
    project_id: str,
    name: str,
    description: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a process-management scope in a project. Returns it, formatted."""
    body: dict[str, Any] = {"projectId": project_id, "name": name}
    if description is not None:
        body["description"] = description

    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes"
    result = _write("POST", url, token, body)
    return _format_scope(result) if isinstance(result, dict) and result else {"submitted": body}


def update_scope(
    token: str,
    scope_id: str,
    name: str | None = None,
    description: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a scope. Only provided fields are sent."""
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes/{scope_id}"
    result = _write("PATCH", url, token, body)
    return _format_scope(result) if isinstance(result, dict) and result else {"updated": scope_id, "fields": body}


# --- Manual test cases ------------------------------------------------------

def _format_test_case(item: dict) -> dict:
    priority_code = str(item.get("priorityCode"))
    return {
        "ID": item.get("id"),
        "Project ID": item.get("projectId"),
        "Scope ID": item.get("scopeId"),
        "Solution Process ID": item.get("solutionProcessId"),
        "Title": item.get("title"),
        "Prepared": item.get("isPrepared"),
        "Priority": TESTCASE_PRIORITY_MAP.get(priority_code, priority_code),
    }


def create_test_case(
    token: str,
    title: str,
    project_id: str | None = None,
    scope_id: str | None = None,
    solution_process_id: str | None = None,
    priority: str | None = None,
    is_prepared: bool | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a manual test case. Returns the created test case, formatted."""
    body: dict[str, Any] = {"title": title}
    if project_id is not None:
        body["projectId"] = project_id
    if scope_id is not None:
        body["scopeId"] = scope_id
    if solution_process_id is not None:
        body["solutionProcessId"] = solution_process_id
    if priority is not None:
        body["priorityCode"] = resolve_testcase_priority(priority)
    if is_prepared is not None:
        body["isPrepared"] = is_prepared

    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases"
    result = _write("POST", url, token, body)
    return _format_test_case(result) if isinstance(result, dict) and result else {"submitted": body}


def update_test_case(
    token: str,
    test_case_id: str,
    title: str | None = None,
    scope_id: str | None = None,
    solution_process_id: str | None = None,
    priority: str | None = None,
    is_prepared: bool | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a manual test case. Only provided fields are sent."""
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if scope_id is not None:
        body["scopeId"] = scope_id
    if solution_process_id is not None:
        body["solutionProcessId"] = solution_process_id
    if priority is not None:
        body["priorityCode"] = resolve_testcase_priority(priority)
    if is_prepared is not None:
        body["isPrepared"] = is_prepared
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases/{test_case_id}"
    result = _write("PATCH", url, token, body)
    return _format_test_case(result) if isinstance(result, dict) and result else {"updated": test_case_id, "fields": body}
