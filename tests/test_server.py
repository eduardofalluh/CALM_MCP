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
        "    def __init__(self, text, status_code=200, headers=None):\n"
        "        self.text = text; self.status_code = status_code; self.headers = headers or {}\n"
        "    def raise_for_status(self): pass\n"
        "    def json(self): return json.loads(self.text)\n"
        f"_PAYLOAD = {FAKE_PROJECTS_PAYLOAD!r}\n"
        "def _fake_get(url, *a, **kw):\n"
        "    # Single-entity GETs used by OData ETag auto-fetch.\n"
        "    if '/ManualTestCases/' in url or '/Activities/' in url or '/Actions/' in url:\n"
        "        # Test Management: ETag is the modifiedAt timestamp (no ETag header).\n"
        "        return _FakeResp(json.dumps({'uuid': 'TC-1', 'title': 'old', 'modifiedAt': '2025-11-17T15:51:04Z'}))\n"
        "    if '/businessProcesses/' in url or '/solutionProcesses/' in url or '/scopes/' in url:\n"
        "        return _FakeResp(json.dumps({'id': 'X', 'name': 'old'}), headers={'ETag': 'W/\\\"1\\\"'})\n"
        "    if '/projects/' in url:\n"
        "        # Projects: ETag is the numeric-timestamp `etag` body field (no header).\n"
        "        return _FakeResp(json.dumps({'id': 'P-1', 'name': 'old', 'etag': '1755245808454'}))\n"
        "    if '/tasks/' in url:\n"
        "        # Single-task GET used to auto-detect type for status-by-label updates.\n"
        "        return _FakeResp(json.dumps({'id': 'T1', 'type': 'CALMTASK', 'title': 'old'}))\n"
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
                "create_calm_task", "update_calm_task", "delete_calm_task",
                "create_calm_project", "update_calm_project",
                "create_calm_business_process", "update_calm_business_process",
                "delete_calm_business_process",
                "create_calm_solution_process", "update_calm_solution_process",
                "delete_calm_solution_process",
                "create_calm_scope", "update_calm_scope", "delete_calm_scope",
                "create_calm_test_case", "update_calm_test_case", "delete_calm_test_case",
            }
            sub_entity_tools = {
                "create_calm_task_relation", "delete_calm_task_relation", "set_calm_task_tags",
                "create_calm_task_comment", "update_calm_task_comment", "delete_calm_task_comment",
                "create_calm_timebox", "update_calm_timebox", "delete_calm_timebox",
                "assign_calm_scenario_versions", "update_calm_scope_assignments",
                "update_calm_test_activity", "delete_calm_test_activity",
                "create_calm_test_action", "update_calm_test_action", "delete_calm_test_action",
                "calm_api_write", "calm_api_delete",
            }
            check(
                "all top-level write/delete tools advertised",
                write_tools.issubset(tool_names),
                f"missing {sorted(write_tools - tool_names)}",
            )
            check(
                "all sub-entity + generic tools advertised",
                sub_entity_tools.issubset(tool_names),
                f"missing {sorted(sub_entity_tools - tool_names)}",
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
            print("\nTest 9: create_calm_project round-trips (name + programId)")
            res = await session.call_tool(
                "create_calm_project",
                {"name": "Proj X", "program_id": "PRG-1"},
            )
            proj = res.structuredContent or json.loads(res.content[0].text)
            check("project create did not error", res.isError is not True, f"got {proj}")
            check("project name echoed", proj.get("Name") == "Proj X", f"got {proj}")

            print("\nTest 10: create_calm_business_process round-trips")
            res = await session.call_tool(
                "create_calm_business_process",
                {"name": "Order to Cash", "description": "O2C"},
            )
            bp = res.structuredContent or json.loads(res.content[0].text)
            check("business process create did not error", res.isError is not True, f"got {bp}")
            check("business process name echoed", bp.get("Name") == "Order to Cash", f"got {bp}")

            print("\nTest 11: create_calm_solution_process (countries list -> comma string)")
            res = await session.call_tool(
                "create_calm_solution_process",
                {"name": "SP1", "countries": ["US", "CA"], "business_process_id": "BP-1"},
            )
            sp = res.structuredContent or json.loads(res.content[0].text)
            check("solution process create did not error", res.isError is not True, f"got {sp}")
            check(
                "countries sent as comma string",
                sp.get("Countries") == "US,CA",
                f"got {sp.get('Countries')!r}",
            )

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
                {"title": "TC1", "project_id": "P001", "scope_id": "SC1", "priority": "High", "is_prepared": True},
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

            # ---- OData updates auto-fetch the If-Match ETag ---------------
            print("\nTest 15: update_calm_business_process auto-fetches ETag and round-trips")
            res = await session.call_tool(
                "update_calm_business_process",
                {"business_process_id": "BP-1", "name": "Renamed BP"},
            )
            bp = res.structuredContent or json.loads(res.content[0].text)
            check("business process update did not error", res.isError is not True, f"got {bp}")
            check("business process new name echoed", bp.get("Name") == "Renamed BP", f"got {bp}")

            print("\nTest 16: update_calm_test_case (ETag = modifiedAt) round-trips")
            res = await session.call_tool(
                "update_calm_test_case",
                {"test_case_id": "TC-1", "title": "Renamed TC", "priority": "Low"},
            )
            tc = res.structuredContent or json.loads(res.content[0].text)
            check("test case update did not error", res.isError is not True, f"got {tc}")
            check("test case new title echoed", tc.get("Title") == "Renamed TC", f"got {tc}")
            check("test case priority label round-trips", tc.get("Priority") == "Low", f"got {tc}")

            print("\nTest 17: explicit if_match is honoured on update")
            res = await session.call_tool(
                "update_calm_scope",
                {"scope_id": "SC-1", "name": "Renamed scope", "if_match": "W/\"custom\""},
            )
            sc = res.structuredContent or json.loads(res.content[0].text)
            check("scope update with explicit if_match did not error", res.isError is not True, f"got {sc}")
            check("scope new name echoed", sc.get("Name") == "Renamed scope", f"got {sc}")

            # ---- test case deep insert -----------------------------------
            print("\nTest 18: create_calm_test_case with deep-insert activities/references")
            res = await session.call_tool(
                "create_calm_test_case",
                {
                    "title": "TC deep",
                    "project_id": "P001",
                    "scope_id": "SC1",
                    "priority": "Medium",
                    "activities": [
                        {"title": "Login", "sequence": 1, "isInScope": True,
                         "toActions": [{"title": "Enter creds", "sequence": 1, "isEvidenceRequired": True}]},
                    ],
                    "references": [{"name": "Docs", "url": "https://example.com"}],
                },
            )
            tcd = res.structuredContent or json.loads(res.content[0].text)
            check("deep-insert create did not error", res.isError is not True, f"got {tcd}")
            check("deep-insert title echoed", tcd.get("Title") == "TC deep", f"got {tcd}")

            # ---- delete tools --------------------------------------------
            print("\nTest 19: delete_calm_task (no If-Match)")
            res = await session.call_tool("delete_calm_task", {"task_id": "T123"})
            d = res.structuredContent or json.loads(res.content[0].text)
            check("task delete did not error", res.isError is not True, f"got {d}")
            check("task delete confirms id", d.get("deleted") == "T123", f"got {d}")

            print("\nTest 20: delete_calm_business_process (auto If-Match)")
            res = await session.call_tool("delete_calm_business_process", {"business_process_id": "BP-1"})
            d = res.structuredContent or json.loads(res.content[0].text)
            check("business process delete did not error", res.isError is not True, f"got {d}")
            check("business process delete confirms id", d.get("deleted") == "BP-1", f"got {d}")

            print("\nTest 21: delete_calm_test_case (ETag = modifiedAt)")
            res = await session.call_tool("delete_calm_test_case", {"test_case_id": "TC-1"})
            d = res.structuredContent or json.loads(res.content[0].text)
            check("test case delete did not error", res.isError is not True, f"got {d}")
            check("test case delete confirms id", d.get("deleted") == "TC-1", f"got {d}")

            print("\nTest 22: delete_calm_test_case force=true uses the force-delete action")
            res = await session.call_tool("delete_calm_test_case", {"test_case_id": "TC-1", "force": True})
            d = res.structuredContent or json.loads(res.content[0].text)
            check("force delete did not error", res.isError is not True, f"got {d}")
            check("force delete flagged", d.get("force") is True, f"got {d}")

            print("\nTest 23: update_calm_project auto-fetches the etag body field (If-Match)")
            res = await session.call_tool(
                "update_calm_project",
                {"project_id": "P-1", "name": "Renamed project"},
            )
            pu = res.structuredContent or json.loads(res.content[0].text)
            check("project update did not error", res.isError is not True, f"got {pu}")
            check("project new name echoed", pu.get("Name") == "Renamed project", f"got {pu}")

            print("\nTest 24: create_calm_task type=Risk maps CIPRI* status")
            res = await session.call_tool(
                "create_calm_task",
                {"project_id": "P001", "title": "A risk", "task_type": "Risk", "status": "In Progress"},
            )
            rt = res.structuredContent or json.loads(res.content[0].text)
            check("risk task create did not error", res.isError is not True, f"got {rt}")
            check("risk status round-trips", rt.get("Status") == "In Progress", f"got {rt.get('Status')}")

            print("\nTest 25: sub-task status uses task (CIPTK*) codes, not user-story codes")
            res = await session.call_tool(
                "create_calm_task",
                {"project_id": "P001", "title": "A sub-task", "task_type": "Sub-task", "status": "Done"},
            )
            st = res.structuredContent or json.loads(res.content[0].text)
            check("sub-task create did not error", res.isError is not True, f"got {st}")
            check("sub-task Done round-trips", st.get("Status") == "Done", f"got {st.get('Status')}")

            # ---- sub-entities --------------------------------------------
            print("\nTest 26: task relation + tags")
            res = await session.call_tool(
                "create_calm_task_relation",
                {"task_id": "T1", "relation_task_id": "T2", "relation_type": "0"},
            )
            check("create relation did not error", res.isError is not True)
            res = await session.call_tool("set_calm_task_tags", {"task_id": "T1", "tags": ["Group: A"]})
            tg = res.structuredContent or json.loads(res.content[0].text)
            check("set tags did not error", res.isError is not True, f"got {tg}")

            print("\nTest 27: task comment create/delete")
            res = await session.call_tool("create_calm_task_comment", {"task_id": "T1", "text": "hi"})
            check("create comment did not error", res.isError is not True)
            res = await session.call_tool("delete_calm_task_comment", {"comment_id": "C1"})
            cd = res.structuredContent or json.loads(res.content[0].text)
            check("delete comment confirms id", cd.get("deleted") == "C1", f"got {cd}")

            print("\nTest 28: timebox create/update/delete")
            res = await session.call_tool(
                "create_calm_timebox",
                {"project_id": "P001", "name": "Sprint 1", "timebox_type": 0, "start_date": "2026-01-01"},
            )
            check("create timebox did not error", res.isError is not True)
            res = await session.call_tool("delete_calm_timebox", {"timebox_id": "TB1"})
            tbd = res.structuredContent or json.loads(res.content[0].text)
            check("delete timebox confirms id", tbd.get("deleted") == "TB1", f"got {tbd}")

            print("\nTest 29: test action create + update (activity If-Match auto-fetch)")
            res = await session.call_tool(
                "create_calm_test_action",
                {"activity_id": "ACT-1", "title": "Step 1", "sequence": 1, "is_evidence_required": True},
            )
            check("create action did not error", res.isError is not True)
            res = await session.call_tool(
                "update_calm_test_action",
                {"action_id": "ACN-1", "title": "Step 1 renamed"},
            )
            check("update action did not error", res.isError is not True)

            print("\nTest 30: scope assignments (scope/unscope) + scenario versions")
            res = await session.call_tool(
                "update_calm_scope_assignments",
                {"assignments": [
                    {"scopeId": "S1", "solutionScenarioVersionId": "SSV1",
                     "solutionProcessVersionId": "SPV1", "isScoped": True, "statusId": "DESIGN"},
                ]},
            )
            sa = res.structuredContent or json.loads(res.content[0].text)
            check("scope assignments did not error", res.isError is not True, f"got {sa}")
            res = await session.call_tool(
                "assign_calm_scenario_versions", {"scope_id": "S1", "version_ids": ["SSV1", "SSV2"]},
            )
            check("assign scenario versions did not error", res.isError is not True)

            print("\nTest 31: generic escape hatch (calm_api_write / calm_api_delete)")
            res = await session.call_tool(
                "calm_api_write",
                {"method": "POST", "path": "api/calm-tasks/v1/workstreams", "body": {"name": "WS A"}},
            )
            gw = res.structuredContent or json.loads(res.content[0].text)
            check("generic write did not error", res.isError is not True, f"got {gw}")
            check("generic write echoes name", gw.get("name") == "WS A", f"got {gw}")
            res = await session.call_tool(
                "calm_api_delete", {"path": "api/calm-tasks/v1/workstreams/WS-1"},
            )
            gd = res.structuredContent or json.loads(res.content[0].text)
            check("generic delete confirms path", "workstreams/WS-1" in str(gd.get("deleted")), f"got {gd}")

            print("\nTest 32: generic write rejects bad method")
            res = await session.call_tool(
                "calm_api_write", {"method": "GET", "path": "api/calm-tasks/v1/tasks"},
            )
            check("bad method errors", res.isError is True)

            print("\nTest 33: update_calm_task status-by-label WITHOUT task_type (auto-detect type)")
            res = await session.call_tool(
                "update_calm_task", {"task_id": "T1", "status": "In Progress"},
            )
            au = res.structuredContent or json.loads(res.content[0].text)
            check("status-by-label update did not error", res.isError is not True, f"got {au}")
            check("auto-detected type resolved status", au.get("Status") == "In Progress", f"got {au.get('Status')}")

            print("\nTest 34: create_calm_test_case without scope_id is rejected")
            res = await session.call_tool(
                "create_calm_test_case", {"title": "no scope", "project_id": "P001"},
            )
            check("missing scope_id errors", res.isError is True)

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
