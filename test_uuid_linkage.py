"""Test that test case UUID/ID is returned for linkage purposes.

Test cases in SAP Cloud ALM use `uuid` as the unique identifier (OData key).
This is essential for:
1. Linking test cases to requirements
2. Assigning test cases to test plans
3. Referencing test cases in other entities

This test verifies that both get_test_cases and create_test_case return the UUID.
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
ROOT = HERE

# Fake response with realistic UUID format
FAKE_TEST_CASES = json.dumps([
    {
        "uuid": "550e8400-e29b-41d4-a716-446655440000",  # Realistic UUID format
        "projectId": "P001",
        "scopeId": "SC001",
        "solutionProcessId": "SP001",
        "title": "Test Customer Login",
        "isPrepared": True,
        "priorityCode": "20",
    },
    {
        "uuid": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "projectId": "P001",
        "scopeId": "SC001",
        "solutionProcessId": "SP001",
        "title": "Test Password Reset",
        "isPrepared": False,
        "priorityCode": "30",
    },
])


def _write_shim() -> Path:
    shim_dir = ROOT / ".test_shim_uuid"
    shim_dir.mkdir(exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(
        "import json, requests\n"
        "class _FakeResp:\n"
        "    def __init__(self, text, status_code=200):\n"
        "        self.text = text; self.status_code = status_code\n"
        "    def raise_for_status(self): pass\n"
        "    def json(self): return json.loads(self.text)\n"
        f"_TEST_CASES = {FAKE_TEST_CASES!r}\n"
        "def _fake_get(url, *a, **kw):\n"
        "    if 'ManualTestCases' in url:\n"
        "        return _FakeResp(json.dumps({'value': json.loads(_TEST_CASES)}))\n"
        "    return _FakeResp('{}')\n"
        "def _fake_request(method, url, *a, **kw):\n"
        "    # Echo back with a real UUID\n"
        "    body = json.loads(kw.get('data') or '{}')\n"
        "    body['uuid'] = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'\n"
        "    return _FakeResp(json.dumps(body))\n"
        "requests.get = _fake_get\n"
        "requests.request = _fake_request\n"
    )
    return shim_dir


async def main() -> int:
    shim_dir = _write_shim()

    env = {
        **os.environ,
        "CALM_TOKEN": "fake-token-for-uuid-test",
        "IDENTITY_ZONE": "test-cloudalm",
        "REGION_ZONE": "us10",
        "CALM_ENABLE_WRITES": "true",
        "PYTHONPATH": f"{ROOT}{os.pathsep}{shim_dir}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=env,
    )

    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        marker = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {marker} {label}{(' - ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    print("=" * 60)
    print("UUID LINKAGE TEST - Verify test case UUIDs are accessible")
    print("=" * 60)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Test 1: get_calm_test_cases returns UUID
            print("\nTest 1: get_calm_test_cases returns UUID field")
            res = await session.call_tool("get_calm_test_cases", {})
            test_cases = (res.structuredContent or {}).get("result")
            check("returned a list", isinstance(test_cases, list), f"got {type(test_cases)}")
            check("returned test cases", len(test_cases) > 0, f"got {len(test_cases)} test cases")

            if test_cases:
                first_tc = test_cases[0]
                print(f"\n  📋 First test case: {json.dumps(first_tc, indent=2)}")

                check("test case has ID field", "ID" in first_tc, f"fields: {list(first_tc.keys())}")
                check("ID field is not None", first_tc.get("ID") is not None, f"got {first_tc.get('ID')}")
                check("ID field is not empty", bool(first_tc.get("ID")), f"got '{first_tc.get('ID')}'")

                # Check if it looks like a UUID (contains hyphens and is 36 chars)
                id_value = str(first_tc.get("ID", ""))
                is_uuid_format = "-" in id_value and len(id_value) == 36
                check("ID looks like UUID format", is_uuid_format, f"got '{id_value}' (len={len(id_value)})")

                check("test case has Title", "Title" in first_tc, f"fields: {list(first_tc.keys())}")
                check("test case has Project ID", "Project ID" in first_tc, f"fields: {list(first_tc.keys())}")

            # Test 2: create_calm_test_case returns UUID
            print("\nTest 2: create_calm_test_case returns UUID field")
            res = await session.call_tool(
                "create_calm_test_case",
                {
                    "title": "Test Invoice Generation",
                    "project_id": "P001",
                    "scope_id": "SC001",
                },
            )
            created_tc = res.structuredContent or json.loads(res.content[0].text)

            print(f"\n  📋 Created test case: {json.dumps(created_tc, indent=2)}")

            check("create did not error", res.isError is not True, f"got error: {created_tc}")
            check("created test case has ID field", "ID" in created_tc, f"fields: {list(created_tc.keys())}")
            check("created ID is not None", created_tc.get("ID") is not None, f"got {created_tc.get('ID')}")
            check("created ID is not empty", bool(created_tc.get("ID")), f"got '{created_tc.get('ID')}'")

            # Check if it looks like a UUID
            created_id = str(created_tc.get("ID", ""))
            is_uuid_format = "-" in created_id and len(created_id) == 36
            check("created ID looks like UUID format", is_uuid_format, f"got '{created_id}' (len={len(created_id)})")

            # Test 3: Demonstrate linkage use case
            print("\nTest 3: UUID can be used for linkage")
            if test_cases and created_tc.get("ID"):
                existing_uuid = test_cases[0].get("ID")
                new_uuid = created_tc.get("ID")

                print(f"\n  🔗 Linkage examples:")
                print(f"     - Link to requirement: task_id=R001, test_case_uuid={existing_uuid}")
                print(f"     - Assign to test plan: plan_id=TP001, test_case_uuid={new_uuid}")
                print(f"     - Reference in test activity: activity_id=ACT001, test_case_uuid={existing_uuid}")

                check("existing test case UUID is accessible", bool(existing_uuid), f"got '{existing_uuid}'")
                check("new test case UUID is accessible", bool(new_uuid), f"got '{new_uuid}'")
                check("UUIDs are different", existing_uuid != new_uuid, f"both are '{existing_uuid}'")

    print("\n" + "=" * 60)
    if failures:
        print(f"❌ FAILED: {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        print("\n⚠️  UUID LINKAGE NOT WORKING - Test cases cannot be linked!")
        return 1

    print("✅ All UUID checks passed!")
    print("\n📌 Summary:")
    print("  - get_calm_test_cases returns UUID in ID field")
    print("  - create_calm_test_case returns UUID in ID field")
    print("  - UUIDs are in correct format (36 chars with hyphens)")
    print("  - UUIDs can be used for linkage to requirements, test plans, etc.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
