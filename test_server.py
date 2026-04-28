"""End-to-end MCP test for the CALM server.

Spawns server.py as a stdio subprocess, connects with the official MCP
client, and exercises:
  - tools/list           (all 7 tools advertised, correct schemas)
  - calm_health          (token resolution)
  - get_calm_projects    (full round-trip with requests.get monkey-patched
                          via a tiny shim module so we don't hit SAP)

Run with:    python test_server.py
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

# A fake CALM payload that matches the real /api/calm-projects/v1/projects
# response shape (a JSON array of project objects).
FAKE_PROJECTS_PAYLOAD = json.dumps([
    {"id": "P001", "name": "Test Project A", "status": "O", "purpose": "Build"},
    {"id": "P002", "name": "Test Project B", "status": "C", "purpose": "Run"},
])


def _write_shim() -> Path:
    """Create a sitecustomize.py that patches requests.get inside the spawned
    server process so it returns FAKE_PROJECTS_PAYLOAD without hitting the
    network. Python auto-imports `sitecustomize` on startup if it's on
    sys.path, so injecting it via PYTHONPATH means the patch is in place
    before server.py imports anything."""
    shim_dir = HERE / ".test_shim"
    shim_dir.mkdir(exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(
        "import json, requests\n"
        "class _FakeResp:\n"
        "    status_code = 200\n"
        "    def __init__(self, text): self.text = text\n"
        "    def raise_for_status(self): pass\n"
        "    def json(self): return json.loads(self.text)\n"
        f"_PAYLOAD = {FAKE_PROJECTS_PAYLOAD!r}\n"
        "def _fake_get(url, *a, **kw):\n"
        "    return _FakeResp(_PAYLOAD)\n"
        "requests.get = _fake_get\n"
    )
    return shim_dir


async def main() -> int:
    shim_dir = _write_shim()

    env = {
        **os.environ,
        "CALM_TOKEN": "fake-local-token-for-tests",
        # Force the shim onto PYTHONPATH for the child process.
        "PYTHONPATH": f"{shim_dir}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(HERE / "server.py")],
        env=env,
    )

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
                "all 7 tools advertised",
                expected.issubset(tool_names),
                f"got {sorted(tool_names)}",
            )

            # Each tool should have a non-empty description (helps the LLM).
            for t in tools.tools:
                check(
                    f"'{t.name}' has a description",
                    bool(t.description and t.description.strip()),
                )

            # get_calm_tasks must declare project_id as a required arg.
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
            # FastMCP exposes the typed return value via structuredContent.
            # For dict returns the value is the dict itself; for list returns
            # the list lives under the "result" key.
            health = res.structuredContent or json.loads(res.content[0].text)
            check("server name", health.get("server") == "sap-cloud-alm")
            check("token configured", health.get("token_configured") is True)
            check("token source is CALM_TOKEN", health.get("token_source") == "CALM_TOKEN")
            check("base_url present", bool(health.get("base_url")))

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
                set(projects[0].keys()) == {"ID", "Name", "Status", "Purpose"},
                f"got {sorted(projects[0].keys())}",
            )

            # ---- error path --------------------------------------------
            print("\nTest 4: missing project_id surfaces a clear error")
            res = await session.call_tool("get_calm_tasks", {"project_id": ""})
            check("error flag set", res.isError is True)

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
