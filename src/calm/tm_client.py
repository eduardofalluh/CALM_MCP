"""
BTP Test Management OData V4 client.

This talks to the *optional* BTP Test Management repository — a CAP OData V4
service over PostgreSQL deployed on Cloud Foundry — NOT to SAP Cloud ALM itself.
The repository mirrors CALM test-management entities (Requirements, TestCases
with activities → actions → fields, applications, references, task links) and
keys them to CALM via project_id / scope_id / solution_process_id / external_id.

Sync model
----------
The OData interface is a live query surface: every call returns the current
repository state, so reads are always "in sync" by construction. Incremental
(delta) reads use the documented watermark pattern:

    $filter=updated_at gt <last-processed-timestamp>&$orderby=updated_at

Concurrency: PATCH and DELETE require an ``If-Match`` ETag (428 when missing,
412 when stale). Single-entity GETs return the current ETag, which the update
and delete helpers auto-fetch when the caller does not supply one.

Keys are quoted strings: TestCases('<uuid>'), not TestCases(<uuid>).
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests

log = logging.getLogger("calm-mcp.tm")

REQUEST_TIMEOUT = 60  # seconds

# Entity sets exposed by TestManagementService (from the service $metadata).
TM_ENTITY_SETS = {
    "Requirements",
    "TestCases",
    "Activities",
    "Actions",
    "Fields",
    "Applications",
    "References",
    "TaskLinks",
    "Statistics",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _raise_for_status(resp: requests.Response, url: str) -> None:
    if resp.status_code >= 400:
        raise RuntimeError(
            f"TM OData request failed: HTTP {resp.status_code} at {url} — "
            f"{(resp.text or '')[:500]}"
        )


def _params_from_query(query: str | None) -> dict[str, str] | None:
    """Parse a raw OData query string ("$filter=...&$top=10") into params.

    requests re-encodes the parsed pairs, so callers can write filters with
    plain spaces and quotes exactly as they would in Postman.
    """
    if not query:
        return None
    return dict(parse_qsl(query.lstrip("?"), keep_blank_values=True))


def _odata_key(value: str) -> str:
    """Escape a value for use inside an OData key, e.g. TestCases('<value>').

    OData doubles an embedded single quote. Ids are normally GUIDs with no
    special characters, but escaping is cheap and closes a breakage/injection
    class if a non-GUID key ever flows through.
    """
    return str(value).replace("'", "''")


def _normalize(payload: Any) -> Any:
    """Flatten the OData collection envelope into {items, count?, next_link?}."""
    if isinstance(payload, dict) and "value" in payload:
        out: dict[str, Any] = {"items": payload["value"]}
        if "@odata.count" in payload:
            out["count"] = payload["@odata.count"]
        if "@odata.nextLink" in payload:
            out["next_link"] = payload["@odata.nextLink"]
        return out
    return payload


def _get(url: str, token: str, params: dict[str, str] | None = None) -> Any:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    _raise_for_status(resp, url)
    if "xml" in (resp.headers.get("Content-Type") or "") or (resp.text or "").lstrip().startswith("<"):
        return {"metadata_xml": resp.text}
    return resp.json() if (resp.text or "").strip() else {}


def _get_all(url: str, token: str, params: dict[str, str] | None = None) -> Any:
    """Fetch a COMPLETE TM OData collection, following @odata.nextLink to the end.

    The CAP OData V4 service pages large collections and signals continuation via
    a relative ``@odata.nextLink``. The single-page ``_get`` surfaced that link but
    never followed it, so any collection past one server page was silently cut off
    — the same truncation class the CALM-native client already guards against.

    Returns the same normalized envelope as ``_normalize`` (``{items, count?}``),
    with every page concatenated and ``next_link`` dropped once exhausted. Rows are
    de-duped defensively so an endpoint that loops a link cannot run away. On a hard
    ceiling the shared truncation sink is fed via ``client._record_truncation`` so a
    TM cut-off raises the same user-facing alert as every CALM list.

    Only used when the caller drives no explicit ``$top``/``$skip`` — explicit paging
    and delta-sync watermarks keep their single-page behavior through ``_get``.
    """
    # Reuse the CALM client's ceilings and shared truncation sink.
    from src.calm import client as _calm

    first = _get(url, token, params=params)
    if not isinstance(first, dict) or "value" not in first:
        # metadata_xml, a single entity, or an unexpected shape — nothing to page.
        return _normalize(first)

    items = list(first.get("value", []))
    count = first.get("@odata.count")
    next_link = first.get("@odata.nextLink")

    def _row_id(r: Any) -> Any:
        if isinstance(r, dict):
            for k in ("ID", "id", "uuid", "test_case_id", "tr_id"):
                if r.get(k) is not None:
                    return (k, r[k])
        return id(r)

    seen = {_row_id(r) for r in items}
    requests_made = 1
    current = url
    while next_link:
        if requests_made >= _calm._PAGE_MAX_REQUESTS or len(items) >= _calm._PAGE_MAX_ROWS:
            limit = ("max-requests" if requests_made >= _calm._PAGE_MAX_REQUESTS
                     else "max-rows")
            _calm._record_truncation(url, len(items), limit)
            break
        # Resolve a relative @odata.nextLink against the CURRENT request URL
        # (urljoin keeps the service path, e.g. /odata/v4/..); absolute links pass
        # through unchanged. Chaining against `current` keeps multi-page links correct.
        current = urljoin(current, next_link)
        page = _get(current, token)
        if not isinstance(page, dict):
            break
        batch = page.get("value", [])
        new = [r for r in batch if _row_id(r) not in seen]
        if not new:  # link looped or no further data
            break
        items.extend(new)
        seen.update(_row_id(r) for r in new)
        next_link = page.get("@odata.nextLink")
        requests_made += 1

    out: dict[str, Any] = {"items": items}
    if count is not None:
        out["count"] = count
    return out


def _get_with_etag(url: str, token: str) -> tuple[Any, str | None]:
    """GET a single entity, returning (parsed_json, etag).

    The ETag comes from the response ETag header when present, else from the
    '@odata.etag' body annotation that CAP includes on single-entity reads.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    _raise_for_status(resp, url)
    data = resp.json() if (resp.text or "").strip() else {}
    etag = None
    try:
        etag = resp.headers.get("ETag") or resp.headers.get("etag")
    except Exception:
        etag = None
    if not etag and isinstance(data, dict):
        etag = data.get("@odata.etag")
    return data, etag


def _resolve_etag(url: str, token: str, if_match: str | None) -> str:
    """Return the If-Match token: the caller's value, else fetched, else '*'.

    The service returns 428 on PATCH/DELETE without If-Match; '*' (match any
    current version) is the safe fallback when no ETag can be fetched.
    """
    if if_match:
        return if_match
    try:
        _, etag = _get_with_etag(url, token)
    except Exception:
        etag = None
    return etag or "*"


def _write(method: str, url: str, token: str, body: dict, if_match: str | None = None) -> Any:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if if_match:
        headers["If-Match"] = if_match
    # DEBUG only; never logs Authorization or the request body.
    log.debug("TM write: %s %s (If-Match=%s)", method, url, headers.get("If-Match", "-"))
    resp = requests.request(method, url, headers=headers, data=json.dumps(body), timeout=REQUEST_TIMEOUT)
    _raise_for_status(resp, url)
    if resp.status_code == 204 or not (resp.text or "").strip():
        return {}
    return resp.json()


def _delete(url: str, token: str, if_match: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if if_match:
        headers["If-Match"] = if_match
    log.debug("TM delete: %s (If-Match=%s)", url, headers.get("If-Match", "-"))
    resp = requests.request("DELETE", url, headers=headers, timeout=REQUEST_TIMEOUT)
    _raise_for_status(resp, url)
    if resp.status_code == 204 or not (resp.text or "").strip():
        return {}
    return resp.json()


def _host_root(base_url: str) -> str:
    """https://host/odata/v4/test-management → https://host (for /health)."""
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def service_health(base_url: str) -> Any:
    """GET /health on the service host root. Unauthenticated liveness probe;
    also reports whether the service can reach its PostgreSQL database."""
    url = f"{_host_root(base_url)}/health"
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    _raise_for_status(resp, url)
    return resp.json() if (resp.text or "").strip() else {}


def odata_read(token: str, base_url: str, entity_set: str, query: str | None = None) -> Any:
    """Generic OData GET: {base_url}/{entity_set}?{query}.

    entity_set must be one of TM_ENTITY_SETS, '$metadata', or a single-entity
    path like "TestCases('<uuid>')".
    """
    entity_set = entity_set.strip().lstrip("/")
    root = entity_set.split("(", 1)[0].split("?", 1)[0].split("/", 1)[0]
    if root not in TM_ENTITY_SETS and root != "$metadata":
        raise ValueError(
            f"Unknown entity set '{root}'. Use one of: "
            f"{', '.join(sorted(TM_ENTITY_SETS))} (or '$metadata')."
        )
    url = f"{base_url.rstrip('/')}/{entity_set}"
    params = _params_from_query(query)
    # Page a collection read to exhaustion; leave single-entity ('…'), $metadata,
    # and caller-driven $top/$skip reads as a single request.
    is_collection = root in TM_ENTITY_SETS and "(" not in entity_set
    if is_collection and not (params and ("$top" in params or "$skip" in params)):
        return _get_all(url, token, params=params or None)
    return _normalize(_get(url, token, params=params))


def get_statistics(token: str, base_url: str) -> Any:
    """Aggregated counts per entity plus breakdowns (scenario type, priority,
    prepared flag). Zero/stale counts mean the CALM→repository feed has not run."""
    return _normalize(_get(f"{base_url.rstrip('/')}/Statistics", token))


def get_test_cases(
    token: str,
    base_url: str,
    filter: str | None = None,
    select: str | None = None,
    expand: str | None = None,
    orderby: str | None = None,
    top: int | None = None,
    skip: int | None = None,
    count: bool = False,
    updated_since: str | None = None,
) -> Any:
    """List test cases with full OData query support.

    updated_since implements the delta-sync watermark: it adds
    ``updated_at gt <timestamp>`` to the filter and defaults the ordering to
    ``updated_at`` so callers can keep the highest processed value as the next
    watermark.
    """
    clauses = [c for c in (filter, f"updated_at gt {updated_since}" if updated_since else None) if c]
    params: dict[str, str] = {}
    if clauses:
        params["$filter"] = " and ".join(f"({c})" for c in clauses) if len(clauses) > 1 else clauses[0]
    if select:
        params["$select"] = select
    if expand:
        params["$expand"] = expand
    if orderby:
        params["$orderby"] = orderby
    elif updated_since:
        params["$orderby"] = "updated_at"
    if top is not None:
        params["$top"] = str(top)
    if skip is not None:
        params["$skip"] = str(skip)
    if count:
        params["$count"] = "true"
    tc_url = f"{base_url.rstrip('/')}/TestCases"
    # No explicit $top/$skip → caller wants the whole set, so page to exhaustion.
    # With either present the caller is driving paging (or delta-sync) themselves.
    if top is None and skip is None:
        return _get_all(tc_url, token, params=params or None)
    return _normalize(_get(tc_url, token, params=params or None))


def get_test_case_full(token: str, base_url: str, test_case_id: str) -> Any:
    """One request returns the complete test case tree: activities → actions →
    field entries, plus applications, references and task links."""
    url = f"{base_url.rstrip('/')}/TestCases('{_odata_key(test_case_id)}')"
    params = {"$expand": "activities($expand=actions($expand=fields),applications),refs,taskLinks"}
    return _get(url, token, params=params)


def get_requirements(
    token: str,
    base_url: str,
    filter: str | None = None,
    expand_test_cases: bool = False,
    top: int | None = None,
    count: bool = False,
) -> Any:
    """List testing requirements (tr_id, wricef, short_desc), optionally with
    their linked test cases expanded."""
    params: dict[str, str] = {}
    if filter:
        params["$filter"] = filter
    if expand_test_cases:
        params["$expand"] = "testCases"
    if top is not None:
        params["$top"] = str(top)
    if count:
        params["$count"] = "true"
    req_url = f"{base_url.rstrip('/')}/Requirements"
    # No explicit $top → page the full collection; an explicit $top is caller-driven.
    if top is None:
        return _get_all(req_url, token, params=params or None)
    return _normalize(_get(req_url, token, params=params or None))


# ---------------------------------------------------------------------------
# Writes (PATCH/DELETE require If-Match; auto-fetched when not supplied)
# ---------------------------------------------------------------------------

def create_requirement(token: str, base_url: str, body: dict) -> Any:
    return _write("POST", f"{base_url.rstrip('/')}/Requirements", token, body)


def create_test_case(token: str, base_url: str, body: dict) -> Any:
    """POST supports deep insert: test case → activities → actions → fields,
    plus applications. preconditions/test_data/postconditions/assumptions are
    JSON string arrays."""
    return _write("POST", f"{base_url.rstrip('/')}/TestCases", token, body)


def update_test_case(token: str, base_url: str, test_case_id: str, fields: dict, if_match: str | None = None) -> Any:
    url = f"{base_url.rstrip('/')}/TestCases('{_odata_key(test_case_id)}')"
    etag = _resolve_etag(url, token, if_match)
    return _write("PATCH", url, token, fields, if_match=etag)


def delete_requirement(token: str, base_url: str, requirement_id: str, if_match: str | None = None) -> dict:
    url = f"{base_url.rstrip('/')}/Requirements('{_odata_key(requirement_id)}')"
    etag = _resolve_etag(url, token, if_match)
    _delete(url, token, if_match=etag)
    return {"deleted": requirement_id, "cascade": "requirement's test cases, activities, actions and fields"}


def delete_test_case(token: str, base_url: str, test_case_id: str, if_match: str | None = None) -> dict:
    url = f"{base_url.rstrip('/')}/TestCases('{_odata_key(test_case_id)}')"
    etag = _resolve_etag(url, token, if_match)
    _delete(url, token, if_match=etag)
    return {"deleted": test_case_id}


def odata_write(token: str, base_url: str, method: str, path: str, body: dict, if_match: str | None = None) -> Any:
    """Generic escape hatch for POST/PATCH against any service path
    (e.g. "Activities('<uuid>')"). Does NOT auto-fetch ETags — pass if_match
    explicitly for PATCH, or use the dedicated typed tool which does."""
    method = method.upper().strip()
    if method not in ("POST", "PATCH"):
        raise ValueError("method must be POST or PATCH")
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    return _write(method, url, token, body, if_match=if_match)


def odata_delete(token: str, base_url: str, path: str, if_match: str | None = None) -> dict:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    _delete(url, token, if_match=if_match or "*")
    return {"deleted": path}
