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
# Internal helper
# ---------------------------------------------------------------------------

def _get(url: str, token: str) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    payload = json.dumps({"session_id": str(uuid.uuid4())})
    resp = requests.get(url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
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
