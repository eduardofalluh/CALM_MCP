"""
Cloud ALM HTTP client.

1:1 port of the standalone functions from the existing Syntax GenAI Studio agent.
Token is received from the caller (resolved by the dependency layer) — no
credentials are stored or fetched here.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import requests

from .config import build_base_url

REQUEST_TIMEOUT = 30  # seconds

log = logging.getLogger("calm-mcp.client")


def _raise_for_status(resp: requests.Response, url: str) -> None:
    """Raise with the API's actual response body on any 4xx/5xx.

    requests' raise_for_status() drops the response body, which hides the real
    reason (400 field errors, 415 media type, 412/428 ETag, …). Surface it — the
    Authorization header and request body are never included here.
    """
    if resp.status_code >= 400:
        raise RuntimeError(
            f"CALM API error: HTTP {resp.status_code} {resp.reason} at {url} — "
            f"response: {(resp.text or '')[:800]}"
        )

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
    _raise_for_status(resp, url)
    return resp.json()


def _write(
    method: str,
    url: str,
    token: str,
    body: dict,
    if_match: str | None = None,
    content_type: str = "application/json",
    user_email: str | None = None,
) -> Any:
    """Send a JSON write request (POST/PATCH) and return the parsed response.

    Returns the parsed JSON body, or {} when the API responds with no content
    (e.g. 204 on a PATCH). `if_match` sets the If-Match header, required by the
    OData services (Process Authoring, Test Management) for PATCH/DELETE.
    `content_type` defaults to application/json; some endpoints (e.g. the
    processmanagement scopes PATCH) require application/merge-patch+json.
    `user_email` is included in request headers for audit logging in CALM.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": content_type,
    }
    if if_match:
        headers["If-Match"] = if_match
    if user_email:
        # SAP Cloud ALM may use these headers for audit logging
        headers["X-User-Email"] = user_email
        headers["X-Forwarded-User"] = user_email
    # DEBUG only; never logs Authorization or the request body.
    log.debug(
        "CALM write: %s %s (Content-Type=%s, If-Match=%s)",
        method, url, content_type, headers.get("If-Match", "-"),
    )
    resp = requests.request(
        method, url, headers=headers, data=json.dumps(body), timeout=REQUEST_TIMEOUT
    )
    _raise_for_status(resp, url)
    if resp.status_code == 204 or not (resp.text or "").strip():
        return {}
    return resp.json()


def _delete(url: str, token: str, if_match: str | None = None, user_email: str | None = None) -> dict:
    """Send a DELETE and return {} (or the parsed body if the API returns one)."""
    headers = {"Authorization": f"Bearer {token}"}
    if if_match:
        headers["If-Match"] = if_match
    if user_email:
        headers["X-User-Email"] = user_email
        headers["X-Forwarded-User"] = user_email
    log.debug("CALM delete: %s (If-Match=%s)", url, headers.get("If-Match", "-"))
    resp = requests.request("DELETE", url, headers=headers, timeout=REQUEST_TIMEOUT)
    _raise_for_status(resp, url)
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
    _raise_for_status(resp, url)
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


def _tm_if_match(if_match: str | None) -> str:
    """If-Match token for Test Management PATCH/DELETE.

    The entity's modifiedAt timestamp is documented as the ETag but is rejected as
    an If-Match token in practice (412 Precondition Failed). The '*' wildcard —
    match any current version — is accepted, so it's the default here. Callers can
    still pass an explicit ETag for strict optimistic concurrency.
    """
    return if_match or "*"


def _base_url(base_url: str | None = None) -> str:
    return base_url or build_base_url()


# ---------------------------------------------------------------------------
# CALM read functions
# ---------------------------------------------------------------------------

def get_tasks(
    project_id: str, token: str, base_url: str | None = None, task_type: str | None = None
) -> list[dict]:
    """Return tasks for a project. `task_type` (human label or raw code) filters to
    one type — e.g. "Requirement" (CALMREQU) for requirements. The type is sent as a
    query param and also filtered client-side so the result is correct even if the
    API ignores the param.
    """
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks?projectId={project_id}"
    type_code: str | None = None
    if task_type:
        type_code = resolve_task_type_code(task_type)
        url += f"&type={type_code}"
    result = _get(url, token)
    items = result if isinstance(result, list) else result.get("value", [])
    if type_code:
        items = [it for it in items if it.get("type") == type_code]
    return [_format_task(item) for item in items]


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
    return [_format_test_case(item) for item in result.get("value", [])]


def get_timeboxes(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return timeboxes (sprints, iterations) for a project.

    Timeboxes are used to organize work into time-bounded periods. Common fields:
    name, type (numeric), startDate, endDate, closed (boolean).
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/timeboxes"
    result = _get(url, token)
    items = result if isinstance(result, list) else result.get("value", [])
    return [
        {
            "ID": item.get("id"),
            "Project ID": item.get("projectId") or project_id,
            "Name": item.get("name"),
            "Type": item.get("type"),
            "StartDate": item.get("startDate"),
            "EndDate": item.get("endDate"),
            "Closed": item.get("closed"),
        }
        for item in items
    ]


def get_teams(token: str, base_url: str | None = None) -> list[dict]:
    """Return all teams visible to the configured tenant.

    Teams group users for project collaboration. The exact fields depend on
    what the CALM API exposes; common fields: id, name, description, members.
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/teams"
    result = _get(url, token)
    items = result if isinstance(result, list) else result.get("value", [])
    return [
        {
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Description": item.get("description"),
            "Project ID": item.get("projectId"),
        }
        for item in items
    ]


# --- Tags -------------------------------------------------------------------

def get_tags(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return all tag definitions for a project.

    Tags are project-level metadata organized in groups. Each tag has a group
    name and tag name, formatted as "Group: Tag" (e.g. "Scope:Baseline",
    "Tshirt size:L"). Used to categorize tasks and requirements.
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/tags"
    result = _get(url, token)
    items = result if isinstance(result, list) else result.get("value", [])
    return [
        {
            "ID": item.get("id"),
            "Project ID": item.get("projectId") or project_id,
            "Group": item.get("group"),
            "Tag": item.get("tag"),
            "Full Name": f"{item.get('group')}: {item.get('tag')}" if item.get("group") and item.get("tag") else None,
        }
        for item in items
    ]


def create_tag(
    token: str,
    project_id: str,
    group: str,
    tag: str,
    base_url: str | None = None,
    user_email: str | None = None,
) -> dict:
    """Create a new tag definition in a project.

    Tags must be created before they can be assigned to tasks/requirements.
    The group and tag names are case-sensitive.

    Args:
        project_id: Target project ID
        group: Tag group name (e.g. "Scope", "Tshirt size")
        tag: Tag value (e.g. "Baseline", "L")
    """
    body = {
        "projectId": project_id,
        "group": group,
        "tag": tag,
    }
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/tags"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if isinstance(result, dict) and result else {"submitted": body}


# --- Users / Team Members ---------------------------------------------------

def get_project_users(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return all users/team members for a project with their assignable IDs.

    Use this to get the correct assignee IDs before creating/updating tasks.
    The returned 'ID' field is what should be passed as assignee_id to avoid
    'Former Member' issues.

    Tries multiple endpoints in order:
    1. /projects/{id}/users (most specific)
    2. /projects/{id}/team (alternative)
    3. /teams endpoint filtering by project (fallback)
    """
    # Try primary endpoint first
    urls_to_try = [
        f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/users",
        f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/team",
        f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/members",
    ]

    last_error = None
    for url in urls_to_try:
        try:
            result = _get(url, token)
            items = result if isinstance(result, list) else result.get("value", [])
            return [
                {
                    "ID": item.get("id") or item.get("userId") or item.get("memberId"),
                    "Email": item.get("email") or item.get("userEmail") or item.get("emailAddress"),
                    "Name": item.get("name") or item.get("displayName") or item.get("fullName"),
                    "Role": item.get("role") or item.get("projectRole"),
                    "Active": item.get("active", True),
                }
                for item in items
            ]
        except Exception as e:
            last_error = e
            continue

    # All endpoints failed
    raise RuntimeError(
        f"Could not fetch project users from any endpoint. "
        f"Last error: {last_error}. "
        f"Your OAuth2 client may need additional scopes (calm.users.read or similar)."
    )


# --- Features ---------------------------------------------------------------

def get_features(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return all features for a project.

    Features are higher-level groupings used for transport tracking and
    release planning. Each feature can contain multiple requirements.
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/features"
    result = _get(url, token)
    items = result if isinstance(result, list) else result.get("value", [])
    return [
        {
            "ID": item.get("id"),
            "Project ID": item.get("projectId") or project_id,
            "Name": item.get("name"),
            "Description": item.get("description"),
            "Status": item.get("status"),
            "External ID": item.get("externalId"),
        }
        for item in items
    ]


def create_feature(
    token: str,
    project_id: str,
    name: str,
    description: str | None = None,
    external_id: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None,
    user_email: str | None = None,
) -> dict:
    """Create a new feature in a project.

    Features group requirements for transport and release management. Used
    for baseline requirements in BP workflows.

    Args:
        project_id: Target project ID
        name: Feature name
        description: Optional description
        external_id: Optional external system reference
        extra_fields: Additional API fields (status, etc.)
    """
    body: dict[str, Any] = {
        "projectId": project_id,
        "name": name,
    }
    if description is not None:
        body["description"] = description
    if external_id is not None:
        body["externalId"] = external_id
    if extra_fields:
        body.update(extra_fields)

    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/features"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if isinstance(result, dict) and result else {"submitted": body}


# --- Test Plans -------------------------------------------------------------

def get_test_plans(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return all test plans for a project.

    Test plans organize test cases into execution sets. Each plan can be
    assigned to testers and tracked separately.
    """
    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/projects/{project_id}/testPlans"
    result = _get(url, token)
    items = result if isinstance(result, list) else result.get("value", [])
    return [
        {
            "ID": item.get("id"),
            "Project ID": item.get("projectId") or project_id,
            "Name": item.get("name"),
            "Description": item.get("description"),
            "Status": item.get("status"),
        }
        for item in items
    ]


def create_test_plan(
    token: str,
    project_id: str,
    name: str,
    description: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None,
    user_email: str | None = None,
) -> dict:
    """Create a new test plan in a project.

    Test plans group test cases for execution tracking. Used to organize
    customer enablement scripts and other test scenarios.

    Args:
        project_id: Target project ID
        name: Test plan name
        description: Optional description
        extra_fields: Additional API fields
    """
    body: dict[str, Any] = {
        "projectId": project_id,
        "name": name,
    }
    if description is not None:
        body["description"] = description
    if extra_fields:
        body.update(extra_fields)

    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/projects/{project_id}/testPlans"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if isinstance(result, dict) and result else {"submitted": body}


def assign_test_case_to_plan(
    token: str,
    test_plan_id: str,
    test_case_id: str,
    tester_email: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None,
    user_email: str | None = None,
) -> dict:
    """Assign a test case to a test plan, optionally with a tester.

    Args:
        test_plan_id: Target test plan ID
        test_case_id: Test case to assign
        tester_email: Optional email of assigned tester
        extra_fields: Additional API fields
    """
    body: dict[str, Any] = {
        "testPlanId": test_plan_id,
        "testCaseId": test_case_id,
    }
    if tester_email is not None:
        body["testerEmail"] = tester_email
    if extra_fields:
        body.update(extra_fields)

    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/testPlans/{test_plan_id}/assignments"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if isinstance(result, dict) and result else {"submitted": body}


def link_test_case_to_requirement(
    token: str,
    test_case_id: str,
    requirement_id: str,
    link_type: str = "covers",
    base_url: str | None = None,
    user_email: str | None = None,
) -> dict:
    """Link a test case to a requirement for traceability.

    Creates a reference from the test case to the requirement, establishing
    test coverage tracking. This is the standard way to track which test cases
    verify which requirements in CALM.

    Args:
        test_case_id: UUID of the test case (from get_calm_test_cases or create_calm_test_case)
        requirement_id: Task ID of the requirement (from get_calm_requirements or create_calm_requirement)
        link_type: Type of link (default "covers" for test coverage)

    Common link types:
        - "covers": Test case covers/verifies this requirement
        - "validates": Test case validates this requirement
        - "references": General reference link

    Returns the created reference object or submission confirmation.
    """
    body: dict[str, Any] = {
        "name": f"Requirement {requirement_id}",
        "url": f"/calm/tasks/{requirement_id}",
        "type": link_type,
        "targetId": requirement_id,
        "targetType": "requirement",
    }

    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases/{test_case_id}/toReferences"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if isinstance(result, dict) and result else {"submitted": body, "test_case_id": test_case_id, "requirement_id": requirement_id}


# --- Project Customization Values -------------------------------------------

def get_project_customization(project_id: str, token: str, base_url: str | None = None) -> dict:
    """Return all customization values for a project.

    Returns picklist values for workstreams, deliverables, and other
    project-specific custom fields. Used to validate task field values
    against the project's allowed options.

    Returns dict with keys: workstreams, deliverables, customFields
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/customization"
    result = _get(url, token)

    return {
        "Project ID": project_id,
        "Workstreams": result.get("workstreams", []),
        "Deliverables": result.get("deliverables", []),
        "Custom Fields": result.get("customFields", []),
    }


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
        "Display ID": item.get("displayId") or item.get("externalId"),
        "Title": item.get("title"),
        "Type": TASK_TYPE_MAP.get(item.get("type"), item.get("type")),
        "Status": TASK_STATUS_MAP.get(item.get("status"), item.get("status")),
        "StartDate": item.get("startDate"),
        "DueDate": item.get("dueDate"),
        "AssigneeName": item.get("assigneeName"),
        "AssigneeID": item.get("assigneeId"),  # UUID needed for auto-resolution
        "ApprovalState": TASK_APPROVAL_STATE_MAP.get(item.get("approvalState"), item.get("approvalState")),
        "Obsolete": item.get("obsolete"),
        "Effort": item.get("effort"),
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
    base_url: str | None = None, user_email: str | None = None,
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
    result = _write("POST", url, token, body, user_email=user_email)
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
    base_url: str | None = None, user_email: str | None = None,
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
        if status not in _KNOWN_STATUS_CODES and not type_code:
            # Auto-fetch the task's type so a human status label works standalone.
            try:
                data, _ = _get_with_meta(
                    f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}", token
                )
                if isinstance(data, dict) and data.get("type"):
                    type_code = data["type"]
            except Exception:
                pass
        if status in _KNOWN_STATUS_CODES or type_code:
            body["status"] = resolve_status_code(status, type_code or "")
        else:
            raise ValueError(
                "Updating status by human label requires `task_type` (could not "
                "auto-detect the task's type); or pass a raw CALM status code."
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
    result = _write("PATCH", url, token, body, user_email=user_email)
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
    base_url: str | None = None, user_email: str | None = None,
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
    result = _write("POST", url, token, body, user_email=user_email)
    return _format_project(result) if isinstance(result, dict) and result else {"submitted": body}


def update_project(
    token: str,
    project_id: str,
    name: str | None = None,
    program_id: str | None = None,
    deployment_plan_id: str | None = None,
    if_match: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None, user_email: str | None = None,
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
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
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
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create a business process. Returns the created process, formatted."""
    body: dict[str, Any] = {"name": name}
    if description is not None:
        body["description"] = description

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses"
    result = _write("POST", url, token, body, user_email=user_email)
    return _format_business_process(result) if isinstance(result, dict) and result else {"submitted": body}


def update_business_process(
    token: str,
    business_process_id: str,
    name: str | None = None,
    description: str | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
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
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
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
    base_url: str | None = None, user_email: str | None = None,
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
    result = _write("POST", url, token, body, user_email=user_email)
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
    base_url: str | None = None, user_email: str | None = None,
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
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
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
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create a process-management scope in a project. Returns it, formatted."""
    body: dict[str, Any] = {"projectId": project_id, "name": name}
    if description is not None:
        body["description"] = description

    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes"
    result = _write("POST", url, token, body, user_email=user_email)
    return _format_scope(result) if isinstance(result, dict) and result else {"submitted": body}


def update_scope(
    token: str,
    scope_id: str,
    name: str | None = None,
    description: str | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
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
    # The processmanagement scopes PATCH rejects application/json with 415; it
    # follows JSON Merge Patch (RFC 7386) and requires this media type.
    result = _write(
        "PATCH", url, token, body, if_match=if_match, content_type="application/merge-patch+json"
    , user_email=user_email)
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
    base_url: str | None = None, user_email: str | None = None,
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
    result = _write("POST", url, token, body, user_email=user_email)
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
    base_url: str | None = None, user_email: str | None = None,
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
    etag = _tm_if_match(if_match)
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
    return _format_test_case(result) if isinstance(result, dict) and result else {"updated": test_case_id, "fields": body}


# ---------------------------------------------------------------------------
# CALM delete functions (guarded at the tool layer by CALM_ENABLE_WRITES)
# ---------------------------------------------------------------------------

def delete_task(token: str, task_id: str, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Delete a task. Plain REST — no If-Match. Returns {"deleted": task_id}."""
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}"
    _delete(url, token, user_email=user_email)
    return {"deleted": task_id}


def delete_business_process(
    token: str, business_process_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    """Delete a business process. OData — DELETE needs If-Match (auto-fetched)."""
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses/{business_process_id}"
    etag = _resolve_etag(url, token, if_match)
    _delete(url, token, if_match=etag, user_email=user_email)
    return {"deleted": business_process_id}


def delete_solution_process(
    token: str, solution_process_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    """Delete a solution process. OData — DELETE needs If-Match (auto-fetched)."""
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses/{solution_process_id}"
    etag = _resolve_etag(url, token, if_match)
    _delete(url, token, if_match=etag, user_email=user_email)
    return {"deleted": solution_process_id}


def delete_scope(
    token: str, scope_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    """Delete a scope. OData; spec confirms no If-Match needed (honoured if given)."""
    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes/{scope_id}"
    _delete(url, token, if_match=if_match, user_email=user_email)
    return {"deleted": scope_id}


def delete_test_case(
    token: str,
    test_case_id: str,
    force: bool = False,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Delete a manual test case. OData — DELETE needs If-Match (= modifiedAt).

    Plain DELETE fails (412) if the test case has execution history. Set
    `force=True` to call the force-delete action, which also removes test runs
    and results (requires the calm-api.testcases.force-delete scope).
    """
    base = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases/{test_case_id}"
    etag = _tm_if_match(if_match)
    if force:
        action_url = f"{base}/api.v1.ExternalServiceAPI.forceDeletionIncludingTestRunsAndResults"
        _write("POST", action_url, token, {}, if_match=etag, user_email=user_email)
        return {"deleted": test_case_id, "force": True}
    _delete(base, token, if_match=etag, user_email=user_email)
    return {"deleted": test_case_id}


# ===========================================================================
# Sub-entity write functions
# ===========================================================================

# --- Generic escape hatch ---------------------------------------------------

def api_write(
    token: str,
    method: str,
    path: str,
    body: dict | list | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> Any:
    """Low-level POST/PATCH to any CALM API path (escape hatch for endpoints
    without a dedicated tool). `path` is relative to the tenant base URL, e.g.
    "api/calm-tasks/v1/tasks/{id}/comments". Returns the parsed response or a
    small ack. Pass `if_match` where the target service requires an ETag.
    """
    url = f"{_base_url(base_url)}/{path.lstrip('/')}"
    result = _write(method.upper(), url, token, body if body is not None else {}, if_match=if_match, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "method": method.upper(), "path": path}


def api_delete(token: str, path: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Low-level DELETE to any CALM API path (escape hatch). `path` is relative to
    the tenant base URL. Pass `if_match` where the target service requires an ETag.
    """
    url = f"{_base_url(base_url)}/{path.lstrip('/')}"
    _delete(url, token, if_match=if_match, user_email=user_email)
    return {"deleted": path}


# --- Task sub-entities (plain REST, no If-Match) ---------------------------

def create_task_relation(
    token: str, task_id: str, relation_task_id: str, relation_type: str = "0", base_url: str | None = None, user_email: str | None = None
) -> dict:
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}/relations"
    result = _write("POST", url, token, {"type": relation_type, "relationTaskId": relation_task_id}, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True}


def delete_task_relation(token: str, relation_id: str, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/relations/{relation_id}"
    _delete(url, token, user_email=user_email)
    return {"deleted": relation_id}


def set_task_tags(token: str, task_id: str, tags: list, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Replace a task's tag assignments. Tags look like "Group: Tag"."""
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/updateTags"
    result = _write("POST", url, token, {"taskId": task_id, "tags": tags}, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "taskId": task_id, "tags": tags}


def create_task_comment(
    token: str, task_id: str, text: str | None = None, extra_fields: dict | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    """Add a comment to a task. The exact body field is not documented; `text` is
    sent as-is and `extra_fields` can override/augment it."""
    body: dict[str, Any] = {}
    if text is not None:
        body["text"] = text
    if extra_fields:
        body.update(extra_fields)
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}/comments"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "submitted": body}


def update_task_comment(
    token: str, comment_id: str, text: str | None = None, extra_fields: dict | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    body: dict[str, Any] = {}
    if text is not None:
        body["text"] = text
    if extra_fields:
        body.update(extra_fields)
    if not body:
        raise ValueError("No fields to update — provide at least one field.")
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/comments/{comment_id}"
    result = _write("PATCH", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"updated": comment_id}


def delete_task_comment(token: str, comment_id: str, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/comments/{comment_id}"
    _delete(url, token, user_email=user_email)
    return {"deleted": comment_id}


# --- Project timeboxes (plain REST, no If-Match) ---------------------------

def create_timebox(
    token: str,
    project_id: str,
    name: str | None = None,
    timebox_type: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    closed: bool | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if timebox_type is not None:
        body["type"] = timebox_type
    if start_date is not None:
        body["startDate"] = start_date
    if end_date is not None:
        body["endDate"] = end_date
    if closed is not None:
        body["closed"] = closed
    if extra_fields:
        body.update(extra_fields)
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/timeboxes"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "submitted": body}


def update_timebox(
    token: str,
    timebox_id: str,
    name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    closed: bool | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if start_date is not None:
        body["startDate"] = start_date
    if end_date is not None:
        body["endDate"] = end_date
    if closed is not None:
        body["closed"] = closed
    if extra_fields:
        body.update(extra_fields)
    if not body:
        raise ValueError("No fields to update — provide at least one field.")
    url = f"{_base_url(base_url)}/api/calm-projects/v1/timeboxes/{timebox_id}"
    result = _write("PATCH", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"updated": timebox_id}


def delete_timebox(token: str, timebox_id: str, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = f"{_base_url(base_url)}/api/calm-projects/v1/timeboxes/{timebox_id}"
    _delete(url, token, user_email=user_email)
    return {"deleted": timebox_id}


# --- Process management: scope assignments & scenario versions -------------

def assign_scenario_versions(token: str, scope_id: str, version_ids: list, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Assign one or more solution-scenario versions to a scope."""
    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes/{scope_id}/solutionScenarioVersions"
    body = {"value": [{"id": v} for v in version_ids]}
    result = _write("POST", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "scopeId": scope_id}


def update_scope_assignments(token: str, assignments: list, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Scope/unscope solution processes. Each assignment is a dict with
    scopeId, solutionScenarioVersionId, solutionProcessVersionId, isScoped
    (required) and an optional statusId
    (EMPTY/DESIGN/REALIZATION/PRODUCTION/MAINTENANCE/OBSOLETE)."""
    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/solutionProcesses/scopeAssignments"
    result = _write("PATCH", url, token, {"value": assignments}, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "count": len(assignments)}


# --- Test management: activities & actions (OData, If-Match = modifiedAt) ---

def _tm_url(base_url: str | None, path: str) -> str:
    return f"{_base_url(base_url)}/api/calm-testmanagement/v1/{path}"


def create_test_action(
    token: str,
    activity_id: str,
    title: str,
    description: str | None = None,
    expected_result: str | None = None,
    sequence: int | None = None,
    is_evidence_required: bool | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create an action under an activity (POST /Activities/{id}/toActions)."""
    body: dict[str, Any] = {"title": title}
    if description is not None:
        body["description"] = description
    if expected_result is not None:
        body["expectedResult"] = expected_result
    if sequence is not None:
        body["sequence"] = sequence
    if is_evidence_required is not None:
        body["isEvidenceRequired"] = is_evidence_required
    url = _tm_url(base_url, f"Activities/{activity_id}/toActions")
    result = _write("POST", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "submitted": body}


def update_test_action(
    token: str,
    action_id: str,
    title: str | None = None,
    description: str | None = None,
    expected_result: str | None = None,
    sequence: int | None = None,
    is_evidence_required: bool | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if description is not None:
        body["description"] = description
    if expected_result is not None:
        body["expectedResult"] = expected_result
    if sequence is not None:
        body["sequence"] = sequence
    if is_evidence_required is not None:
        body["isEvidenceRequired"] = is_evidence_required
    if not body:
        raise ValueError("No fields to update — provide at least one field.")
    url = _tm_url(base_url, f"Actions/{action_id}")
    etag = _tm_if_match(if_match)
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"updated": action_id}


def delete_test_action(token: str, action_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = _tm_url(base_url, f"Actions/{action_id}")
    etag = _tm_if_match(if_match)
    _delete(url, token, if_match=etag, user_email=user_email)
    return {"deleted": action_id}


def update_test_activity(
    token: str,
    activity_id: str,
    title: str | None = None,
    sequence: int | None = None,
    is_in_scope: bool | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if sequence is not None:
        body["sequence"] = sequence
    if is_in_scope is not None:
        body["isInScope"] = is_in_scope
    if not body:
        raise ValueError("No fields to update — provide at least one field.")
    url = _tm_url(base_url, f"Activities/{activity_id}")
    etag = _tm_if_match(if_match)
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"updated": activity_id}


def delete_test_activity(token: str, activity_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = _tm_url(base_url, f"Activities/{activity_id}")
    etag = _tm_if_match(if_match)
    _delete(url, token, if_match=etag, user_email=user_email)
    return {"deleted": activity_id}
