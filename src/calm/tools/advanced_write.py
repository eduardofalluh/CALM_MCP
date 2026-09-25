"""Generic low-level CALM API tools — an escape hatch for any endpoint that
doesn't have a dedicated tool (e.g. feature/document/hierarchy assignments,
workstreams, deliverables, programs, system groups, deployment plans, external
integrations, process-authoring assets/flows/diagrams/activities, publish/draft
actions, test-case applications/references/task assignments).

Three tools complete the read/write/delete trio: `calm_api_read` (GET),
`calm_api_write` (POST/PATCH) and `calm_api_delete` (DELETE). The write and
delete tools are guarded by CALM_ENABLE_WRITES; `calm_api_read` is read-only and
always available (never gated), so an agent can always read even if the unified
`calm_resource` tool is not enabled for it. The caller supplies the exact
API-relative path, so these can hit anything the token is scoped for.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calm_api_read(path: str, ctx: Context, params: dict | None = None) -> Any:
        """Low-level GET for any CALM API path. Read-only — always available
        (NOT gated by CALM_ENABLE_WRITES).

        Use this to READ any endpoint, especially when you need a value that a
        write call requires. The classic case: a requirement/task POST needs the
        project UUID in the path — list projects here first to find it.

        Args:
            path: API-relative path from the tenant base URL, e.g.
                "api/calm-projects/v1/projects" (list projects → get project UUIDs),
                "api/calm-tasks/v1/tasks/{id}" (one task),
                "api/calm-projects/v1/projects/{id}" (one project).
            params: optional query parameters, e.g. {"$top": 50}.

        Returns the parsed JSON response.
        """
        if not path:
            raise ValueError("path is required")
        h = get_calm_headers(ctx)
        return client.api_read(token=h.token, path=path, params=params, base_url=h.base_url)

    @mcp.tool()
    def calm_api_write(
        method: str,
        path: str,
        ctx: Context,
        body: dict | list | None = None,
        if_match: str | None = None,
    ) -> dict:
        """Low-level POST/PATCH to any CALM API path. Requires CALM_ENABLE_WRITES=true.

        Use this for documented endpoints that don't yet have a dedicated tool.

        Args:
            method: "POST" or "PATCH".
            path: API-relative path from the tenant base URL, e.g.
                "api/calm-tasks/v1/workstreams" or
                "api/calm-processauthoring/v1/publishSolutionProcess/{id}".
            body: JSON body (object or array) to send.
            if_match: ETag for services that require it (Process Authoring, Test
                Management PATCH/DELETE, Projects PATCH). Not auto-fetched here —
                pass it explicitly when needed, or use the dedicated typed tool.

        Returns the parsed response, or a small acknowledgement if the API returns
        no body.
        """
        ensure_writes_enabled()
        method_up = (method or "").upper()
        if method_up not in ("POST", "PATCH"):
            raise ValueError('method must be "POST" or "PATCH"')
        if not path:
            raise ValueError("path is required")
        h = get_calm_headers(ctx)
        return client.api_write(
            token=h.token, method=method_up, path=path, body=body,
            if_match=if_match, base_url=h.base_url, user_email=h.user_email,
        )

    @mcp.tool()
    def calm_api_delete(path: str, ctx: Context, if_match: str | None = None) -> dict:
        """Low-level DELETE to any CALM API path. Requires CALM_ENABLE_WRITES=true.

        Args:
            path: API-relative path, e.g. "api/calm-tasks/v1/workstreams/{id}".
            if_match: ETag for services that require it (pass explicitly when needed).
        """
        ensure_writes_enabled()
        if not path:
            raise ValueError("path is required")
        h = get_calm_headers(ctx)
        return client.api_delete(token=h.token, path=path, if_match=if_match, base_url=h.base_url, user_email=h.user_email)
