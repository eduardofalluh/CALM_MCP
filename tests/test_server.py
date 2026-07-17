"""End-to-end MCP test for the CALM server.

Spawns server.py as a stdio subprocess, connects with the official MCP
client, and exercises:
  - tools/list           (read + write tools advertised, correct schemas)
  - calm_health          (token resolution, writes_enabled flag)
  - get_calm_projects    (full round-trip with requests.get monkey-patched
                          via a tiny shim module so we don't hit SAP)
  - create/update tasks  (guard blocks by default; round-trips when
                          CALM_ENABLE_WRITES=true, with requests.request shimmed)

Run with:    python tests/test_server.py
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


def _write_shim() -> Path:
    shim_dir = ROOT / ".test_shim"
    shim_dir.mkdir(exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(
        "import json, requests\n"
        "class _FakeResp:\n"
        "    def __init__(self, text, status_code=200): self.text = text; self.status_code = status_code\n"
        "    def raise_for_status(self): pass\n"
        "    def json(self): return json.loads(self.text)\n"
        f"_PAYLOAD = {FAKE_PROJECTS_PAYLOAD!r}\n"
        "def _fake_get(url, *a, **kw):\n"
        "    return _FakeResp(_PAYLOAD)\n"
        "def _fake_request(method, url, *a, **kw):\n"
        "    # Echo the submitted body back with a generated id, mimicking a create/update.\n"
        "    body = json.loads(kw.get('data') or '{}')\n"
        "    body.setdefault('id', 'T999')\n"
        "    return _FakeResp(json.dumps(body))\n"
        "requests.get = _fake_get\n"
        "requests.request = _fake_request\n"
    )
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
        "PYTHONPATH": f"{ROOT}{os.pathsep}{shim_dir}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }
    if extra_env:
        env.update(extra_env)
    return StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=env,
    )


async def main() -> int:
    shim_dir = _write_shim()

    params = _make_params(shim_dir)

    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {label}{(' - ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    print("Connecting to CALM MCP server over stdio...")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Session initialized.\n")

            # ---- tools/list ---------------------------------------------
            print("Test 1: tools/list advertises all expected tools")
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            expected = {
                "get_calm_projects",
                "get_calm_tasks",
                "get_calm_business_processes",
                "get_calm_solution_processes",
                "get_calm_scopes",
                "get_calm_test_cases",
                "calm_health",
            }
            check(
                "all 7 read tools advertised",
                expected.issubset(tool_names),
                f"got {sorted(tool_names)}",
            )
            write_tools = {
                "create_calm_task", "update_calm_task",
                "create_calm_project", "update_calm_project",
                "create_calm_business_process", "update_calm_business_process",
                "create_calm_solution_process", "update_calm_solution_process",
                "create_calm_scope", "update_calm_scope",
                "create_calm_test_case", "update_calm_test_case",
            }
            check(
                "all 12 write tools advertised",
                write_tools.issubset(tool_names),
                f"missing {sorted(write_tools - tool_names)}",
            )

            for t in tools.tools:
                check(
                    f"'{t.name}' has a description",
                    bool(t.description and t.description.strip()),
                )

            tasks_tool = next(t for t in tools.tools if t.name == "get_calm_tasks")
            schema = tasks_tool.inputSchema or {}
            required = schema.get("required") or []
            check(
                "get_calm_tasks requires project_id",
                "project_id" in required,
                f"required={required}",
            )

            # ---- calm_health --------------------------------------------
            print("\nTest 2: calm_health returns expected diagnostic")
            res = await session.call_tool("calm_health", {})
            health = res.structuredContent or json.loads(res.content[0].text)
            check("server name", health.get("server") == "sap-cloud-alm")
            check("token configured", health.get("token_configured") is True)
            check("token source is CALM_TOKEN env var", health.get("token_source") == "CALM_TOKEN env var")
            check(
                "base_url derived from BTP zone config",
                health.get("base_url") == "https://test-cloudalm.us10.alm.cloud.sap",
                f"got {health.get('base_url')}",
            )
            check("client_credentials_enabled is False", health.get("client_credentials_enabled") is False)

            # ---- get_calm_projects (with requests.get shimmed) ----------
            print("\nTest 3: get_calm_projects returns parsed list")
            res = await session.call_tool("get_calm_projects", {})
            projects = (res.structuredContent or {}).get("result")
            check("returned a list", isinstance(projects, list))
            check("returned 2 projects", len(projects) == 2)
            check(
                "first project is Active",
                projects[0]["Status"] == "Active",
                f"got {projects[0]['Status']}",
            )
            check(
                "second project is Hidden",
                projects[1]["Status"] == "Hidden",
                f"got {projects[1]['Status']}",
            )
            check(
                "field names match contract",
                set(projects[0].keys()) == {"ID", "Name", "Status", "Purpose", "OperationalStatus"},
                f"got {sorted(projects[0].keys())}",
            )

            # ---- error path --------------------------------------------
            print("\nTest 4: missing project_id surfaces a clear error")
            res = await session.call_tool("get_calm_tasks", {"project_id": ""})
            check("error flag set", res.isError is True)

            # ---- writes disabled by default -----------------------------
            print("\nTest 5: create_calm_task is blocked when writes are disabled")
            res = await session.call_tool(
                "create_calm_task",
                {"project_id": "P001", "title": "Should be blocked", "task_type": "Project Task"},
            )
            check("write blocked (error flag set)", res.isError is True)
            err_text = res.content[0].text if res.content else ""
            check(
                "error mentions CALM_ENABLE_WRITES",
                "CALM_ENABLE_WRITES" in err_text,
                f"got {err_text!r}",
            )

    # ---- writes enabled (separate server process) -------------------
    print("\nTest 6: with CALM_ENABLE_WRITES=true, create/update round-trip")
    write_params = _make_params(shim_dir, {"CALM_ENABLE_WRITES": "true"})
    async with stdio_client(write_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            res = await session.call_tool("calm_health", {})
            health = res.structuredContent or json.loads(res.content[0].text)
            check("writes_enabled true in health", health.get("writes_enabled") is True)

            res = await session.call_tool(
                "create_calm_task",
                {
                    "project_id": "P001",
                    "title": "New task from test",
                    "task_type": "Project Task",
                    "status": "In Progress",
                },
            )
            created = res.structuredContent or json.loads(res.content[0].text)
            check("create did not error", res.isError is not True, f"got {created}")
            check("created task echoes title", created.get("Title") == "New task from test", f"got {created}")
            check(
                "human status mapped to code and back to label",
                created.get("Status") == "In Progress",
                f"got {created.get('Status')}",
            )

            print("\nTest 7: update_calm_task round-trips a partial change")
            res = await session.call_tool(
                "update_calm_task",
                {"task_id": "T123", "title": "Renamed", "status": "Done", "task_type": "Project Task"},
            )
            updated = res.structuredContent or json.loads(res.content[0].text)
            check("update did not error", res.isError is not True, f"got {updated}")
            check("updated task echoes new title", updated.get("Title") == "Renamed", f"got {updated}")

            print("\nTest 8: update with no fields surfaces a clear error")
            res = await session.call_tool("update_calm_task", {"task_id": "T123"})
            check("empty update errors", res.isError is True)

            # ---- other entity writes round-trip -------------------------
            print("\nTest 9: create_calm_project round-trips (status label mapping)")
            res = await session.call_tool(
                "create_calm_project",
                {"name": "Proj X", "status": "Active", "purpose": "Build"},
            )
            proj = res.structuredContent or json.loads(res.content[0].text)
            check("project create did not error", res.isError is not True, f"got {proj}")
            check("project name echoed", proj.get("Name") == "Proj X", f"got {proj}")
            check("project status label round-trips", proj.get("Status") == "Active", f"got {proj}")

            print("\nTest 10: create_calm_business_process round-trips")
            res = await session.call_tool(
                "create_calm_business_process",
                {"name": "Order to Cash", "description": "O2C"},
            )
            bp = res.structuredContent or json.loads(res.content[0].text)
            check("business process create did not error", res.isError is not True, f"got {bp}")
            check("business process name echoed", bp.get("Name") == "Order to Cash", f"got {bp}")

            print("\nTest 11: create_calm_solution_process round-trips")
            res = await session.call_tool(
                "create_calm_solution_process",
                {"name": "SP1", "countries": ["US", "CA"]},
            )
            sp = res.structuredContent or json.loads(res.content[0].text)
            check("solution process create did not error", res.isError is not True, f"got {sp}")
            check("solution process countries echoed", sp.get("Countries") == ["US", "CA"], f"got {sp}")

            print("\nTest 12: create_calm_scope round-trips")
            res = await session.call_tool(
                "create_calm_scope",
                {"project_id": "P001", "name": "Scope A", "description": "d"},
            )
            sc = res.structuredContent or json.loads(res.content[0].text)
            check("scope create did not error", res.isError is not True, f"got {sc}")
            check("scope project id echoed", sc.get("Project ID") == "P001", f"got {sc}")

            print("\nTest 13: create_calm_test_case round-trips (priority label mapping)")
            res = await session.call_tool(
                "create_calm_test_case",
                {"title": "TC1", "project_id": "P001", "priority": "High", "is_prepared": True},
            )
            tc = res.structuredContent or json.loads(res.content[0].text)
            check("test case create did not error", res.isError is not True, f"got {tc}")
            check("test case title echoed", tc.get("Title") == "TC1", f"got {tc}")
            check("test case priority label round-trips", tc.get("Priority") == "High", f"got {tc}")
            check("test case prepared echoed", tc.get("Prepared") is True, f"got {tc}")

            print("\nTest 14: unknown priority label surfaces a clear error")
            res = await session.call_tool(
                "create_calm_test_case",
                {"title": "TC2", "priority": "Bogus"},
            )
            check("bad priority errors", res.isError is True)

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
