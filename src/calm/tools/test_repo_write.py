"""Write tools for the optional BTP Test Management OData V4 repository.

Guarded by TM_ENABLE_WRITES (independent from CALM_ENABLE_WRITES, so enabling
writes to one system never silently enables them for the other). All tools
also require the TM connection to be configured (TM_* env vars or x-tm-*
headers) — see tools/test_repo.py.

Concurrency: the service enforces optimistic locking — PATCH/DELETE without
If-Match → 428, stale ETag → 412. The typed update/delete tools auto-fetch the
current ETag when `if_match` is not supplied; the generic escape hatch does
not (pass it explicitly, or default '*' is used for delete).
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import tm_client
from src.calm.tm_dependencies import ensure_tm_writes_enabled, get_tm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def create_tm_requirement(
        tr_id: str,
        short_desc: str,
        ctx: Context,
        wricef: str | None = None,
    ) -> dict:
        """Create a testing requirement in the Test Management repository.

        Args:
            tr_id: requirement key, e.g. "TR-0042".
            short_desc: short description.
            wricef: optional WRICEF classification.
        """
        ensure_tm_writes_enabled()
        if not tr_id or not short_desc:
            raise ValueError("tr_id and short_desc are required")
        h = get_tm_headers(ctx)
        body: dict = {"tr_id": tr_id, "short_desc": short_desc}
        if wricef:
            body["wricef"] = wricef
        return tm_client.create_requirement(h.token, h.base_url, body)

    @mcp.tool()
    def create_tm_test_case(test_case: dict, ctx: Context) -> dict:
        """Create a test case — supports DEEP INSERT of the whole tree in one
        request: test case → activities → actions → field entries, plus
        applications.

        Args:
            test_case: entity payload, e.g.
                {"title": "...", "project_id": "<CALM-project-uuid>",
                 "scope_id": "<CALM-scope-uuid>", "external_id": "TC-0001",
                 "scenario_type": "positive", "priority_code": 30,
                 "is_prepared": false,
                 "preconditions": ["..."], "test_data": ["..."],
                 "activities": [{"sequence": 1, "title": "...",
                                 "applications": [...], "actions": [...]}]}
            preconditions/test_data/postconditions/assumptions are JSON string
            arrays. priority_code is numeric: 10=Very High, 20=High, 30=Medium,
            40=Low.
        """
        ensure_tm_writes_enabled()
        if not test_case or not isinstance(test_case, dict):
            raise ValueError("test_case payload (dict) is required")
        if not test_case.get("title"):
            raise ValueError("test_case.title is required")
        h = get_tm_headers(ctx)
        return tm_client.create_test_case(h.token, h.base_url, test_case)

    @mcp.tool()
    def update_tm_test_case(
        test_case_id: str,
        fields: dict,
        ctx: Context,
        if_match: str | None = None,
    ) -> dict:
        """Partial-update (PATCH) a test case. The current ETag is auto-fetched
        when `if_match` is not supplied (the service returns 428 without one,
        412 when stale — on 412, retry to pick up the fresh ETag).

        Args:
            test_case_id: the test case id.
            fields: fields to change, e.g. {"is_prepared": true}.
            if_match: optional explicit ETag for strict optimistic locking.
        """
        ensure_tm_writes_enabled()
        if not test_case_id:
            raise ValueError("test_case_id is required")
        if not fields:
            raise ValueError("fields is required — nothing to update")
        h = get_tm_headers(ctx)
        return tm_client.update_test_case(h.token, h.base_url, test_case_id, fields, if_match=if_match)

    @mcp.tool()
    def delete_tm_requirement(requirement_id: str, ctx: Context, if_match: str | None = None) -> dict:
        """Delete a testing requirement. ⚠️ CASCADES to its test cases,
        activities, actions and field entries — use with care. ETag auto-fetched
        when `if_match` is not supplied."""
        ensure_tm_writes_enabled()
        if not requirement_id:
            raise ValueError("requirement_id is required")
        h = get_tm_headers(ctx)
        return tm_client.delete_requirement(h.token, h.base_url, requirement_id, if_match=if_match)

    @mcp.tool()
    def delete_tm_test_case(test_case_id: str, ctx: Context, if_match: str | None = None) -> dict:
        """Delete a test case (ETag auto-fetched when `if_match` is not supplied)."""
        ensure_tm_writes_enabled()
        if not test_case_id:
            raise ValueError("test_case_id is required")
        h = get_tm_headers(ctx)
        return tm_client.delete_test_case(h.token, h.base_url, test_case_id, if_match=if_match)

    @mcp.tool()
    def tm_odata_write(
        method: str,
        path: str,
        body: dict,
        ctx: Context,
        if_match: str | None = None,
    ) -> dict:
        """Generic write escape hatch for the Test Management OData service —
        POST or PATCH against any service-relative path (e.g.
        "Activities('<uuid>')"). Does NOT auto-fetch ETags: pass `if_match` for
        PATCH, or use the dedicated typed tool which fetches it for you.
        """
        ensure_tm_writes_enabled()
        if not path:
            raise ValueError("path is required")
        h = get_tm_headers(ctx)
        return tm_client.odata_write(h.token, h.base_url, method, path, body or {}, if_match=if_match)

    @mcp.tool()
    def tm_odata_delete(path: str, ctx: Context, if_match: str | None = None) -> dict:
        """Generic DELETE escape hatch for any service-relative path. Uses
        If-Match '*' (match any version) when `if_match` is not supplied."""
        ensure_tm_writes_enabled()
        if not path:
            raise ValueError("path is required")
        h = get_tm_headers(ctx)
        return tm_client.odata_delete(h.token, h.base_url, path, if_match=if_match)
