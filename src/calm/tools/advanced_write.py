"""Generic low-level write tools — an escape hatch for any CALM API endpoint
that doesn't have a dedicated tool (e.g. feature/document/hierarchy assignments,
workstreams, deliverables, programs, system groups, deployment plans, external
integrations, process-authoring assets/flows/diagrams/activities, publish/draft
actions, test-case applications/references/task assignments).

Both tools are guarded by CALM_ENABLE_WRITES. The caller supplies the exact
API-relative path and JSON body, so these can hit anything the token is scoped for.
"""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers


def register(mcp: FastMCP) -> None:

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
            if_match=if_match, base_url=h.base_url,
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
        return client.api_delete(token=h.token, path=path, if_match=if_match, base_url=h.base_url)
