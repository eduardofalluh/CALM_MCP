"""End-to-end MCP test for the CALM server (consolidated `calm_resource` surface).

Spawns server.py as a stdio subprocess, connects with the official MCP client,
and drives the *real* stack — MCP protocol -> `calm_resource` -> `src/calm/client.py`
-> HTTP (monkey-patched via a tiny `requests` shim so we never hit SAP). This is
the only test that exercises the full runtime path end-to-end, so it is the one
that would catch an argument-shift regression in the write branches at the
protocol level (the class of bug the consolidation originally introduced).

Covers:
  - tools/list            (consolidated surface advertised, no legacy CRUD tools)
  - calm_health           (token / base_url resolution)
  - calm_resource reads   (projects, tasks + type filter, requirements, teams +
                           project filter [reported bug], processes, timeboxes,
                           scopes, tags, features, project_users, customization)
  - write guard           (create blocked when CALM_ENABLE_WRITES is off)
  - calm_resource writes  (task create/update/delete, requirement create,
                           business_process create/update/delete [ETag],
                           scope create/update/delete, test_case create/delete,
                           timebox create, tags create [reported bug],
                           features create)
  - escape hatch          (calm_api_write / calm_api_delete)
  - BTP Test Management    (tm_health, statistics, test cases, requirements,
                           odata read + write)

Run with:    ./venv/bin/python tests/test_server.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
ROOT = HERE.parent

FAKE_PROJECTS_PAYLOAD = json.dumps([
    {"id": "P001", "name": "Test Project A", "status": "O", "purpose": "Build", "operationalStatus": "In Progress"},
    {"id": "P002", "name": "Test Project B", "status": "C", "purpose": "Run", "operationalStatus": "Completed"},
])

# The requests shim. Authored as a normal module string (not concatenated
# fragments) so the URL routing order is easy to read and maintain. Order
# matters: more specific paths (…/teams, …/tags) must be checked BEFORE the
# generic `/projects/` single-entity fallback, or they get shadowed.
_SHIM_SRC = '''\
import json, re, requests


class _FakeResp:
    def __init__(self, text, status_code=200, headers=None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}
        self.reason = "Bad Request" if status_code >= 400 else "OK"

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.text)


_PAYLOAD = %(payload)r

_TEAMS = {
    "P001": [{"id": "TEAM1", "name": "Development Team", "description": "Backend developers",
              "projectId": "P001", "members": ["U1", "U2"]}],
    "P002": [{"id": "TEAM2", "name": "QA Team", "description": "Quality assurance",
              "projectId": "P002", "members": ["U3"]}],
}


_CSDL = (
    '<edmx:Edmx Version="4.0"><edmx:DataServices><Schema Namespace="api.v1.S">'
    '<EntityContainer Name="C">'
    '<EntitySet Name="Documents" EntityType="api.v1.S.Documents"/>'
    '<EntitySet Name="AutomatedTestCases" EntityType="api.v1.S.AutomatedTestCases"/>'
    '</EntityContainer>'
    '<EntityType Name="Documents"><Key><PropertyRef Name="uuid"/></Key>'
    '<Property Name="uuid" Type="Edm.Guid" Nullable="false"/>'
    '<Property Name="displayId" Type="Edm.String"/><Property Name="title" Type="Edm.String"/>'
    '<Property Name="content" Type="Edm.String"/><Property Name="projectId" Type="Edm.String"/>'
    '<Property Name="statusCode" Type="Edm.String"/><Property Name="typeCode" Type="Edm.String"/>'
    '<Property Name="createdAt" Type="Edm.DateTimeOffset"/>'
    '</EntityType>'
    '<EntityType Name="AutomatedTestCases"><Key><PropertyRef Name="uuid"/></Key>'
    '<Property Name="uuid" Type="Edm.Guid" Nullable="false"/><Property Name="title" Type="Edm.String"/>'
    '<Property Name="projectId" Type="Edm.String"/><Property Name="priorityCode" Type="Edm.Int32"/>'
    '<Property Name="displayId" Type="Edm.String"/>'
    '</EntityType></Schema></edmx:DataServices></edmx:Edmx>'
)
_DOC = {"uuid": "0b1c2d3e-4f50-4a61-8b72-9c83d4e5f601", "displayId": "7-101",
        "title": "Solution design", "content": "<p>Design <b>text</b></p>", "projectId": "P001",
        "statusCode": "IN_PROGRESS", "typeCode": "SDD"}


def _fake_get(url, *a, **kw):
    # --- OData $metadata (Documents / Test Management schemas) --------------
    if url.endswith("/$metadata"):
        if "calm-documents" in url or "calm-testmanagement" in url:
            return _FakeResp(_CSDL, headers={"Content-Type": "application/xml"})
        return _FakeResp("{}", status_code=403)
    if "calm-documents/v1/Documents" in url:
        if "/Documents/" in url:
            return _FakeResp(json.dumps(_DOC), headers={"ETag": 'W/"d1"'})
        return _FakeResp(json.dumps({"value": [_DOC, dict(_DOC, uuid="0b1c2d3e-4f50-4a61-8b72-9c83d4e5f602",
                                                         displayId="7-102", title="Cutover plan")]}))
    if "calm-testmanagement/v1/AutomatedTestCases" in url:
        return _FakeResp(json.dumps({"value": [
            {"uuid": "4f506172-8394-4ea5-b6c7-d8e9f0011223", "title": "O2C smoke", "projectId": "P001",
             "priorityCode": 20, "displayId": "8-2-17"}]}))

    # --- BTP Test Management OData (tm_* tools) — check FIRST ---------------
    if url.rstrip("/").endswith("/health") and "test-management" not in url:
        return _FakeResp(json.dumps({"status": "UP", "db": "ok"}))
    if "/odata/v4/test-management" in url:
        if "TestCases('" in url:
            return _FakeResp(json.dumps({"id": "TC-1", "title": "TM case", "is_prepared": False,
                                         "updated_at": "2026-08-01T00:00:00Z"}),
                             headers={"ETag": 'W/"tm-1"'})
        if "Requirements('" in url:
            return _FakeResp(json.dumps({"id": "RQ-1", "tr_id": "TR-1", "short_desc": "Req"}),
                             headers={"ETag": 'W/"tm-2"'})
        if "Statistics" in url:
            return _FakeResp(json.dumps({"value": [
                {"scope": "TestCases", "metric": "total", "count": 42},
                {"scope": "Requirements", "metric": "total", "count": 7},
            ]}))
        if "TestCases" in url:
            return _FakeResp(json.dumps({"value": [
                {"id": "TC-1", "external_id": "TC-0001", "title": "TM case",
                 "scenario_type": "positive", "updated_at": "2026-08-05T00:00:00Z"},
            ], "@odata.count": 1}))
        if "Requirements" in url:
            return _FakeResp(json.dumps({"value": [
                {"id": "RQ-1", "tr_id": "TR-1", "wricef": "R", "short_desc": "Req"},
            ]}))
        return _FakeResp(json.dumps({"value": []}))

    # --- Teams (MUST come before the generic /projects/ fallback) ----------
    m = re.search(r"/projects/([^/]+)/teams", url)
    if m:
        return _FakeResp(json.dumps(_TEAMS.get(m.group(1), [])))
    if "calm-projects/v1/teams" in url:
        pm = re.search(r"projectId=([^&]+)", url)
        if pm:
            return _FakeResp(json.dumps(_TEAMS.get(pm.group(1), [])))
        return _FakeResp(json.dumps([t[0] for t in _TEAMS.values()]))

    # --- Project sub-resources (before generic /projects/ single-entity) ---
    if "/projects/" in url and "/tags" in url:
        return _FakeResp(json.dumps([
            {"id": "TAG1", "projectId": "P001", "group": "Scope", "tag": "Baseline"},
            {"id": "TAG2", "projectId": "P001", "group": "Tshirt size", "tag": "L"},
        ]))
    # Features have their own service (features.read); the project-path variant
    # below is not the real Features API. Match the service endpoint first.
    if "calm-features/v1/Features" in url:
        return _FakeResp(json.dumps([
            {"id": "F1", "projectId": "P001", "name": "User Management", "description": "auth", "status": "Active"},
            {"id": "F2", "projectId": "P001", "name": "Reporting", "description": "BI", "status": "Planned"},
            {"id": "F9", "projectId": "P999", "name": "Other project feature", "description": "x", "status": "Active"},
        ]))
    if "/projects/" in url and "/features" in url:
        return _FakeResp(json.dumps([
            {"id": "F1", "projectId": "P001", "name": "User Management", "description": "auth", "status": "Active"},
            {"id": "F2", "projectId": "P001", "name": "Reporting", "description": "BI", "status": "Planned"},
        ]))
    if "/projects/" in url and "/users" in url:
        return _FakeResp(json.dumps([
            {"id": "U1", "email": "eduardo.falluh@syntax.com", "name": "Eduardo Falluh", "role": "PM", "active": True},
            {"id": "U2", "email": "jane.doe@syntax.com", "name": "Jane Doe", "role": "Developer", "active": True},
        ]))
    if "/projects/" in url and "/customization" in url:
        return _FakeResp(json.dumps({
            "workstreams": ["A", "B"], "deliverables": ["MVP", "Final"],
            "customFields": [{"name": "Priority", "values": ["High", "Low"]}],
        }))
    if "/projects/" in url and "/timeboxes" in url:
        return _FakeResp(json.dumps([
            {"id": "TB1", "projectId": "P001", "name": "Sprint 1", "type": 0,
             "startDate": "2026-07-01", "endDate": "2026-07-14", "closed": False},
        ]))

    # --- Processes lists ---------------------------------------------------
    if "processauthoring/v1/businessProcesses" in url and "/businessProcesses/" not in url:
        return _FakeResp(json.dumps({"value": [
            {"id": "BP1", "name": "Order to Cash", "description": "O2C"},
        ]}))
    if "processauthoring/v1/solutionProcesses" in url and "/solutionProcesses/" not in url:
        return _FakeResp(json.dumps({"value": [
            {"id": "SP1", "name": "SD Sales", "description": "Sales"},
        ]}))

    # --- Test case detail read (step tree) — BEFORE the single-entity route
    if "ManualTestCases" in url and "toActivities" in url:
        case = {
            "uuid": "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d", "displayId": "8-1-1380",
            "projectId": "P001", "title": "FRICEW 112 boundary", "priorityCode": 30,
            "isPrepared": True, "toTagAssignments": [{"label": "SIT"}],
            "toTaskAssignments": [{"uuid": "TA1", "taskId": "K1", "taskDisplayId": "3-1", "type": "CALMREQU"}],
            "toActivities": [{
                "uuid": "A1", "title": "Log on", "sequence": 1, "isInScope": True,
                "toActions": [
                    {"uuid": "X2", "title": "Open app", "sequence": 2,
                     "description": "<p>Open <b>Manage License Numbers</b></p>",
                     "expectedResult": "<p>App opens</p>"},
                    {"uuid": "X1", "title": "Log on", "sequence": 1,
                     "description": "Log on", "expectedResult": "Launchpad opens"},
                ],
            }],
        }
        if "displayId" in url:
            return _FakeResp(json.dumps({"value": [case]}))
        return _FakeResp(json.dumps(case))
    # Test Management service document (test-plan discovery): no plan entity set.
    if url.rstrip("/").endswith("/calm-testmanagement/v1"):
        return _FakeResp(json.dumps({"value": [
            {"name": "ManualTestCases", "url": "ManualTestCases"},
            {"name": "Activities", "url": "Activities"},
            {"name": "Actions", "url": "Actions"},
        ]}))
    # Analytics DataSet: DP_TESTS rows in CALM's pivoted dN/mN layout.
    if "calm-analytics" in url and "DataSet" in url:
        if "DP_TESTS" not in url:
            return _FakeResp(json.dumps({"value": []}))
        return _FakeResp(json.dumps({"value": [
            {"provider": "DP_TESTS", "date": "2026-10-22", "d1k": "testcaseID", "d1v": "8-1-1380",
             "d2k": "status", "d2v": "Failed", "d3k": "project", "d3v": "P001",
             "m1k": "total", "m1v": 1},
        ]}))

    # --- Single-entity GETs used for ETag auto-fetch on update/delete ------
    if "/ManualTestCases/" in url or "/Activities/" in url or "/Actions/" in url:
        return _FakeResp(json.dumps({"uuid": "TC-1", "title": "old", "modifiedAt": "2025-11-17T15:51:04Z"}))
    if "/businessProcesses/" in url or "/solutionProcesses/" in url or "/scopes/" in url:
        return _FakeResp(json.dumps({"id": "X", "name": "old"}), headers={"ETag": 'W/"1"'})

    # --- Task list / single task -------------------------------------------
    if "calm-tasks/v1/tasks" in url and "%%24" in url:
        # SAP's Tasks API is plain REST and refuses OData options (live, 2026-10-30).
        name = url.split("%%24", 1)[1].split("=", 1)[0]
        return _FakeResp(json.dumps({"message": f'Query parameter "${name}" is not supported yet.'}),
                         status_code=400)
    if "/tasks/" in url:
        # Single-task GET used to auto-detect type for status-by-label updates.
        return _FakeResp(json.dumps({"id": "T1", "type": "CALMTASK", "title": "old"}))
    if "calm-tasks/v1/tasks" in url:
        return _FakeResp(json.dumps([
            {"id": "R1", "displayId": "3-60729", "title": "Req A", "type": "CALMREQU", "status": "CIPREQUOPEN"},
            {"id": "K1", "title": "Task B", "type": "CALMTASK", "status": "CIPTKOPEN",
             "responsibleTeamId": "TEAM1", "timeboxId": "TB1", "effort": 8.0},
        ]))

    # --- Generic /projects/ single-entity (etag body field) ----------------
    if "/projects/" in url:
        return _FakeResp(json.dumps({"id": "P-1", "name": "old", "etag": "1755245808454"}))

    # --- Default: project list ---------------------------------------------
    return _FakeResp(_PAYLOAD)


def _fake_request(method, url, *a, **kw):
    # Echo the submitted body back with a generated id, mimicking a create/update.
    body = json.loads(kw.get("data") or "{}")
    body.setdefault("id", "T999")
    return _FakeResp(json.dumps(body))


requests.get = _fake_get
requests.request = _fake_request
''' % {"payload": FAKE_PROJECTS_PAYLOAD}


def _write_shim() -> Path:
    shim_dir = ROOT / ".test_shim"
    shim_dir.mkdir(exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(_SHIM_SRC)
    return shim_dir


def _make_params(shim_dir: Path, extra_env: dict | None = None) -> StdioServerParameters:
    env = {
        **os.environ,
        "CALM_TOKEN": "fake-local-token-for-tests",
        "IDENTITY_ZONE": "test-cloudalm",
        "REGION_ZONE": "us10",
        "CALM_BASE_URL": "",
        "CALM_AUTH_URL": "",
        # Ensure client-credentials mode is OFF so tests use the env-var path
        "CALM_CLIENT_ID": "",
        "CALM_CLIENT_SECRET": "",
        # Writes off by default; individual tests opt in via extra_env.
        "CALM_ENABLE_WRITES": "",
        # TM OData off by default; individual tests opt in via extra_env.
        "TM_BASE_URL": "",
        "TM_TOKEN_URL": "",
        "TM_CLIENT_ID": "",
        "TM_CLIENT_SECRET": "",
        "TM_TOKEN": "",
        "TM_ENABLE_WRITES": "",
        "PYTHONPATH": f"{ROOT}{os.pathsep}{shim_dir}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }
    if extra_env:
        env.update(extra_env)
    return StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=env,
    )


def _payload(res):
    """structured_content, falling back to parsing the text content block.

    Returns {} for an error result so a single failed check can be reported
    without aborting the whole end-to-end run.
    """
    if getattr(res, "is_error", False):
        return {}
    sc = res.structured_content
    if sc is None and res.content:
        try:
            sc = json.loads(res.content[0].text)
        except (ValueError, AttributeError):
            sc = {}
    # FastMCP wraps every non-annotated return (list AND dict) in a
    # {"result": ...} envelope — unwrap it to get the real payload.
    if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
        return sc["result"]
    return sc if sc is not None else {}


def _list(res):
    """Unwrap a list-returning tool result to the underlying list."""
    sc = _payload(res)
    return sc if isinstance(sc, list) else []


async def _call(session, resource, operation, **kw):
    args = {"resource": resource, "operation": operation}
    args.update(kw)
    return await session.call_tool("calm_resource", args)


async def main() -> int:
    shim_dir = _write_shim()
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {label}{(' - ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    # ================= Reads + write guard (writes OFF) =================
    print("Connecting to CALM MCP server over stdio (writes OFF)...")
    async with stdio_client(_make_params(shim_dir)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Session initialized.\n")

            # ---- Test 1: tools/list ---------------------------------------
            print("Test 1: tools/list advertises the consolidated surface")
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}

            check("calm_resource advertised", "calm_resource" in names)
            required = {"calm_health", "calm_api_write", "calm_api_delete", "tm_health"}
            check("kept specialized tools advertised", required.issubset(names),
                  f"missing {sorted(required - names)}")

            legacy = {
                "get_calm_projects", "get_calm_tasks", "create_calm_task",
                "update_calm_task", "delete_calm_task", "get_calm_scopes",
                "create_calm_scope", "get_calm_test_cases", "create_calm_tag",
                "get_calm_teams",
            }
            leaked = legacy & names
            check("no legacy CRUD tools advertised", not leaked, f"leaked {sorted(leaked)}")

            for t in tools.tools:
                check(f"'{t.name}' has a description", bool(t.description and t.description.strip()))

            cr = next(t for t in tools.tools if t.name == "calm_resource")
            schema = getattr(cr, "inputSchema", None) or getattr(cr, "input_schema", None) or {}
            props = schema.get("properties", {})
            check("calm_resource exposes resource+operation params",
                  "resource" in props and "operation" in props, f"props={sorted(props)}")

            # ---- Test 2: calm_health --------------------------------------
            print("\nTest 2: calm_health returns expected diagnostic")
            res = await session.call_tool("calm_health", {})
            health = _payload(res)
            check("server name", health.get("server") == "sap-cloud-alm")
            check("token configured", health.get("token_configured") is True)
            check("base_url derived from BTP zone config",
                  health.get("base_url") == "https://test-cloudalm.us10.alm.cloud.sap",
                  f"got {health.get('base_url')}")

            # ---- Test 3: reads via calm_resource --------------------------
            print("\nTest 3: calm_resource reads round-trip through client.py")
            projects = _list(await _call(session, "projects", "list"))
            check("projects is a list of 2", isinstance(projects, list) and len(projects) == 2)
            check("project field contract",
                  set(projects[0].keys()) == {"ID", "Name", "Status", "Purpose", "OperationalStatus"},
                  f"got {sorted(projects[0].keys())}")
            check("project status label mapped (O->Active)", projects[0]["Status"] == "Active",
                  f"got {projects[0]['Status']}")

            tasks = _list(await _call(session, "tasks", "list", project_id="P001"))
            check("tasks is a list of 2", isinstance(tasks, list) and len(tasks) == 2)
            k1 = next((t for t in tasks if t.get("ID") == "K1"), {})
            check("task carries team + sprint by name (per-sprint/per-team grouping)",
                  k1.get("Responsible Team") == "Development Team" and k1.get("Timebox") == "Sprint 1"
                  and k1.get("Responsible Team ID") == "TEAM1" and k1.get("Effort") == 8.0,
                  f"got {k1}")
            r1 = next((t for t in tasks if t.get("ID") == "R1"), {})
            check("task without team/sprint stays unassigned",
                  r1.get("Responsible Team") is None and r1.get("Timebox") is None, f"got {r1}")
            summary = _payload(await _call(session, "tasks", "list", project_id="P001",
                                           data={"summarize_by": ["Timebox", "Responsible Team"]}))
            check("tasks summarize_by returns the exact per-sprint/per-team table",
                  isinstance(summary, dict) and summary.get("Total Tasks") == 2
                  and summary.get("Total Effort") == 8.0
                  and {"Timebox": "Sprint 1", "Responsible Team": "Development Team", "Tasks": 1,
                       "Effort": 8.0, "Tasks Without Effort": 0} in summary.get("Groups", []),
                  f"got {summary}")
            one_sprint = _list(await _call(session, "tasks", "list", project_id="P001",
                                           data={"timebox": "sprint 1"}))
            check("tasks timebox filter keeps only that sprint",
                  [t.get("ID") for t in one_sprint] == ["K1"], f"got {one_sprint}")
            found = _payload(await _call(session, "tasks", "list", project_id="P001",
                                         data={"search": "task b", "fields": ["Title"]}))
            check("tasks search returns the match with totals (duplicate check)",
                  isinstance(found, dict) and found.get("Total Matching") == 1
                  and found.get("Tasks") == [{"ID": "K1", "Title": "Task B"}], f"got {found}")
            res = await _call(session, "tasks", "list", project_id="P001",
                              data={"search": "task b", "status": "Open"})
            refused = _payload(res)
            check("tasks list answers an unknown data key (no tool error, nothing listed)",
                  res.is_error is not True and isinstance(refused, dict)
                  and refused.get("status") == "invalid_request"
                  and "does not support" in refused.get("message", ""), f"got {str(refused)[:160]}")
            res = await _call(session, "requirements", "list")
            missing = _payload(res)
            check("a read missing project_id answers what is missing (no tool error)",
                  res.is_error is not True and missing.get("status") == "invalid_request"
                  and "project_id is required" in missing.get("message", ""), f"got {str(missing)[:160]}")
            res = await _call(session, "tasks", "list", project_id="P001", task_type="Task")
            check("tasks list takes an everyday type name ('Task')",
                  res.is_error is not True and [t.get("ID") for t in _list(res)] == ["K1"],
                  f"got {str(_payload(res))[:160]}")
            one = _payload(await _call(session, "tasks", "get",
                                       resource_id="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"))
            check("tasks get by UUID returns one task row",
                  isinstance(one, dict) and one.get("ID") == "T1" and "Title" in one, f"got {one}")

            reqs = _list(await _call(session, "requirements", "list", project_id="P001"))
            check("requirements read returns a list", isinstance(reqs, list))
            res = await _call(session, "requirements", "get", project_id="P001", resource_id="3-60729")
            one_req = _payload(res)
            check("requirements get by display ID (the 2026-10-26 traced call) returns it",
                  res.is_error is not True and isinstance(one_req, dict) and one_req.get("ID") == "R1",
                  f"got {res.content[0].text[:160] if res.content else ''}")
            proj = _payload(await _call(session, "projects", "get", resource_id="test project a"))
            check("projects get by name returns the project",
                  isinstance(proj, dict) and proj.get("ID") == "P001", f"got {proj}")
            by_name = _list(await _call(session, "tasks", "list", project_id="Test Project A"))
            check("project name in project_id resolves to the project (same tasks as by ID)",
                  [t.get("ID") for t in by_name] == [t.get("ID") for t in tasks], f"got {by_name}")
            res = await _call(session, "tasks", "list", project_id="No Such Project")
            miss = _payload(res)
            check("unknown project name on a read is an answer naming the real projects (no tool error)",
                  res.is_error is not True and isinstance(miss, dict) and miss.get("status") == "not_found"
                  and "Test Project A" in miss.get("message", ""), f"got {miss}")
            res = await _call(session, "requirements", "get", project_id="P001", resource_id="3-99999")
            miss = _payload(res)
            check("requirements get on a missing ID is a not_found answer (no tool error)",
                  res.is_error is not True and isinstance(miss, dict) and miss.get("status") == "not_found",
                  f"got {miss}")

            # The reported bug: project-scoped teams read.
            teams = _list(await _call(session, "teams", "list", project_id="P001"))
            check("project teams returns a list", isinstance(teams, list) and len(teams) == 1,
                  f"got {teams}")
            check("team field mapped (projectId->Project ID)",
                  teams and teams[0].get("Project ID") == "P001" and teams[0].get("Name") == "Development Team",
                  f"got {teams}")
            teams_empty = _list(await _call(session, "teams", "list", project_id="P404"))
            check("unknown project teams returns empty list (not an error)",
                  isinstance(teams_empty, list) and teams_empty == [], f"got {teams_empty}")

            procs = _list(await _call(session, "processes", "list"))
            check("combined processes returns BP + SP", isinstance(procs, list) and len(procs) == 2,
                  f"got {procs}")

            timeboxes = _list(await _call(session, "timeboxes", "list", project_id="P001"))
            check("timeboxes read returns a list", isinstance(timeboxes, list) and len(timeboxes) == 1)

            tags = _list(await _call(session, "tags", "list", project_id="P001"))
            check("tags read returns a list of 2", isinstance(tags, list) and len(tags) == 2)

            features = _list(await _call(session, "features", "list", project_id="P001"))
            check("features read returns a list of 2", isinstance(features, list) and len(features) == 2)

            users = _list(await _call(session, "project_users", "list", project_id="P001"))
            check("project_users read returns a list", isinstance(users, list) and len(users) == 2)

            cust = _payload(await _call(session, "customization", "get", project_id="P001"))
            check("customization get returns a dict", isinstance(cust, dict) and "Workstreams" in cust, f"got {cust}")

            # Test-case detail: the steps an agent needs before raising a defect.
            tc = _payload(await _call(session, "test_cases", "get", resource_id="8-1-1380"))
            steps = tc.get("Steps") if isinstance(tc, dict) else None
            check("test case get by display ID returns numbered steps",
                  isinstance(steps, list) and [s.get("Step") for s in steps] == ["1.1", "1.2"],
                  f"got {steps}")
            check("step 1.2 instructions + expected result as plain text",
                  bool(steps) and len(steps) == 2
                  and steps[1].get("Instructions") == "Open Manage License Numbers"
                  and steps[1].get("Expected Result") == "App opens",
                  f"got {steps}")
            check("test case get keeps the list field contract",
                  isinstance(tc, dict) and tc.get("Display ID") == "8-1-1380"
                  and tc.get("Tags") == ["SIT"] and "Execution Results" in tc,
                  f"got {sorted(tc) if isinstance(tc, dict) else tc}")
            tc_uuid = _payload(await _call(session, "test_cases", "get",
                                           resource_id="3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"))
            check("test case get by UUID returns the same steps",
                  isinstance(tc_uuid, dict) and tc_uuid.get("Steps") == steps)
            check("test case get lists the requirements/tasks it covers",
                  tc_uuid.get("Linked Tasks") == [{"Task ID": "K1", "Task Display ID": "3-1",
                                                   "Type": "CALMREQU"}], f"got {tc_uuid.get('Linked Tasks')}")

            docs = _list(await _call(session, "documents", "list", project_id="P001"))
            check("documents list returns rows from the Documents service",
                  [d.get("Display ID") for d in docs] == ["7-101", "7-102"]
                  and docs[0].get("Title") == "Solution design" and "Content" not in docs[0],
                  f"got {docs}")
            doc = _payload(await _call(session, "documents", "get", project_id="P001", resource_id="7-101"))
            check("documents get by display ID returns the text as plain text",
                  isinstance(doc, dict) and doc.get("Content") == "Design text"
                  and doc.get("Status Code") == "IN_PROGRESS", f"got {doc}")
            res = await _call(session, "documents", "list", project_id="P001", data={"colour": "red"})
            refused = _payload(res)
            check("documents list answers an unknown field with the real field names",
                  res.is_error is not True and isinstance(refused, dict)
                  and refused.get("status") == "invalid_request"
                  and "statusCode" in refused.get("message", ""), f"got {str(refused)[:160]}")
            atcs = _list(await _call(session, "automated_test_cases", "list", project_id="P001"))
            check("automated test cases list with the priority label",
                  len(atcs) == 1 and atcs[0].get("Priority") == "High" and atcs[0].get("Display ID") == "8-2-17",
                  f"got {atcs}")
            feats = _list(await _call(session, "features", "list", project_id="P001"))
            check("features list still works when the Features schema can't be read",
                  [f.get("ID") for f in feats] == ["F1", "F2"] and feats[0].get("Name") == "User Management",
                  f"got {feats}")

            plans = _payload(await _call(session, "test_plans", "list"))
            check("test_plans reports unavailable (no plan entity) instead of failing",
                  isinstance(plans, dict) and plans.get("status") == "unavailable"
                  and "calm-api.testplans.read" in plans.get("message", ""),
                  f"got {plans}")

            runs = _list(await _call(session, "analytics", "list", project_id="P001",
                                     data={"provider": "DP_TESTS"}))
            check("analytics DP_TESTS returns unpivoted execution status",
                  len(runs) == 1 and runs[0].get("status") == "Failed"
                  and runs[0].get("testcaseID") == "8-1-1380",
                  f"got {runs}")

            # ---- Test 4: write guard blocks create when writes OFF --------
            print("\nTest 4: write guard blocks create when CALM_ENABLE_WRITES is off")
            res = await _call(session, "tasks", "create", project_id="P001",
                              data={"title": "Blocked", "task_type": "Project Task"})
            check("create blocked (is_error)", res.is_error is True)
            check("error mentions writes disabled",
                  "disabled" in (res.content[0].text.lower() if res.content else ""),
                  f"got {res.content[0].text if res.content else ''}")

    # ================= Writes ON =================
    print("\nConnecting again with CALM_ENABLE_WRITES=true (writes ON)...")
    async with stdio_client(_make_params(shim_dir, {"CALM_ENABLE_WRITES": "true"})) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ---- Test 5: writes via calm_resource -------------------------
            print("Test 5: calm_resource writes round-trip (no arg-shift crash)")

            res = await _call(session, "tasks", "create", project_id="P001",
                              data={"title": "New Task", "task_type": "Project Task", "status": "In Progress"})
            check("task create ok", res.is_error is not True, f"err {res.content[0].text if res.content else ''}")
            created = _payload(res)
            check("task create round-trips status label + id",
                  created.get("ID") == "T999" and created.get("Status") == "In Progress",
                  f"got {created}")

            res = await _call(session, "tasks", "update", project_id="P001", resource_id="T1",
                              data={"title": "Updated", "status": "in progress"})
            check("task update ok", res.is_error is not True, f"err {res.content[0].text if res.content else ''}")
            res = await _call(session, "requirements", "update", project_id="Test Project A",
                              resource_id="3-60729", data='{"title": "Updated by display ID"}')
            check("update by display ID + project name + data as JSON text",
                  res.is_error is not True, f"err {res.content[0].text if res.content else ''}")

            res = await _call(session, "tasks", "delete", project_id="P001", resource_id="T1",
                              data={"task_type": "Project Task"})
            check("task delete ok", res.is_error is not True, f"err {res.content[0].text if res.content else ''}")

            res = await _call(session, "requirements", "create", project_id="P001",
                              data={"title": "New Req", "sub_status": "In Specification"})
            check("requirement create ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            # Agent-style calls (2026-10-26 live replay): everyday names and values.
            res = await _call(session, "tasks", "create", project_id="P001", task_type="Task",
                              data={"name": "Agent task", "priority": "High", "sprint": "sprint 1",
                                    "dueDate": "2026-12-31T00:00:00Z", "colour": "red"})
            made = _payload(res)
            check("agent-style task create: type arg, name, priority label, sprint name, datetime",
                  res.is_error is not True and made.get("Title") == "Agent task"
                  and made.get("Type") == "Project Task" and made.get("Priority") == "High"
                  and made.get("Timebox ID") == "TB1" and made.get("DueDate") == "2026-12-31",
                  f"got {made}")
            check("a field that can't be written is reported, not dropped",
                  set((made.get("Not Written") or {})) == {"colour"}, f"got {made.get('Not Written')}")
            res = await _call(session, "requirements", "create", project_id="P001",
                              data={"title": "Req with ids", "priority": "Very High", "external_id": "FTS-001"})
            made = _payload(res)
            check("requirement create writes priority and external ID",
                  res.is_error is not True and made.get("Priority") == "Very High"
                  and made.get("External ID (FRICEF)") == "FTS-001", f"got {made}")
            res = await _call(session, "requirements", "update", project_id="P001", resource_id="T1",
                              data={"status": "In Progress"})
            upd = _payload(res)
            check("requirements update sends no type; status resolves on the item's own type",
                  res.is_error is not True and upd.get("Type") is None and upd.get("Status") == "In Progress",
                  f"got {upd}")
            res = await _call(session, "tasks", "create", project_id="P001",
                              data={"title": "Story for Req A", "task_type": "User Story", "parent_id": "3-60729"})
            made = _payload(res)
            check("a user story is linked under its requirement (a relation, as CALM links them)",
                  res.is_error is not True and made.get("Linked Under") == "R1"
                  and made.get("Parent ID") is None and "Not Written" not in made, f"got {made}")
            res = await _call(session, "requirements", "create", project_id="P001",
                              data={"title": "Req approval", "approval_status": "No Approval Required"})
            check("approval state by name is written as CALM's code",
                  res.is_error is not True and _payload(res).get("ApprovalState") == "No Approval Required",
                  f"got {_payload(res)}")
            res = await _call(session, "requirements", "create", project_id="P001",
                              data={"title": "Req bad approval", "approval_state": "Pending Customer Confirmation"})
            made = _payload(res)
            check("an approval state CALM doesn't have: saved without it and reported, naming the real ones",
                  res.is_error is not True and made.get("ApprovalState") is None
                  and "Ready for Approval" in str((made.get("Not Written") or {}).get("approval_state")), f"got {made}")
            res = await _call(session, "projects", "get", resource_id="project a")
            check("projects get takes part of a project's name",
                  res.is_error is not True and _payload(res).get("ID") == "P001", f"got {_payload(res)}")
            res = await _call(session, "task_comments", "create", resource_id="T1",
                              data={"content": "Created via Project Agent by A. Person."})
            check("a comment sent as data.content is posted with its words",
                  res.is_error is not True and _payload(res).get("text") == "Created via Project Agent by A. Person.",
                  f"got {_payload(res)}")

            res = await _call(session, "business_processes", "create", project_id="P001",
                              data={"name": "New BP", "description": "d"})
            check("business_process create ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")
            res = await _call(session, "business_processes", "update", project_id="P001", resource_id="BP1",
                              data={"name": "BP renamed"})
            check("business_process update ok (ETag auto-fetch)", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")
            res = await _call(session, "business_processes", "delete", project_id="P001", resource_id="BP1")
            check("business_process delete ok (no arg-shift into if_match)", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            res = await _call(session, "scopes", "create", project_id="P001",
                              data={"name": "New Scope"})
            check("scope create ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")
            res = await _call(session, "scopes", "delete", project_id="P001", resource_id="S1")
            check("scope delete ok (no arg-shift into if_match)", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            res = await _call(session, "test_cases", "create", project_id="P001",
                              data={"title": "TC", "scope_id": "S1", "priority": "High"})
            check("test_case create ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")
            # Missing scope_id must produce a clear error, not a crash.
            res = await _call(session, "test_cases", "create", project_id="P001", data={"title": "TC no scope"})
            check("test_case create without scope_id errors clearly", res.is_error is True)
            res = await _call(session, "test_cases", "delete", project_id="P001", resource_id="TC1",
                              data={"scope_id": "S1", "force": True})
            check("test_case delete ok (force)", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            res = await _call(session, "timeboxes", "create", project_id="P001",
                              data={"name": "Sprint 3", "start_date": "2026-08-01", "due_date": "2026-08-14"})
            check("timebox create ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            # ---- Tag creation: not exposed by SAP's public API ------------
            # Creating tag *definitions* has no scope in SAP's CALM public API,
            # so the tool returns a clear 'unavailable' explanation instead of a
            # raw 403. (Assigning existing tags to a task still works — see the
            # task_tags path.)
            res = await _call(session, "tags", "create", project_id="P001",
                              data={"group": "Scope", "tag": "MyNewTag"})
            check("tag create returns a result (not a hard error)", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")
            tag = _payload(res)
            check("tag create reports unavailable (SAP platform limitation)",
                  isinstance(tag, dict) and tag.get("status") == "unavailable"
                  and tag.get("resource") == "tags",
                  f"got {tag}")
            check("tag create points to the task_tags alternative",
                  isinstance(tag, dict) and "task_tags" in (tag.get("alternative") or ""),
                  f"got {tag}")

            res = await _call(session, "features", "create", project_id="P001",
                              data={"name": "New Feature", "description": "d"})
            check("feature create ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            res = await _call(session, "documents", "create", project_id="P001",
                              data={"title": "New design", "type": "SDD", "content": "<p>Hi</p>"})
            made = _payload(res)
            check("document create ok (schema field names, project filled in)",
                  res.is_error is not True and isinstance(made, dict) and made.get("Title") == "New design"
                  and made.get("Type Code") == "SDD" and made.get("Project ID") == "P001", f"got {made}")
            res = await _call(session, "documents", "update", project_id="P001", resource_id="7-101",
                              data={"status": "IN_REVIEW"})
            check("document update by display ID ok (ETag sent)", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")
            res = await _call(session, "documents", "delete",
                              resource_id="0b1c2d3e-4f50-4a61-8b72-9c83d4e5f601")
            check("document delete ok", res.is_error is not True and _payload(res) == {
                "deleted": "0b1c2d3e-4f50-4a61-8b72-9c83d4e5f601"}, f"got {_payload(res)}")

            # ---- Test 6: escape hatch -------------------------------------
            print("\nTest 6: calm_api_write / calm_api_delete escape hatch")
            res = await session.call_tool("calm_api_write", {
                "method": "POST",
                "path": "/api/calm-tasks/v1/tasks",
                "body": {"title": "Direct", "projectId": "P001"},
            })
            check("calm_api_write ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")
            res = await session.call_tool("calm_api_delete", {
                "path": "/api/calm-tasks/v1/tasks/T1",
            })
            check("calm_api_delete ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")
            res = await session.call_tool("calm_api_read", {
                "path": "api/calm-tasks/v1/tasks", "params": {"projectId": "P001", "$top": 1000}})
            got = _payload(res)
            check("calm_api_read leaves out $top the Tasks API refuses", res.is_error is not True
                  and got.get("Ignored Parameters") == ["$top"] and len(got.get("Result", [])) == 2,
                  f"got {got or (res.content[0].text if res.content else '')}")
            res = await session.call_tool("calm_api_read", {
                "path": "api/calm-tasks/v1/tasks", "params": {"projectId": "P001", "$filter": "x"}})
            got = _payload(res)
            check("calm_api_read $filter on tasks is an answer, not an error", res.is_error is not True
                  and got.get("status") == "invalid_request" and "calm_resource" in got.get("hint", ""),
                  f"got {got or (res.content[0].text if res.content else '')}")

    # ================= BTP Test Management (TM OData) =================
    print("\nConnecting with TM OData configured...")
    tm_env = {
        "TM_BASE_URL": "https://tm.example.com/odata/v4/test-management",
        "TM_TOKEN": "fake-tm-token",
        "TM_ENABLE_WRITES": "true",
    }
    async with stdio_client(_make_params(shim_dir, tm_env)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("Test 7: BTP Test Management tools")
            res = await session.call_tool("tm_health", {})
            check("tm_health ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            res = await session.call_tool("get_tm_statistics", {})
            check("get_tm_statistics ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            res = await session.call_tool("get_tm_test_cases", {})
            check("get_tm_test_cases ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            res = await session.call_tool("get_tm_requirements", {})
            check("get_tm_requirements ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            res = await session.call_tool("tm_odata_read", {"entity_set": "TestCases"})
            check("tm_odata_read ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

    # ================= No tenant configured: refuse, never guess one =================
    no_tenant_env = {"IDENTITY_ZONE": "", "REGION_ZONE": "", "CALM_IDENTITY_ZONE": "", "CALM_REGION_ZONE": ""}
    async with stdio_client(_make_params(shim_dir, no_tenant_env)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("\nTest 8: unconfigured tenant fails with a configuration error")
            health = _payload(await session.call_tool("calm_health", {}))
            check("calm_health still answers when unconfigured", health.get("server") == "sap-cloud-alm")
            check("calm_health reports base_url not configured",
                  str(health.get("base_url", "")).startswith("(not configured)"), f"got {health.get('base_url')}")

            res = await _call(session, "projects", "list")
            text = res.content[0].text if res.content else ""
            check("calm_resource refuses without a tenant", res.is_error is True, f"got {text[:120]}")
            check("error names the env vars to set", "IDENTITY_ZONE" in text and "REGION_ZONE" in text,
                  f"got {text[:200]}")

            res = await session.call_tool("get_calm_oauth_endpoints", {})
            text = res.content[0].text if res.content else ""
            check("get_calm_oauth_endpoints refuses without a tenant",
                  res.is_error is True and "IDENTITY_ZONE" in text, f"got {text[:200]}")

    # ================= Summary =================
    print("\n" + "=" * 70)
    if failures:
        print(f"❌ {len(failures)} check(s) FAILED:")
        for f in failures:
            print(f"   - {f}")
        print("=" * 70)
        return 1
    print("✅ ALL end-to-end checks PASSED")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
