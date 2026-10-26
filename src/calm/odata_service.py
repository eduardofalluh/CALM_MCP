"""SAP Cloud ALM's OData v4 entity services, driven by their own ``$metadata``.

Documents (``calm-documents``), Features (``calm-features``) and Test Management
(``calm-testmanagement``) are SAP CAP services: entity sets keyed by ``uuid``, an
ETag per entity that PATCH / DELETE must send back as If-Match, and a
``$metadata`` document naming every property. The schema is read from the
tenant — once per tenant and service — so rows, filters and write payloads use
SAP's real property names, and a misspelt field is refused with the list of real
ones instead of being silently ignored (an ignored filter returns everything).

Rows use the same Title-Case labels as the rest of the server, derived from the
property name by one fixed rule (``displayId`` -> "Display ID", ``statusCode`` ->
"Status Code", ``parent_ID`` -> "Parent ID"; ``uuid`` -> "ID", ``createdAt`` ->
"Created", ``modifiedAt`` -> "Last Changed"), so they stay stable for agents.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterable
from urllib.parse import quote

import requests

from . import client, http_retry

log = logging.getLogger("calm-mcp.odata")

# (tenant base URL, service) -> {entity set name: EntitySet dict}
_SCHEMAS: dict[tuple[str, str], dict[str, dict]] = {}
_SCHEMAS_MAX = 64              # the base URL can come from the caller: bound the memory
_METADATA_MAX_BYTES = 5_000_000

# Read-only bookkeeping CAP fills in itself; never sent on a write.
_MANAGED = frozenset({"createdAt", "createdBy", "modifiedAt", "modifiedBy"})
# Free text that can be long; left out of list rows, kept on get.
LONG_TEXT = frozenset({"content", "contentHtml", "htmlContent", "text", "documentText", "body"})

_ENTITY_TYPE = re.compile(r'<EntityType\s+Name="([^"]+)"[^>]*>(.*?)</EntityType>', re.S)
_PROPERTY = re.compile(r"<Property\s+([^>]*?)/?>")
_NAVIGATION = re.compile(r"<NavigationProperty\s+([^>]*?)/?>")
_KEY = re.compile(r'<PropertyRef\s+Name="([^"]+)"')
_ENTITY_SET = re.compile(r'<EntitySet\s+Name="([^"]+)"\s+EntityType="([^"]+)"')
_ATTR = re.compile(r'(\w+)="([^"]*)"')


class SchemaUnavailable(RuntimeError):
    """The service's $metadata could not be read (usually a missing scope)."""


def parse_metadata(xml: str) -> dict[str, dict]:
    """CSDL XML -> {entity set: {name, type, key, props, navs}}."""
    types: dict[str, dict] = {}
    for type_name, body in _ENTITY_TYPE.findall(xml):
        props: dict[str, dict] = {}
        for attrs in _PROPERTY.findall(body):
            a = dict(_ATTR.findall(attrs))
            if a.get("Name"):
                props[a["Name"]] = {"type": a.get("Type", ""), "nullable": a.get("Nullable") != "false"}
        navs: dict[str, dict] = {}
        for attrs in _NAVIGATION.findall(body):
            a = dict(_ATTR.findall(attrs))
            if a.get("Name"):
                target = a.get("Type", "")
                navs[a["Name"]] = {"type": target, "many": target.startswith("Collection(")}
        types[type_name] = {"key": _KEY.findall(body), "props": props, "navs": navs}
    sets: dict[str, dict] = {}
    for set_name, entity_type in _ENTITY_SET.findall(xml):
        short = entity_type.rsplit(".", 1)[-1]
        if short in types:
            sets[set_name] = dict(types[short], name=set_name, type=short)
    return sets


def _root(base_url: str | None, service: str) -> str:
    return f"{client._base_url(base_url)}/api/{service}/v1"


def schema(service: str, token: str, base_url: str | None = None) -> dict[str, dict]:
    """The service's entity sets, read from $metadata once per tenant."""
    root = _root(base_url, service)
    cache_key = (root, service)
    if cache_key in _SCHEMAS:
        return _SCHEMAS[cache_key]
    url = f"{root}/$metadata"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/xml"}
    resp = http_retry.send(
        lambda t: requests.get(url, headers=headers, timeout=t),
        "GET", url, repeatable=True, timeout=client.REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise SchemaUnavailable(
            f"HTTP {resp.status_code} reading the {service} schema ($metadata)"
        )
    text = resp.text or ""
    if len(text) > _METADATA_MAX_BYTES:
        raise SchemaUnavailable(f"the {service} schema is unexpectedly large ({len(text)} bytes)")
    sets = parse_metadata(text)
    if not sets:
        raise SchemaUnavailable(f"the {service} schema lists no entity sets")
    while len(_SCHEMAS) >= _SCHEMAS_MAX:
        _SCHEMAS.pop(next(iter(_SCHEMAS)))
    _SCHEMAS[cache_key] = sets
    return sets


def entity_set(service: str, name: str, token: str, base_url: str | None = None) -> dict:
    sets = schema(service, token, base_url)
    if name not in sets:
        raise SchemaUnavailable(
            f"the {service} service has no '{name}' entity set (it has: {sorted(sets)})"
        )
    return sets[name]


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #

_ACRONYMS = frozenset({"id", "url", "uri", "api", "sap"})
_LABELS = {"uuid": "ID", "id": "ID", "createdAt": "Created", "modifiedAt": "Last Changed",
           "createdBy": "Created By", "modifiedBy": "Last Changed By"}


def label(prop: str) -> str:
    """CALM property name -> the row label agents see (fixed rule, see module doc)."""
    if prop in _LABELS:
        return _LABELS[prop]
    if prop.startswith("to") and prop[2:3].isupper():  # navigation: toURLReferences
        prop = prop[2:]
    text = re.sub(r"_ID$", "Id", prop)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", text).replace("_", " ")
    return " ".join(w.upper() if w.lower() in _ACRONYMS else w[:1].upper() + w[1:] for w in text.split())


def _plain(value: Any) -> Any:
    if isinstance(value, str) and client._HTML_TAG.search(value):
        return client._rich_text_to_plain(value)
    return value


def format_row(item: dict, *, long_text: bool = True) -> dict:
    """An OData entity as a row: every property under its label, expanded
    navigations as nested rows, rich text as plain text. ``long_text=False``
    drops the free-text body fields (for compact lists)."""
    out: dict[str, Any] = {}
    for key, value in item.items():
        if key.startswith("@") or (not long_text and key in LONG_TEXT):
            continue
        if isinstance(value, dict):
            out[label(key)] = format_row(value, long_text=long_text)
        elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            out[label(key)] = [format_row(v, long_text=long_text) for v in value]
        else:
            out[label(key)] = _plain(value)
    return out


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_NUMERIC = ("Edm.Int16", "Edm.Int32", "Edm.Int64", "Edm.Decimal", "Edm.Double", "Edm.Byte")


def _literal(value: Any, edm_type: str) -> str:
    """An OData v4 literal for ``value`` — values are escaped, never spliced raw."""
    if edm_type == "Edm.Guid":
        if not _GUID.match(str(value)):
            raise ValueError(f"{value!r} is not a valid ID (UUID)")
        return str(value)
    if edm_type == "Edm.Boolean":
        if isinstance(value, bool):
            return "true" if value else "false"
        if str(value).lower() in ("true", "false"):
            return str(value).lower()
        raise ValueError(f"{value!r} is not true/false")
    if edm_type in _NUMERIC:
        if isinstance(value, bool) or not re.match(r"^-?\d+(\.\d+)?$", str(value)):
            raise ValueError(f"{value!r} is not a number")
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _filter(es: dict, filters: dict[str, Any]) -> str:
    clauses = []
    for prop, value in filters.items():
        values = value if isinstance(value, (list, tuple, set)) else [value]
        edm = es["props"][prop]["type"]
        ors = [f"{prop} eq {_literal(v, edm)}" for v in values]
        clauses.append(ors[0] if len(ors) == 1 else "(" + " or ".join(ors) + ")")
    return " and ".join(clauses)


def unknown_fields(es: dict, names: Iterable[str]) -> list[str]:
    return [n for n in names if n not in es["props"] and n not in es["navs"]]


def list_raw(
    service: str, set_name: str, token: str, base_url: str | None = None,
    filters: dict[str, Any] | None = None, expand: Iterable[str] = (),
) -> list[dict]:
    """Every entity of the set matching ``filters`` ({property: value or [values]},
    exact match, server-side), paged to completion."""
    es = entity_set(service, set_name, token, base_url)
    filters = {k: v for k, v in (filters or {}).items() if v is not None and v != ""}
    bad = unknown_fields(es, filters)
    if bad:
        raise ValueError(f"{set_name} has no field(s) {bad}; filterable fields: {sorted(es['props'])}")
    query = []
    if filters:
        query.append("$filter=" + quote(_filter(es, filters), safe=""))
    expand = [n for n in expand if n in es["navs"]]
    if expand:
        query.append("$expand=" + ",".join(expand))
    url = f"{_root(base_url, service)}/{set_name}" + ("?" + "&".join(query) if query else "")
    return [r for r in client._get_all(url, token) if isinstance(r, dict)]


def _key_url(service: str, es: dict, base_url: str | None, uuid: str) -> str:
    if not _GUID.match(uuid):
        raise ValueError(f"{uuid!r} is not a valid ID (UUID)")
    return f"{_root(base_url, service)}/{es['name']}/{uuid}"


def resolve_uuid(
    service: str, set_name: str, token: str, ident: str, base_url: str | None = None,
    project_id: str | None = None,
) -> str:
    """A UUID as given, or the UUID of the entity with that display ID."""
    ident = str(ident or "").strip()
    if not ident:
        raise ValueError("resource_id is required: the ID (UUID) or display ID")
    if _GUID.match(ident):
        return ident
    es = entity_set(service, set_name, token, base_url)
    if "displayId" not in es["props"]:
        raise ValueError(f"'{ident}' is not a UUID, and {set_name} have no display ID to look it up by")
    filters: dict[str, Any] = {"displayId": ident}
    if project_id and "projectId" in es["props"]:
        filters["projectId"] = project_id
    hits = list_raw(service, set_name, token, base_url, filters)
    # Re-check locally: an ID must match exactly even if a filter were ignored.
    hits = [h for h in hits if str(h.get("displayId", "")).strip().lower() == ident.lower()]
    if not hits:
        raise client.NotFound(f"No {set_name[:-1].lower()} with display ID '{ident}'")
    if len(hits) > 1:
        raise client.Ambiguous(
            f"{len(hits)} {set_name.lower()} have display ID '{ident}' — pass project_id or the UUID",
            [format_row(h, long_text=False) for h in hits[:10]],
        )
    return str(hits[0].get("uuid") or hits[0].get("id"))


def get_raw(
    service: str, set_name: str, token: str, ident: str, base_url: str | None = None,
    project_id: str | None = None, expand_all: bool = True,
) -> tuple[dict, str | None]:
    """(entity, etag) by UUID or display ID, with every navigation expanded."""
    es = entity_set(service, set_name, token, base_url)
    uuid = resolve_uuid(service, set_name, token, ident, base_url, project_id)
    url = _key_url(service, es, base_url, uuid)
    if expand_all and es["navs"]:
        url += "?$expand=" + ",".join(es["navs"])
    try:
        data, etag = client._get_with_meta(url, token)
    except RuntimeError as exc:
        if client._is_http_404(exc):
            raise client.NotFound(f"No {set_name[:-1].lower()} with ID {uuid}") from exc
        raise
    if not isinstance(data, dict) or not data:
        raise client.NotFound(f"No {set_name[:-1].lower()} with ID {uuid}")
    return data, etag or data.get("@odata.etag")


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #

def writable_fields(es: dict) -> list[str]:
    return sorted((set(es["props"]) - set(es["key"]) - _MANAGED) | set(es["navs"]))


def body_for(es: dict, data: dict) -> dict:
    """Write payload with SAP's field names: snake_case -> camelCase, plus the
    friendly names (status -> statusCode, name -> title, …). A key SAP has no
    writable field for is refused with the list of the real ones."""
    writable = writable_fields(es)
    body: dict[str, Any] = {}
    bad = []
    for key, value in data.items():
        target = next((k for k in (key, client._camel(key), *_ALIASES.get(key, ()),
                                   *(("title",) if key == "name" else ()))
                       if k in writable), None)
        if target is None:
            bad.append(key)
        else:
            body[target] = value
    if bad:
        raise ValueError(f"{es['name']} has no writable field(s) {bad}. Writable fields: {writable}")
    return body


CREATE_LOOKBACK = 300.0  # seconds of clock skew allowed when confirming a create


def create(
    service: str, set_name: str, token: str, body: dict, base_url: str | None = None,
    user_email: str | None = None, confirm_by: tuple[str, ...] = ("title", "projectId"),
) -> tuple[dict, str | None]:
    """POST one entity -> (entity, note). If SAP drops the answer, look for it
    (same ``confirm_by`` values, created in the last few minutes) before
    reporting a doubt — it is never re-sent, so no duplicate can come from here."""
    es = entity_set(service, set_name, token, base_url)
    since = time.time()
    url = f"{_root(base_url, service)}/{set_name}"
    try:
        result = client._write("POST", url, token, body, user_email=user_email)
    except http_retry.WriteUnconfirmed as exc:
        found = _find_created(service, es, token, body, base_url, since, confirm_by)
        if found is None:
            raise
        return found, ("SAP dropped the connection, but the item was created — confirmed "
                       "by reading it back.")
    return (result if isinstance(result, dict) else {}), None


def _find_created(service, es, token, body, base_url, since, confirm_by) -> dict | None:
    filters = {k: body[k] for k in confirm_by if k in body and k in es["props"]}
    if not filters or "createdAt" not in es["props"]:
        return None
    http_retry._sleep(client.SLOW_WRITE_SETTLE)
    try:
        hits = list_raw(service, es["name"], token, base_url, filters)
    except Exception as exc:  # noqa: BLE001 — "could not check" keeps the original doubt
        log.warning("reading back an unconfirmed create failed: %s", type(exc).__name__)
        return None
    recent = [h for h in hits if (client._ts_epoch(h.get("createdAt")) or 0) >= since - CREATE_LOOKBACK]
    return recent[0] if len(recent) == 1 else None


def update(
    service: str, set_name: str, token: str, ident: str, body: dict,
    base_url: str | None = None, project_id: str | None = None, user_email: str | None = None,
) -> dict:
    """PATCH by UUID or display ID, sending the entity's current ETag as If-Match."""
    es = entity_set(service, set_name, token, base_url)
    if not body:
        raise ValueError("No fields to update — provide at least one field in data.")
    uuid = resolve_uuid(service, set_name, token, ident, base_url, project_id)
    url = _key_url(service, es, base_url, uuid)
    current, etag = client._get_with_meta(url, token)
    etag = etag or (current.get("@odata.etag") if isinstance(current, dict) else None)
    result = client._write("PATCH", url, token, body, if_match=etag or "*", user_email=user_email)
    if isinstance(result, dict) and result:
        return result
    fresh, _ = client._get_with_meta(url, token)
    return fresh if isinstance(fresh, dict) else {"updated": uuid, "fields": body}


def delete(
    service: str, set_name: str, token: str, ident: str, base_url: str | None = None,
    project_id: str | None = None, user_email: str | None = None,
) -> dict:
    es = entity_set(service, set_name, token, base_url)
    uuid = resolve_uuid(service, set_name, token, ident, base_url, project_id)
    url = _key_url(service, es, base_url, uuid)
    _, etag = client._get_with_meta(url, token)
    client._delete(url, token, if_match=etag or "*", user_email=user_email)
    return {"deleted": uuid}


# --------------------------------------------------------------------------- #
# Resource level: list options, rows, Features' legacy columns
# --------------------------------------------------------------------------- #

DOCUMENTS = ("calm-documents", "Documents")
FEATURES = ("calm-features", "Features")
AUTOMATED_TEST_CASES = ("calm-testmanagement", "AutomatedTestCases")

SEARCH_DEFAULT_TOP = 25
# Friendly data keys -> the first of these properties the entity set has.
_ALIASES = {
    "status": ("statusCode", "status"),
    "type": ("typeCode", "documentTypeCode", "type"),
    "priority": ("priorityCode", "priority"),
    "owner": ("ownerId", "owner"),
    "responsible": ("responsibleId",),
    "display_id": ("displayId",),
}
_ID_FIELDS = ("ID", "Display ID", "External ID")


def _prop_for(es: dict, key: str) -> str | None:
    if key in es["props"]:
        return key
    camel = client._camel(key)
    if camel in es["props"]:
        return camel
    for candidate in _ALIASES.get(key, ()):
        if candidate in es["props"]:
            return candidate
    return None


def _top(value: Any) -> int:
    top = value
    if isinstance(top, float) and top.is_integer():
        top = int(top)
    if isinstance(top, str) and top.strip().isdigit():
        top = int(top)
    if isinstance(top, bool) or not isinstance(top, int) or top < 1:
        raise ValueError(f"top must be a whole number of at least 1 (got {value!r})")
    return top


def list_rows(
    spec: tuple[str, str], token: str, base_url: str | None = None,
    project_id: str | None = None, data: dict | None = None, formatter=None,
) -> list[dict] | dict:
    """List an entity set the way tasks list works: exact-match filters on any of
    its fields (server-side), ``search`` (title / ID / display ID, best first),
    ``top`` and ``fields``. Unknown keys are refused, never ignored."""
    service, set_name = spec
    es = entity_set(service, set_name, token, base_url)
    opts = {k: v for k, v in (data or {}).items() if v is not None}
    search, top, fields = opts.pop("search", None), opts.pop("top", None), opts.pop("fields", None)
    if opts.get("project_id"):
        project_id = project_id or opts["project_id"]
    opts.pop("project_id", None)
    filters: dict[str, Any] = {}
    if project_id and "projectId" in es["props"]:
        filters["projectId"] = project_id
    unknown = []
    for key, value in opts.items():
        prop = _prop_for(es, key)
        if prop is None:
            unknown.append(key)
        else:
            filters[prop] = value
    if unknown:
        raise ValueError(
            f"{label(set_name).lower()} list does not support data key(s) {unknown}. Supported: "
            "search (title / ID / display ID, best matches first), top (max rows), fields (row "
            f"fields to return), or any field to match exactly: {sorted(es['props'])}"
        )
    if search is not None and (isinstance(search, bool) or not str(search).strip()):
        raise ValueError("search must be non-empty text (a title, or part of one, or an ID)")
    top = _top(top) if top is not None else (SEARCH_DEFAULT_TOP if search is not None else None)
    fmt = formatter or (lambda item: format_row(item, long_text=False))
    rows = [fmt(r) for r in list_raw(service, set_name, token, base_url, filters)]
    if search is not None:
        search = " ".join(str(search).split())
        rows = client.search_rows(rows, search, _ID_FIELDS)
    total = len(rows)
    if top is not None:
        rows = rows[:top]
    if fields is not None:
        wanted = client._as_list(fields)
        known = {k for r in rows for k in r} | {label(p) for p in es["props"]}
        bad = [f for f in wanted if f not in known]
        if bad:
            raise ValueError(f"unknown field(s) {bad}; row fields: {sorted(known)}")
        rows = [{k: r.get(k) for k in dict.fromkeys(["ID", *wanted])} for r in rows]
    if top is None:
        return rows
    result: dict[str, Any] = {"Total Matching": total, "Returned": len(rows)}
    if search is not None:
        result["Search"] = search
    if len(rows) < total:
        result["Note"] = (f"Showing the first {len(rows)} of {total} matching items"
                          + (" (best matches first)" if search is not None else "")
                          + ". Raise top or narrow the filters to see more.")
    elif search is not None and not total:
        result["Note"] = "Nothing in this project matches the search."
    result[label(set_name)] = rows
    return result


def feature_row(item: dict, *, long_text: bool = False) -> dict:
    """A feature with the columns agents already use first (ID, Project ID, Name,
    Description, Status, External ID), read from SAP's real field names, then
    every other field."""
    row = {
        "ID": item.get("uuid") or item.get("id"),
        "Project ID": item.get("projectId") or item.get("project"),
        "Name": item.get("title") or item.get("name"),
        "Description": _plain(item.get("description")),
        "Status": item.get("statusCode") or item.get("status"),
        "External ID": item.get("externalId"),
    }
    covered = {"uuid", "id", "projectId", "project", "title", "name", "description",
               "statusCode", "status", "externalId"}
    rest = format_row({k: v for k, v in item.items() if k not in covered}, long_text=long_text)
    row.update({k: v for k, v in rest.items() if k not in row})
    return row
