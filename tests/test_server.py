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
                           features create, test_plans create)
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


def _fake_get(url, *a, **kw):
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

    # --- Test plans / processes lists --------------------------------------
    if "testmanagement" in url and "testPlans" in url:
        return _FakeResp(json.dumps([
            {"id": "TP1", "projectId": "P001", "name": "Enablement", "description": "d", "status": "Active"},
        ]))
    if "processauthoring/v1/businessProcesses" in url and "/businessProcesses/" not in url:
        return _FakeResp(json.dumps({"value": [
            {"id": "BP1", "name": "Order to Cash", "description": "O2C"},
        ]}))
    if "processauthoring/v1/solutionProcesses" in url and "/solutionProcesses/" not in url:
        return _FakeResp(json.dumps({"value": [
            {"id": "SP1", "name": "SD Sales", "description": "Sales"},
        ]}))

    # --- Single-entity GETs used for ETag auto-fetch on update/delete ------
    if "/ManualTestCases/" in url or "/Activities/" in url or "/Actions/" in url:
        return _FakeResp(json.dumps({"uuid": "TC-1", "title": "old", "modifiedAt": "2025-11-17T15:51:04Z"}))
    if "/businessProcesses/" in url or "/solutionProcesses/" in url or "/scopes/" in url:
        return _FakeResp(json.dumps({"id": "X", "name": "old"}), headers={"ETag": 'W/"1"'})

    # --- Task list / single task -------------------------------------------
    if "/tasks/" in url:
        # Single-task GET used to auto-detect type for status-by-label updates.
        return _FakeResp(json.dumps({"id": "T1", "type": "CALMTASK", "title": "old"}))
    if "calm-tasks/v1/tasks" in url:
        return _FakeResp(json.dumps([
            {"id": "R1", "title": "Req A", "type": "CALMREQU", "status": "CIPREQUOPEN"},
            {"id": "K1", "title": "Task B", "type": "CALMTASK", "status": "CIPTKOPEN"},
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

            reqs = _list(await _call(session, "requirements", "list", project_id="P001"))
            check("requirements read returns a list", isinstance(reqs, list))

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

            res = await _call(session, "tasks", "delete", project_id="P001", resource_id="T1",
                              data={"task_type": "Project Task"})
            check("task delete ok", res.is_error is not True, f"err {res.content[0].text if res.content else ''}")

            res = await _call(session, "requirements", "create", project_id="P001",
                              data={"title": "New Req", "sub_status": "In Specification"})
            check("requirement create ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

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

            # ---- The reported tag-creation bug ----------------------------
            res = await _call(session, "tags", "create", project_id="P001",
                              data={"group": "Scope", "tag": "MyNewTag"})
            check("tag create ok (reported bug fixed)", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")
            tag = _payload(res)
            check("tag create round-trips group+tag",
                  isinstance(tag, dict) and tag.get("tag") == "MyNewTag" and tag.get("group") == "Scope",
                  f"got {tag}")
            # Missing group/tag must error clearly rather than mis-call the client.
            res = await _call(session, "tags", "create", project_id="P001", data={"group": "Scope"})
            check("tag create without tag errors clearly", res.is_error is True)
            res = await _call(session, "tags", "create", data={"group": "Scope", "tag": "X"})
            check("tag create without project_id errors clearly", res.is_error is True)

            res = await _call(session, "features", "create", project_id="P001",
                              data={"name": "New Feature", "description": "d"})
            check("feature create ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

            res = await _call(session, "test_plans", "create", project_id="P001",
                              data={"name": "New Test Plan", "description": "d"})
            check("test_plan create ok", res.is_error is not True,
                  f"err {res.content[0].text if res.content else ''}")

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
