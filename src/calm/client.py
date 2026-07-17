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
    "CIPRIOPEN": "Open", "CIPRIINP": "In Progress", "CIPRIDONE": "Done",
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
    "CALMRISK": "Risk",
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
    # Sub-tasks (CALMST) use the task (CIPTK*) status codes, not user-story codes.
    "CALMST": {"open": "CIPTKOPEN", "in progress": "CIPTKINP", "blocked": "CIPTKBLK",
               "done": "CIPTKCLOSE", "not relevant": "CIPTKNO"},
    "CALMUS": {"open": "CIPUSOPEN", "in progress": "CIPUSINP", "blocked": "CIPUSBLK",
               "done": "CIPUSCLOSE", "not relevant": "CIPUSNO"},
    "CALMREQU": {"open": "CIPREQUOPEN", "in progress": "CIPREQUINP", "blocked": "CIPREQUBLK",
                 "done": "CIPREQUCLOSE", "not relevant": "CIPREQUNO"},
    "CALMDEF": {"open": "CIPDFCTOPEN", "in progress": "CIPDFCTINP", "blocked": "CIPDFCTBLK",
                "done": "CIPDFCTDONE"},
    "CALMQGATE": {"open": "CIPQGOPEN", "blocked": "CIPQGBLK", "not relevant": "CIPQGNR",
                  "done": "CIPQGDONE"},
    "CALMRISK": {"open": "CIPRIOPEN", "in progress": "CIPRIINP", "done": "CIPRIDONE"},
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


TESTCASE_PRIORITY_REVERSE_MAP = {label.lower(): code for code, label in TESTCASE_PRIORITY_MAP.items()}


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


def _write(method: str, url: str, token: str, body: dict, if_match: str | None = None) -> Any:
    """Send a JSON write request (POST/PATCH) and return the parsed response.

    Returns the parsed JSON body, or {} when the API responds with no content
    (e.g. 204 on a PATCH). `if_match` sets the If-Match header, required by the
    OData services (Process Authoring, Test Management) for PATCH/DELETE.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if if_match:
        headers["If-Match"] = if_match
    resp = requests.request(
        method, url, headers=headers, data=json.dumps(body), timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    if resp.status_code == 204 or not (resp.text or "").strip():
        return {}
    return resp.json()


def _delete(url: str, token: str, if_match: str | None = None) -> dict:
    """Send a DELETE and return {} (or the parsed body if the API returns one)."""
    headers = {"Authorization": f"Bearer {token}"}
    if if_match:
        headers["If-Match"] = if_match
    resp = requests.request("DELETE", url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    if resp.status_code == 204 or not (resp.text or "").strip():
        return {}
    return resp.json()


def _get_with_meta(url: str, token: str) -> tuple[Any, str | None]:
    """GET a single entity, returning (parsed_json, etag).

    etag is taken from the ETag response header when present. Used to obtain the
    If-Match token for OData updates when the caller did not supply one.
    """
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json() if (resp.text or "").strip() else {}
    try:
        etag = resp.headers.get("ETag") or resp.headers.get("etag")
    except Exception:
        etag = None
    return data, etag


def _resolve_etag(
    url: str, token: str, if_match: str | None, body_field: str | None = None
) -> str | None:
    """Return the If-Match token: the caller's value, else fetched from the entity.

    The ETag comes from the response ETag header when present; otherwise it is read
    from the given response body field — `"etag"` for Projects (a numeric timestamp)
    or `"modifiedAt"` for Test Management.
    """
    if if_match:
        return if_match
    data, etag = _get_with_meta(url, token)
    if etag:
        return etag
    if body_field and isinstance(data, dict):
        return data.get(body_field)
    return None


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
    priority_id: int | None = None,
    external_id: str | None = None,
    parent_id: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a task in a Cloud ALM project. Returns the created task, formatted.

    `assignee_id` is the assignee's email address. `priority_id` is numeric
    (10/20/30/40 = Very High/High/Medium/Low). `parent_id` links a sub-task to
    its parent. `extra_fields` merges any other documented task field verbatim
    (e.g. subStatus, scopeId, storyPoints, effort, workstream, involvedParties,
    classificationId, customField1..20) — used for the long tail not exposed as
    named args.
    """
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
    if priority_id is not None:
        body["priorityId"] = priority_id
    if external_id is not None:
        body["externalId"] = external_id
    if parent_id is not None:
        body["parentId"] = parent_id
    if extra_fields:
        body.update(extra_fields)

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
    priority_id: int | None = None,
    external_id: str | None = None,
    obsolete: bool | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None,
) -> dict:
    """Update fields of an existing task (partial PATCH). Only provided fields are sent.

    `status` needs the task type to resolve a human label to a code; pass
    `task_type` alongside a human status, or pass a raw CALM status code.
    Tasks are a plain REST API — no If-Match/ETag needed. `extra_fields` merges
    any other documented task field verbatim.
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
    if priority_id is not None:
        body["priorityId"] = priority_id
    if external_id is not None:
        body["externalId"] = external_id
    if obsolete is not None:
        body["obsolete"] = obsolete
    if extra_fields:
        body.update(extra_fields)

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
    program_id: str | None = None,
    deployment_plan_id: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a Cloud ALM project. Returns the created project, formatted.

    Plain REST POST — no If-Match. The spec confirms only `name` (and optionally
    `programId`) on the create body; `status`/`purpose`/`operationalStatus`/`phaseId`
    are managed elsewhere (not settable here). Anything extra can still be attempted
    via `extra_fields`.
    """
    body: dict[str, Any] = {"name": name}
    if program_id is not None:
        body["programId"] = program_id
    if deployment_plan_id is not None:
        body["deploymentPlanId"] = deployment_plan_id
    if extra_fields:
        body.update(extra_fields)

    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects"
    result = _write("POST", url, token, body)
    return _format_project(result) if isinstance(result, dict) and result else {"submitted": body}


def update_project(
    token: str,
    project_id: str,
    name: str | None = None,
    program_id: str | None = None,
    deployment_plan_id: str | None = None,
    if_match: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a project. Only provided fields are sent.

    The spec confirms the PATCH body is exactly {name, deploymentPlanId, programId};
    status/operationalStatus/purpose/phaseId are NOT patchable via this API.
    PATCH requires If-Match — the project's `etag` field (a numeric timestamp). If
    `if_match` is not supplied it is fetched from the entity first.
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if program_id is not None:
        body["programId"] = program_id
    if deployment_plan_id is not None:
        body["deploymentPlanId"] = deployment_plan_id
    if extra_fields:
        body.update(extra_fields)
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}"
    etag = _resolve_etag(url, token, if_match, body_field="etag")
    result = _write("PATCH", url, token, body, if_match=etag)
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
    if_match: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a business process. Only provided fields are sent.

    OData service — PATCH requires If-Match. If `if_match` is not supplied, the
    current ETag is fetched from the entity first.
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses/{business_process_id}"
    etag = _resolve_etag(url, token, if_match)
    result = _write("PATCH", url, token, body, if_match=etag)
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


def _countries_to_str(countries: Any) -> str:
    """CALM expects countries as a comma-separated string ("DE,FR"), not an array."""
    if isinstance(countries, (list, tuple)):
        return ",".join(str(c).strip() for c in countries)
    return str(countries)


def create_solution_process(
    token: str,
    name: str,
    description: str | None = None,
    status: str | None = None,
    countries: Any = None,
    state: str | None = None,
    business_process_id: str | None = None,
    external_id: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a solution process. Returns the created process, formatted.

    `countries` may be a list (["DE","FR"]) or a comma-string ("DE,FR"); it is
    sent as a comma-separated string. `business_process_id` links the parent
    business process (sent as the nested {"businessProcess": {"id": ...}}).
    """
    body: dict[str, Any] = {"name": name}
    if description is not None:
        body["description"] = description
    if status is not None:
        body["status"] = status
    if countries is not None:
        body["countries"] = _countries_to_str(countries)
    if state is not None:
        body["state"] = state
    if external_id is not None:
        body["externalId"] = external_id
    if business_process_id is not None:
        body["businessProcess"] = {"id": business_process_id}

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses"
    result = _write("POST", url, token, body)
    return _format_solution_process(result) if isinstance(result, dict) and result else {"submitted": body}


def update_solution_process(
    token: str,
    solution_process_id: str,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    countries: Any = None,
    state: str | None = None,
    external_id: str | None = None,
    if_match: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a solution process. Only provided fields are sent.

    OData service — PATCH requires If-Match (auto-fetched if not supplied).
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if status is not None:
        body["status"] = status
    if countries is not None:
        body["countries"] = _countries_to_str(countries)
    if state is not None:
        body["state"] = state
    if external_id is not None:
        body["externalId"] = external_id
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses/{solution_process_id}"
    etag = _resolve_etag(url, token, if_match)
    result = _write("PATCH", url, token, body, if_match=etag)
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
    if_match: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a scope. Only provided fields are sent.

    OData service, but the spec confirms scopes need NO If-Match, so none is
    fetched; a caller-supplied `if_match` is still honoured if given.
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes/{scope_id}"
    result = _write("PATCH", url, token, body, if_match=if_match)
    return _format_scope(result) if isinstance(result, dict) and result else {"updated": scope_id, "fields": body}


# --- Manual test cases ------------------------------------------------------

def _format_test_case(item: dict) -> dict:
    priority_code = str(item.get("priorityCode"))
    return {
        # Test Management is OData; the key is `uuid` (fall back to `id`).
        "ID": item.get("uuid") or item.get("id"),
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
    activities: list | None = None,
    references: list | None = None,
    solution_process_flow_id: str | None = None,
    solution_process_flow_diagram_id: str | None = None,
    content_package_id: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Create a manual test case. Returns the created test case, formatted.

    `priorityCode` is sent numeric (10/20/30/40). POST supports deep insert of
    nested steps: pass `activities` as a list of activity dicts (each may contain
    a `toActions` list) and `references` as a list of {name, url}.

    To create a *process-linked* test case, all four of solution_process_id,
    solution_process_flow_id, solution_process_flow_diagram_id, and
    content_package_id must be provided together (content_package_id is "CUSTOM"
    for custom processes).
    """
    body: dict[str, Any] = {"title": title}
    if project_id is not None:
        body["projectId"] = project_id
    if scope_id is not None:
        body["scopeId"] = scope_id
    if solution_process_id is not None:
        body["solutionProcessId"] = solution_process_id
    if solution_process_flow_id is not None:
        body["solutionProcessFlowId"] = solution_process_flow_id
    if solution_process_flow_diagram_id is not None:
        body["solutionProcessFlowDiagramId"] = solution_process_flow_diagram_id
    if content_package_id is not None:
        body["contentPackageId"] = content_package_id
    if priority is not None:
        body["priorityCode"] = int(resolve_testcase_priority(priority))
    if is_prepared is not None:
        body["isPrepared"] = is_prepared
    if activities is not None:
        body["toActivities"] = activities
    if references is not None:
        body["toReferences"] = references

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
    if_match: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Partial-update a manual test case. Only provided fields are sent.

    OData service — PATCH requires If-Match. The ETag is the entity's modifiedAt
    timestamp; if `if_match` is not supplied it is fetched from the entity.
    Note: deep updates of nested Activities/Actions are not supported here — use
    their own endpoints.
    """
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if scope_id is not None:
        body["scopeId"] = scope_id
    if solution_process_id is not None:
        body["solutionProcessId"] = solution_process_id
    if priority is not None:
        body["priorityCode"] = int(resolve_testcase_priority(priority))
    if is_prepared is not None:
        body["isPrepared"] = is_prepared
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases/{test_case_id}"
    etag = _resolve_etag(url, token, if_match, body_field="modifiedAt")
    result = _write("PATCH", url, token, body, if_match=etag)
    return _format_test_case(result) if isinstance(result, dict) and result else {"updated": test_case_id, "fields": body}


# ---------------------------------------------------------------------------
# CALM delete functions (guarded at the tool layer by CALM_ENABLE_WRITES)
# ---------------------------------------------------------------------------

def delete_task(token: str, task_id: str, base_url: str | None = None) -> dict:
    """Delete a task. Plain REST — no If-Match. Returns {"deleted": task_id}."""
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}"
    _delete(url, token)
    return {"deleted": task_id}


def delete_business_process(
    token: str, business_process_id: str, if_match: str | None = None, base_url: str | None = None
) -> dict:
    """Delete a business process. OData — DELETE needs If-Match (auto-fetched)."""
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses/{business_process_id}"
    etag = _resolve_etag(url, token, if_match)
    _delete(url, token, if_match=etag)
    return {"deleted": business_process_id}


def delete_solution_process(
    token: str, solution_process_id: str, if_match: str | None = None, base_url: str | None = None
) -> dict:
    """Delete a solution process. OData — DELETE needs If-Match (auto-fetched)."""
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses/{solution_process_id}"
    etag = _resolve_etag(url, token, if_match)
    _delete(url, token, if_match=etag)
    return {"deleted": solution_process_id}


def delete_scope(
    token: str, scope_id: str, if_match: str | None = None, base_url: str | None = None
) -> dict:
    """Delete a scope. OData; spec confirms no If-Match needed (honoured if given)."""
    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes/{scope_id}"
    _delete(url, token, if_match=if_match)
    return {"deleted": scope_id}


def delete_test_case(
    token: str,
    test_case_id: str,
    force: bool = False,
    if_match: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Delete a manual test case. OData — DELETE needs If-Match (= modifiedAt).

    Plain DELETE fails (412) if the test case has execution history. Set
    `force=True` to call the force-delete action, which also removes test runs
    and results (requires the calm-api.testcases.force-delete scope).
    """
    base = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases/{test_case_id}"
    etag = _resolve_etag(base, token, if_match, body_field="modifiedAt")
    if force:
        action_url = f"{base}/api.v1.ExternalServiceAPI.forceDeletionIncludingTestRunsAndResults"
        _write("POST", action_url, token, {}, if_match=etag)
        return {"deleted": test_case_id, "force": True}
    _delete(base, token, if_match=etag)
    return {"deleted": test_case_id}
