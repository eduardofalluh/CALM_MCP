"""Read tools for the optional BTP Test Management OData V4 repository.

This is NOT SAP Cloud ALM — it is the CAP OData service over the BTP
PostgreSQL test-management repository, which mirrors CALM test-management
entities and is fed by a separate CALM→repository integration. Reads here are
always live: OData queries return the current repository state, and the
`updated_since` watermark gives incremental (delta) reads.

Entity model (from the service $metadata, namespace TestManagementService):
  Requirements : id, tr_id, wricef, short_desc, created_at, updated_at
                 → testCases
  TestCases    : id, testing_requirement_id, title, project_id, scope_id,
                 solution_process_id, priority_code (10/20/30/40), is_prepared,
                 external_id, scenario_type, preconditions[], test_data[],
                 postconditions[], assumptions[], created_at, updated_at
                 → requirement, activities, refs, taskLinks
  Activities   → actions → Fields;  Applications;  References;  TaskLinks
  Statistics   : scope, metric, count (aggregated totals and breakdowns)

Keys are quoted strings: TestCases('<uuid>').
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from src.calm import client, tm_client
from src.calm.dependencies import writes_enabled
from src.calm.tm_dependencies import get_tm_headers, tm_configured, tm_writes_enabled
from src.calm.tools.unified import LIST_ROW_LIMIT, _group_key

_TM_HOW = ("Narrow with filter (OData $filter, e.g. \"priority_code eq '10'\"), count with summarize_by "
           f"or count=true, or page with top (at most {LIST_ROW_LIMIT}) and skip.")


def _counted(result: Any, summarize_by: Any = None, whole: bool = True) -> Any:
    """A TM list answer the agent can't miscount: counts made here over the whole
    read, the exact total, and never more than LIST_ROW_LIMIT rows (a longer list
    is read and counted wrongly by the agent)."""
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        if summarize_by is not None:
            raise ValueError("summarize_by needs a list of rows; this answer is not one")
        return result
    items = [r for r in result["items"] if isinstance(r, dict)]
    if summarize_by is not None:
        if not whole:
            raise ValueError("summarize_by counts the whole set — drop top / skip")
        names = sorted({k for r in items for k in r})
        fields = []
        for f in client._as_list(summarize_by):
            hit = next((n for n in names if client._squash(n) == client._squash(f)), None)
            if hit is None and items:
                raise ValueError(f"rows have no field '{f}'. Group on: {', '.join(names)}")
            fields.append(hit or f)
        if not fields:
            raise ValueError("summarize_by needs one or more field names")
        groups: dict = {}
        for r in items:
            key = tuple(_group_key(r.get(f)) for f in fields)
            groups[key] = groups.get(key, 0) + 1
        out = [{**{f: ("(none)" if v is None else v) for f, v in zip(fields, key)}, "Count": n}
               for key, n in sorted(groups.items(), key=lambda kv: tuple(client._natural(v) for v in kv[0]))]
        return {"Grouped By": fields, "Groups": out, "Total": len(items),
                "Check": {"Rows Read": len(items), "Groups Add Up": sum(groups.values()) == len(items)}}
    total = len(items) if whole else result.get("count")
    if len(items) <= LIST_ROW_LIMIT:
        return {**result, "Total": total} if total is not None else result
    out = {k: v for k, v in result.items() if k not in ("items", "next_link")}
    return {**out, "Total": total if total is not None else f"more than {len(items)}", "Returned": 0,
            "Rows Not Returned": (f"{len(items)} rows — more than {LIST_ROW_LIMIT}, too many to read or count "
                                  "reliably, so none are returned; the total is exact. Answer 'how many' "
                                  "from it or from summarize_by, never by counting rows."),
            "How To Get Rows": _TM_HOW}


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def tm_health(ctx: Context) -> dict:
        """Diagnostic for the OPTIONAL BTP Test Management OData connection.

        Reports whether the connection is configured (TM_* env vars or x-tm-*
        headers) and, when it is, probes the service's unauthenticated /health
        endpoint (which also reports PostgreSQL reachability) and one signed-in
        read: "authorized" false means the credential can't read data. Use Statistics
        afterwards to judge whether the CALM→repository feed is populated.
        Never fails when unconfigured — this feature is additive and optional.
        """
        configured = tm_configured(ctx)
        result: dict = {
            "service": "btp-test-management-odata",
            "configured": configured,
            "tm_writes_enabled": tm_writes_enabled(),
            "calm_writes_enabled": writes_enabled(),
        }
        if not configured:
            result["hint"] = (
                "Optional feature — set TM_BASE_URL + TM_TOKEN_URL + TM_CLIENT_ID + "
                "TM_CLIENT_SECRET env vars, or send x-tm-* request headers, to enable "
                "the tm_* tools. All CALM tools work without it."
            )
            return result
        h = get_tm_headers(ctx)
        result["base_url"] = h.base_url
        result["token_source"] = h.token_source
        try:
            result["health"] = tm_client.service_health(h.base_url)
            result["reachable"] = True
        except Exception as exc:  # keep diagnostics non-fatal
            result["reachable"] = False
            result["error"] = str(exc)[:300]
        # /health needs no sign-in: prove the credential can read data too.
        try:
            tm_client.get_test_cases(h.token, h.base_url, top=1, select="id")
            result["authorized"] = True
        except Exception as exc:  # noqa: BLE001 — a diagnostic never fails
            result["authorized"] = False
            result["authorization_error"] = str(exc)[:300]
        return result

    @mcp.tool()
    def get_tm_statistics(ctx: Context) -> dict:
        """BTP Test Management repository (OPTIONAL OData feed, NOT SAP Cloud ALM
        native): aggregated counts — totals per entity plus breakdowns by scenario
        type, priority and prepared flag.

        Use the tm_* tools only for the separate BTP Test Management OData repository;
        for SAP Cloud ALM's own test cases use calm_resource(resource="test_cases").
        This is the quickest way to check whether the CALM→repository sync has data:
        zero or stale counts mean the inbound feed has not run.
        """
        h = get_tm_headers(ctx)
        return tm_client.get_statistics(h.token, h.base_url)

    @mcp.tool()
    def get_tm_test_cases(
        ctx: Context,
        filter: str | None = None,
        select: str | None = None,
        expand: str | None = None,
        orderby: str | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool = False,
        updated_since: str | None = None,
        summarize_by: list[str] | str | None = None,
    ) -> dict:
        """List test cases from the OPTIONAL BTP Test Management OData repository
        (NOT SAP Cloud ALM native — for CALM's own test cases use
        calm_resource(resource="test_cases")). OData query.

        Args:
            filter: OData $filter, e.g. "scenario_type eq 'negative'".
            select: comma list, e.g. "external_id,title,scenario_type,priority_code".
            expand: e.g. "activities($expand=actions)" or "requirement".
            orderby: e.g. "updated_at desc".
            top / skip: paging.
            count: include the total match count.
            updated_since: DELTA SYNC watermark — ISO timestamp (e.g.
                "2026-08-01T00:00:00Z"). Adds `updated_at gt <ts>` to the filter
                and orders by updated_at; keep the highest updated_at you
                processed and pass it as the next watermark.
            summarize_by: field(s) to count by, over every matching test case
                (e.g. ["priority_code"]) — exact counts made by the server. Use it
                for ANY "how many"; never count rows yourself.

        Without top / skip the whole set is read and "Total" is exact. An answer
        carries at most 300 rows: beyond that it gives the Total and how to narrow
        or page instead.

        Fields: id, external_id, title, testing_requirement_id, project_id,
        scope_id, solution_process_id, priority_code (10=Very High … 40=Low),
        is_prepared, scenario_type, preconditions[], test_data[],
        postconditions[], assumptions[], created_at, updated_at.
        """
        h = get_tm_headers(ctx)
        return _counted(tm_client.get_test_cases(
            h.token, h.base_url,
            filter=filter, select=select, expand=expand, orderby=orderby,
            top=top, skip=skip, count=count, updated_since=updated_since,
        ), summarize_by, whole=top is None and skip is None)

    @mcp.tool()
    def get_tm_test_case_full(test_case_id: str, ctx: Context) -> dict:
        """Return ONE test case with its complete tree in a single request:
        activities → actions → field entries, plus applications, references
        and task links.

        Args:
            test_case_id: the test case id (quoted-string OData key).
        """
        if not test_case_id:
            raise ValueError("test_case_id is required")
        h = get_tm_headers(ctx)
        return tm_client.get_test_case_full(h.token, h.base_url, test_case_id)

    @mcp.tool()
    def get_tm_requirements(
        ctx: Context,
        filter: str | None = None,
        expand_test_cases: bool = False,
        top: int | None = None,
        count: bool = False,
        summarize_by: list[str] | str | None = None,
    ) -> dict:
        """List testing requirements from the OPTIONAL BTP Test Management OData
        repository (NOT SAP Cloud ALM native — for CALM requirements use
        calm_resource(resource="requirements")).

        Fields: id, tr_id (e.g. "TR-0001"), wricef, short_desc, created_at,
        updated_at. Set expand_test_cases=true to include each requirement's
        linked test cases. summarize_by (e.g. ["wricef"]) gives exact counts
        made by the server — use it for any "how many". Without top "Total" is
        exact; an answer carries at most 300 rows (beyond that: the Total and
        how to narrow).
        """
        h = get_tm_headers(ctx)
        return _counted(tm_client.get_requirements(
            h.token, h.base_url,
            filter=filter, expand_test_cases=expand_test_cases, top=top, count=count,
        ), summarize_by, whole=top is None)

    @mcp.tool()
    def tm_odata_read(entity_set: str, ctx: Context, query: str | None = None) -> dict:
        """Generic OData GET against any Test Management entity set — the read
        escape hatch when no dedicated tool fits.

        Args:
            entity_set: Requirements | TestCases | Activities | Actions |
                Fields | Applications | References | TaskLinks | Statistics |
                $metadata — or a single-entity path like "TestCases('<uuid>')".
            query: raw OData query string exactly as in Postman, e.g.
                "$filter=updated_at gt 2026-08-01T00:00:00Z&$orderby=updated_at&$top=500".

        Returns {items: [...], count?, next_link?} for collections, or the
        entity/raw payload otherwise.
        """
        if not entity_set:
            raise ValueError("entity_set is required")
        h = get_tm_headers(ctx)
        paged = any(p in (query or "") for p in ("$top", "$skip", "%24top", "%24skip"))
        return _counted(tm_client.odata_read(h.token, h.base_url, entity_set, query=query), whole=not paged)
