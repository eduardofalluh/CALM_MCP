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

import re
from typing import Any

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers
from src.calm.tools.unified import _unanswerable_read

# Query options that only shape or page an answer: leaving one out can't change
# what the answer is about ($filter can, so it is never dropped).
_DROPPABLE = {"$top", "$skip", "$select", "$orderby", "$count", "$expand"}
_UNSUPPORTED = re.compile(r'Query parameter \\?"([^"\\]+)\\?" is not supported')
_TASKS_HINT = ("The Tasks API is plain REST, not OData: it takes projectId and no $filter, $select "
               "or $top. Use calm_resource(resource='tasks', operation='list', project_id=<uuid>, "
               "data={'timebox': ..., 'team': ..., 'summarize_by': ['Timebox', 'Responsible Team']}) "
               "for filtered lists and totals.")


def _unsupported_option(exc: Exception, params: dict | None) -> str | None:
    """The params key SAP refused as unsupported, when leaving it out is safe."""
    match = _UNSUPPORTED.search(str(exc))
    if not (match and params):
        return None
    name = match.group(1).lower()
    return next((k for k in params if k.lower() == name and name in _DROPPABLE), None)


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calm_api_read(path: str, ctx: Context, params: dict | None = None) -> Any:
        """SAP Cloud ALM (CALM) low-level GET — raw read for any SAP Cloud ALM API
        path on THIS tenant. Read-only, always available (NOT gated by
        CALM_ENABLE_WRITES).

        Prefer calm_resource for normal reads; use this ESCAPE HATCH only for SAP
        Cloud ALM endpoints that calm_resource does not cover, or to fetch a value a
        write call requires. The classic case: a requirement/task POST needs the
        project UUID in the path — list projects here first to find it. This hits
        the SAP Cloud ALM tenant only; do not use it for non-CALM systems.

        Do NOT use it to list, filter, count or sum tasks: the Tasks API
        (api/calm-tasks/v1/tasks) is plain REST, not OData — it takes projectId as
        a query parameter and rejects $filter / $select. Use
        calm_resource(resource="tasks", operation="list", project_id=...,
        data={"timebox": ..., "team": ..., "summarize_by": [...]}) instead.

        Args:
            path: API-relative path from the tenant base URL, e.g.
                "api/calm-projects/v1/projects" (list projects → get project UUIDs),
                "api/calm-tasks/v1/tasks/{id}" (one task),
                "api/calm-projects/v1/projects/{id}" (one project).
            params: optional query parameters, e.g. {"projectId": "<uuid>"}. OData
                options ($top, $skip, $select, $orderby) work on OData services only;
                where SAP doesn't support one it is left out and the answer says so.

        Returns the parsed JSON response. A read SAP refuses (400 / 403 / 404) comes
        back as {"status": ..., "message": ...} instead of an error.
        """
        if not path:
            raise ValueError("path is required")
        h = get_calm_headers(ctx)
        ignored: list[str] = []
        try:
            while True:
                try:
                    result = client.api_read(token=h.token, path=path, params=params, base_url=h.base_url)
                    break
                except RuntimeError as exc:
                    key = _unsupported_option(exc, params)
                    if key is None:
                        raise
                    ignored.append(key)
                    params = {k: v for k, v in (params or {}).items() if k != key}
        except (ValueError, RuntimeError) as exc:
            answer = _unanswerable_read("item", "get", path, exc)
            if answer is None:
                raise
            answer["hint"] = (_TASKS_HINT if "calm-tasks" in path else
                              "Check the path, the IDs in it and the parameters; prefer calm_resource "
                              "for the resources it covers.")
            return answer
        if not ignored:
            return result
        paged = any(k.lower() in ("$top", "$skip") for k in params or {})
        return {"Ignored Parameters": ignored,
                "Note": (f"SAP's API here does not support {', '.join(ignored)}, so it was left out"
                         + ("." if paged else " and this is the complete answer — no paging needed.")),
                "Result": result}

    @mcp.tool()
    def calm_api_write(
        method: str,
        path: str,
        ctx: Context,
        body: dict | list | None = None,
        if_match: str | None = None,
    ) -> dict:
        """SAP Cloud ALM (CALM) low-level POST/PATCH — raw write to any SAP Cloud ALM
        API path on THIS tenant. Requires CALM_ENABLE_WRITES=true.

        Prefer calm_resource for normal create/update; use this ESCAPE HATCH only for
        documented SAP Cloud ALM endpoints that calm_resource does not yet cover.
        Writes go to the SAP Cloud ALM tenant only — never another system.

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
        """SAP Cloud ALM (CALM) low-level DELETE — raw delete for any SAP Cloud ALM
        API path on THIS tenant. Requires CALM_ENABLE_WRITES=true. Use this ESCAPE
        HATCH only for SAP Cloud ALM endpoints that calm_resource does not cover;
        deletes affect the SAP Cloud ALM tenant only.

        Args:
            path: API-relative path, e.g. "api/calm-tasks/v1/workstreams/{id}".
            if_match: ETag for services that require it (pass explicitly when needed).
        """
        ensure_writes_enabled()
        if not path:
            raise ValueError("path is required")
        h = get_calm_headers(ctx)
        return client.api_delete(token=h.token, path=path, if_match=if_match, base_url=h.base_url, user_email=h.user_email)
