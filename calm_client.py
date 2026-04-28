"""
Cloud ALM HTTP client.

This module is a 1:1 port of the standalone Python functions used by the
existing Syntax GenAI Studio agent (get_calm_tasks, get_calm_projects, ...).

Keeping the HTTP logic in its own module means:
  - The MCP server (server.py) stays small and only handles MCP plumbing.
  - The same functions can be unit-tested without spinning up MCP.
  - You can later swap `requests` for `httpx`/async without touching server.py.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default CALM tenant used by the existing agent. The MCP server overrides
# this at runtime from the CALM_BASE_URL environment variable so the same
# code can be pointed at a different client tenant without changes.
DEFAULT_BASE_URL = "https://illumiti-corp-cloudalm.eu10.alm.cloud.sap"

# Default token endpoint for the client_credentials fallback flow. The MCP
# server overrides this from CALM_AUTH_URL.
DEFAULT_AUTH_URL = (
    "https://illumiti-corp-cloudalm.authentication.eu10.hana.ondemand.com"
    "/oauth/token?grant_type=client_credentials"
)

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
    """Issue a GET to a CALM API endpoint and return the parsed JSON body.

    A new session_id is generated per call (matches behavior of the original
    agent functions) and sent as the request body. The Authorization header
    uses the bearer token supplied by the caller.
    """
    headers = {"Authorization": f"Bearer {token}"}
    payload = json.dumps({"session_id": str(uuid.uuid4())})
    resp = requests.get(url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Token (optional client_credentials fallback)
# ---------------------------------------------------------------------------

def fetch_token(basic_auth: str, auth_url: str = DEFAULT_AUTH_URL) -> str:
    """Fetch an OAuth2 access token via client_credentials.

    `basic_auth` must be the full base64-encoded "client_id:client_secret"
    string (i.e. exactly what goes after `Basic ` in the Authorization
    header). Mirrors the original `get_calm_token` function.
    """
    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    resp = requests.post(auth_url, headers=headers, data="", timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("access_token")


# ---------------------------------------------------------------------------
# CALM read functions
# ---------------------------------------------------------------------------

def get_tasks(project_id: str, token: str, base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    url = f"{base_url}/api/calm-tasks/v1/tasks?projectId={project_id}"
    result = _get(url, token)
    parsed = []
    for item in result:
        parsed.append({
            "ID": item.get("id"),
            "Title": item.get("title"),
            "Type": TASK_TYPE_MAP.get(item.get("type"), item.get("type")),
            "Status": TASK_STATUS_MAP.get(item.get("status"), item.get("status")),
        })
    return parsed


def get_projects(token: str, base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    url = f"{base_url}/api/calm-projects/v1/projects"
    result = _get(url, token)
    parsed = []
    for item in result:
        parsed.append({
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Status": PROJECT_STATUS_MAP.get(item.get("status"), item.get("status")),
            "Purpose": item.get("purpose"),
        })
    return parsed


def get_business_processes(token: str, base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    url = f"{base_url}/api/calm-processauthoring/v1/businessProcesses"
    result = _get(url, token)
    return [
        {
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Description": item.get("description"),
        }
        for item in result.get("value", [])
    ]


def get_solution_processes(token: str, base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    url = f"{base_url}/api/calm-processauthoring/v1/solutionProcesses"
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


def get_scopes(token: str, base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    url = f"{base_url}/api/calm-processmanagement/v1/scopes"
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


def get_test_cases(token: str, base_url: str = DEFAULT_BASE_URL) -> list[dict]:
    url = f"{base_url}/api/calm-testmanagement/v1/ManualTestCases"
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
