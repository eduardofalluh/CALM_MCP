"""
Cloud ALM HTTP client.

1:1 port of the standalone functions from the existing Syntax GenAI Studio agent.
Token is received from the caller (resolved by the dependency layer) — no
credentials are stored or fetched here.
"""

from __future__ import annotations

import contextvars
import html
import json
import logging
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests

from . import http_retry
from .config import build_base_url

REQUEST_TIMEOUT = 30  # seconds


class NotFound(ValueError):
    """A lookup found no item for the given ID / display ID / name. For reads
    the tool answers this as a normal result, not a tool error."""


class Ambiguous(ValueError):
    """Several items match the given name or ID; ``matches`` lists them."""

    def __init__(self, message: str, matches: list | None = None) -> None:
        super().__init__(message)
        self.matches = list(matches or [])


def _is_http_404(exc: Exception) -> bool:
    return "HTTP 404" in str(exc)

log = logging.getLogger("calm-mcp.client")


def _raise_for_status(resp: requests.Response, url: str) -> None:
    """Raise with the API's actual response body on any 4xx/5xx.

    requests' raise_for_status() drops the response body, which hides the real
    reason (400 field errors, 415 media type, 412/428 ETag, …). Surface it — the
    Authorization header and request body are never included here.
    """
    if resp.status_code >= 400:
        raise RuntimeError(
            f"CALM API error: HTTP {resp.status_code} {resp.reason} at {url} — "
            f"response: {(resp.text or '')[:800]}"
        )


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _api_field_names(fields: dict) -> dict:
    """CALM's REST and OData fields are camelCase (scopeId, storyPoints,
    customField1). Agents often pass snake_case in extra_fields (scope_id), which
    CALM ignores or rejects — the item is then created without that field. Convert
    those keys; an explicit camelCase key wins over its snake_case twin."""
    out = {k: v for k, v in fields.items() if "_" not in k}
    for k, v in fields.items():
        if "_" in k:
            out.setdefault(_camel(k), v)
    return out

# ---------------------------------------------------------------------------
# Mappings (taken verbatim from the existing agent)
# ---------------------------------------------------------------------------

TASK_STATUS_MAP = {
    "CIPTKOPEN": "Open", "CIPTKINP": "In Progress", "CIPTKBLK": "Blocked",
    "CIPTKCLOSE": "Done", "CIPTKNO": "Not Relevant",
    "CIPUSOPEN": "Open", "CIPUSINP": "In Progress", "CIPUSBLK": "Blocked",
    "CIPUSCLOSE": "Done", "CIPUSNO": "Not Relevant",
    "CIPREQUOPEN": "Open", "CIPREQUINP": "In Progress", "CIPREQUBLK": "Blocked",
    "CIPREQUCLOSE": "Done", "CIPREQUNO": "Not Relevant",
    "CIPDFCTOPEN": "Open", "CIPDFCTINP": "In Progress", "CIPDFCTBLK": "Blocked",
    "CIPDFCTDONE": "Done",
    "CIPQGOPEN": "Open", "CIPQGBLK": "Blocked", "CIPQGNR": "Not Relevant",
    "CIPQGDONE": "Done",
    "CIPRIOPEN": "Open", "CIPRIINP": "In Progress", "CIPRIDONE": "Done",
}

TASK_TYPE_MAP = {
    "CALMTMPL": "Roadmap Task",
    "CALMTASK": "Project Task",
    "CALMUS": "User Story",
    "CALMST": "Sub-task",
    "CALMREQU": "Requirement",
    "CALMDEF": "Defect",
    "CALMQGATE": "Quality Gate",
    "CALMCHKLI": "Checklist Item",
    "CALMRISK": "Risk",
}

TASK_APPROVAL_STATE_MAP = {
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
    "READY_4_APPR": "Ready for Approval",
    "NO_APPR_REQ": "No Approval Required",
}

PROJECT_STATUS_MAP = {"O": "Active", "C": "Hidden"}

TESTCASE_PRIORITY_MAP = {
    "10": "Very High",
    "20": "High",
    "30": "Medium",
    "40": "Low",
}

# Tasks use the same priorityId scale (10/20/30/40) as test cases.
TASK_PRIORITY_MAP = TESTCASE_PRIORITY_MAP

# ---------------------------------------------------------------------------
# Reverse mappings for writes (human label -> CALM code)
#
# The CALM status code depends on the task *type* (CIPTK* for project tasks,
# CIPUS* for user stories, etc.), so status resolution is type-aware. Callers
# may also pass a raw CALM code directly, in which case it is used unchanged.
# ---------------------------------------------------------------------------

TASK_TYPE_REVERSE_MAP = {label.lower(): code for code, label in TASK_TYPE_MAP.items()}

# Human status label -> CALM code, grouped by task type code.
STATUS_CODE_BY_TYPE = {
    "CALMTASK": {"open": "CIPTKOPEN", "in progress": "CIPTKINP", "blocked": "CIPTKBLK",
                 "done": "CIPTKCLOSE", "not relevant": "CIPTKNO"},
    "CALMTMPL": {"open": "CIPTKOPEN", "in progress": "CIPTKINP", "blocked": "CIPTKBLK",
                 "done": "CIPTKCLOSE", "not relevant": "CIPTKNO"},
    # Sub-tasks (CALMST) use the task (CIPTK*) status codes, not user-story codes.
    "CALMST": {"open": "CIPTKOPEN", "in progress": "CIPTKINP", "blocked": "CIPTKBLK",
               "done": "CIPTKCLOSE", "not relevant": "CIPTKNO"},
    "CALMUS": {"open": "CIPUSOPEN", "in progress": "CIPUSINP", "blocked": "CIPUSBLK",
               "done": "CIPUSCLOSE", "not relevant": "CIPUSNO"},
    "CALMREQU": {"open": "CIPREQUOPEN", "in progress": "CIPREQUINP", "blocked": "CIPREQUBLK",
                 "done": "CIPREQUCLOSE", "not relevant": "CIPREQUNO"},
    "CALMDEF": {"open": "CIPDFCTOPEN", "in progress": "CIPDFCTINP", "blocked": "CIPDFCTBLK",
                "done": "CIPDFCTDONE"},
    "CALMQGATE": {"open": "CIPQGOPEN", "blocked": "CIPQGBLK", "not relevant": "CIPQGNR",
                  "done": "CIPQGDONE"},
    "CALMRISK": {"open": "CIPRIOPEN", "in progress": "CIPRIINP", "done": "CIPRIDONE"},
}

# All known status codes, so a raw code passed by the caller is recognised.
_KNOWN_STATUS_CODES = set(TASK_STATUS_MAP)


def _squash(value: Any) -> str:
    """"User-Story", "user_story", "UserStory" -> "userstory"."""
    return re.sub(r"[\s_\-/]+", "", str(value)).lower()


# What people (and agents) call each type, besides its CALM label.
_TYPE_WORDS = {
    "task": "CALMTASK", "subtask": "CALMST", "story": "CALMUS", "req": "CALMREQU",
    "bug": "CALMDEF", "qgate": "CALMQGATE", "checklist": "CALMCHKLI", "roadmap": "CALMTMPL",
}
_TYPE_BY_WORD = {**{_squash(label): code for code, label in TASK_TYPE_MAP.items()}, **_TYPE_WORDS}


def resolve_task_type_code(value: str) -> str:
    """Accept a human label ("User Story"), an everyday name ("Task", "Subtask",
    "Story", "Bug"; singular or plural, any case or separator) or a raw code
    ("CALMUS") and return the code."""
    if str(value).strip().upper() in TASK_TYPE_MAP:  # already a raw code
        return str(value).strip().upper()
    word = _squash(value)
    for candidate in (word, word[:-1] if word.endswith("s") else None,
                      word[:-3] + "y" if word.endswith("ies") else None):
        if candidate and candidate in _TYPE_BY_WORD:
            return _TYPE_BY_WORD[candidate]
    raise ValueError(
        f"Unknown task type '{value}'. Use one of: "
        f"{', '.join(sorted(TASK_TYPE_MAP.values()))} (or a raw CALM code)."
    )


# Everyday words for each status label.
_STATUS_WORDS = {
    "open": ("new", "todo", "notstarted"),
    "in progress": ("inprogress", "wip", "ongoing", "started", "inwork"),
    "done": ("closed", "complete", "completed", "resolved", "finished"),
    "not relevant": ("notrelevant", "na", "notapplicable", "irrelevant"),
}


def resolve_status_code(value: str, type_code: str) -> str:
    """Resolve a human status label ("In Progress", or an everyday word such as
    "Closed" / "Completed" / "To Do") to the type-specific CALM code.

    A raw CALM status code is accepted and returned unchanged.
    """
    if str(value).strip().upper() in _KNOWN_STATUS_CODES:  # already a raw code
        return str(value).strip().upper()
    by_type = STATUS_CODE_BY_TYPE.get(type_code, {})
    word = _squash(value)
    label = next((lbl for lbl in by_type
                  if word == _squash(lbl) or word in _STATUS_WORDS.get(lbl, ())), None)
    if not label:
        allowed = ", ".join(sorted(by_type)) or "(none for this type)"
        raise ValueError(
            f"Unknown status '{value}' for task type '{type_code}'. "
            f"Allowed labels: {allowed} (or a raw CALM code)."
        )
    return by_type[label]


def resolve_priority(value: Any) -> Any:
    """A task priority as CALM's priorityId: a label ("High") becomes its code
    (20); a number, or a number sent as text, is sent as that number."""
    if isinstance(value, bool):
        raise ValueError(f"Unknown priority {value!r}. Use Very High, High, Medium or Low (or 10/20/30/40).")
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value
    text = " ".join(str(value).split())
    if text.isdigit():
        return int(text)
    code = TESTCASE_PRIORITY_REVERSE_MAP.get(text.lower()) or {
        "critical": "10", "veryhigh": "10", "normal": "30"}.get(_squash(text))
    if not code:
        raise ValueError(f"Unknown priority {value!r}. Use Very High, High, Medium or Low (or 10/20/30/40).")
    return int(code)


_APPROVAL_BY_WORD = {_squash(label): code for code, label in TASK_APPROVAL_STATE_MAP.items()}


def resolve_approval_state(value: Any) -> str:
    """An approval state as CALM's code: "Ready for Approval" -> READY_4_APPR.
    CALM has four; anything else is refused before it reaches SAP."""
    text = str(value).strip()
    if text.upper() in TASK_APPROVAL_STATE_MAP:
        return text.upper()
    code = _APPROVAL_BY_WORD.get(_squash(text))
    if not code:
        raise ValueError(
            f"Unknown approval state {value!r}. CALM has: "
            f"{', '.join(TASK_APPROVAL_STATE_MAP.values())} (or codes {', '.join(TASK_APPROVAL_STATE_MAP)})."
        )
    return code


_DATE_PREFIX = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$")
_DATE_FORMATS = ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y")


def api_date(value: Any, field: str) -> Any:
    """A task date the way the Tasks API takes it (2026-12-31). Accepts that,
    a datetime ("2026-12-31T00:00:00Z" — its date is kept), 2026/12/31, and
    month-name dates ("31 December 2026", "Dec 31, 2026"). An ambiguous date like
    12/11/2026 is refused rather than guessed. Empty values pass through."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return value
    text = " ".join(str(value).split())
    match = _DATE_PREFIX.match(text)
    try:
        if match:
            return date(*(int(part) for part in match.groups())).isoformat()
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
    except ValueError:
        pass
    raise ValueError(f"{field} must be a date like 2026-12-31 (got {value!r})")


TESTCASE_PRIORITY_REVERSE_MAP = {label.lower(): code for code, label in TESTCASE_PRIORITY_MAP.items()}


def resolve_testcase_priority(value: str) -> str:
    """Accept a label ("High") or a raw code ("20") and return the code string."""
    value = str(value)
    if value in TESTCASE_PRIORITY_MAP:  # already a raw code
        return value
    code = TESTCASE_PRIORITY_REVERSE_MAP.get(value.strip().lower())
    if not code:
        raise ValueError(
            f"Unknown test case priority '{value}'. Use "
            f"{', '.join(TESTCASE_PRIORITY_MAP.values())} (or raw code 10/20/30/40)."
        )
    return code


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _get(url: str, token: str, allow_text: bool = False) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    payload = json.dumps({"session_id": str(uuid.uuid4())})
    resp = http_retry.send(
        lambda t: requests.get(url, headers=headers, data=payload, timeout=t),
        "GET", url, repeatable=True, timeout=REQUEST_TIMEOUT,
    )
    _raise_for_status(resp, url)
    try:
        return resp.json()
    except ValueError:
        if allow_text:  # e.g. an OData $metadata document (XML)
            return resp.text
        raise


# Safety ceilings so a misbehaving endpoint can never spin forever.
_PAGE_MAX_REQUESTS = 500
_PAGE_MAX_ROWS = 200_000
# Only probe for a next page when the first page is at least this large; smaller
# collections are certainly complete (CALM's server page caps are >= 100), so we
# avoid a pointless extra request on tiny reference lists (statuses, tags, …).
_PAGE_PROBE_MIN = 50


# --- Truncation alerting ----------------------------------------------------
# A paged read is only ever cut short by the hard ceilings above (never by the
# "100 per page" server cap — that is fully paged through). If a ceiling IS ever
# hit, that is a silent partial result unless we shout about it. _get_all records
# every such event into a per-request sink (a plain list) that the MCP middleware
# installs before each tool call and reads back after, so the agent/user always
# sees a clear "results were truncated" alert — for ANY collection (tasks, test
# cases, features, …), not just one.
#
# Why a ContextVar holding a *mutable list* (and why _get_all only ever appends,
# never .set()): FastMCP runs sync tool functions in a worker thread, which gets
# a *copy* of the context. A fresh .set() inside the worker would not propagate
# back to the middleware. But the copied context shares the *same list object*
# the middleware set beforehand, so appending to it is visible on both sides.
_truncation_sink: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "calm_truncation_sink", default=None
)


def _resource_label(url: str) -> str:
    """A short human label for a collection URL, for truncation messages."""
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else url


def _record_truncation(url: str, count: int, limit: str, reason: str | None = None) -> None:
    """Note that a paged read stopped early and returned a partial result: it hit
    a safety ceiling (``limit``), or a later page failed (``reason``).

    Always logs a warning (ops visibility). Also appends a structured notice to
    the active per-request sink, if one is installed, so the MCP layer can alert
    the end user. Never raises — alerting must not break a tool call.
    """
    label = _resource_label(url)
    if reason:
        msg = (
            f"'{label}' listing was TRUNCATED at {count} rows because {reason} — the "
            f"result is PARTIAL. Try again in a moment."
        )
    else:
        msg = (
            f"'{label}' listing was TRUNCATED at {count} rows after hitting the "
            f"{limit} safety ceiling — the result is PARTIAL. Narrow the query "
            f"(filter by project/tag) or raise the ceiling in client.py."
        )
    log.warning("TRUNCATION: %s (url=%s)", msg, url)
    try:
        sink = _truncation_sink.get()
        if sink is not None:
            sink.append({"resource": label, "count": count, "limit": limit, "message": msg})
    except Exception:  # pragma: no cover - alerting must never break a read
        log.debug("could not record truncation notice", exc_info=True)


def install_truncation_sink() -> tuple[list, Any]:
    """Install a fresh truncation sink for the current context.

    Returns ``(sink, token)``; pass ``token`` to :func:`reset_truncation_sink`.
    Called by the MCP middleware before each tool invocation.
    """
    sink: list = []
    token = _truncation_sink.set(sink)
    return sink, token


def reset_truncation_sink(token: Any) -> None:
    """Restore the truncation sink to its previous value (see install_...)."""
    try:
        _truncation_sink.reset(token)
    except Exception:  # pragma: no cover - defensive
        log.debug("could not reset truncation sink", exc_info=True)


def _row_id(row: Any) -> Any:
    """A stable identity for a collection row, for de-duping across pages.

    Falls back to a hashable snapshot of the row when no id-like key exists, so
    an endpoint that silently ignores ``$skip`` (returning the same page) is
    detected instead of looping forever.
    """
    if isinstance(row, dict):
        for key in ("id", "uuid", "Id", "ID", "guid", "objectId", "displayId"):
            if row.get(key) is not None:
                return (key, row[key])
        return ("__snapshot__", json.dumps(row, sort_keys=True, default=str))
    return ("__value__", str(row))


def _with_skip(url: str, skip: int) -> str:
    """Return ``url`` with ``$skip`` set to ``skip`` (replacing any existing one).

    Only the ``$skip`` segment is touched. The rest of the query string is left
    byte-for-byte intact: re-encoding it (via ``parse_qsl``/``urlencode``)
    corrupts an already-percent-encoded ``$filter`` — e.g. ``projectId%20eq%20<guid>``
    becomes ``projectId+eq+<guid>``, which CALM rejects with HTTP 400
    "The types 'Edm.Boolean' and 'Edm.Guid' are not compatible", silently
    capping a filtered listing at the first page.
    """
    parts = urlparse(url)
    # Drop any existing $skip / %24skip segment, preserving every other segment
    # exactly as received.
    kept = [seg for seg in parts.query.split("&")
            if seg and seg.split("=", 1)[0] not in ("$skip", "%24skip")]
    kept.append(f"%24skip={skip}")
    return urlunparse(parts._replace(query="&".join(kept)))


def _get_all(url: str, token: str) -> list:
    """Fetch a COMPLETE OData collection, never a single truncated page.

    Verified live against a real customer tenant (us10): CALM's two collection
    shapes page differently, and this handles both without ever truncating:

    * **OData envelope** (``{"value": [...]}`` — Test Management, Features):
      caps a page (100 test cases) and does NOT emit ``@odata.nextLink``; the
      client must advance ``$skip`` (confirmed honored — ``$skip=5`` returns a
      different window). ``$top`` is itself capped at 100. We page via ``$skip``
      until a short/empty page.
    * **Bare list** (``[...]`` — e.g. ``calm-tasks/v1/tasks``): returns the
      COMPLETE collection in one response (seen: 4356 rows) and REJECTS
      ``$skip`` with HTTP 400 "not supported yet". So a bare list is already
      complete — return it as-is and never probe.

    ``@odata.nextLink`` is still followed if a service ever emits it. Rows are
    de-duped by id (so an endpoint that ignores ``$skip`` is detected rather
    than looped), the ``$skip`` probe is skipped for small pages, and any
    rejection of ``$skip`` stops paging gracefully (page one is then the best
    complete answer) so listing is never made worse than a single read. Hard
    ceilings bound both the request count and the total rows.
    """
    first = _get(url, token)
    # A bare-list REST endpoint returns the whole collection and rejects $skip —
    # it's already complete, so never probe it.
    if not isinstance(first, dict):
        return list(first or [])

    items = list(first.get("value", []))
    next_link = first.get("@odata.nextLink")

    # (a) Server-driven paging: follow @odata.nextLink to exhaustion.
    if next_link:
        requests_made = 1
        while next_link:
            if requests_made >= _PAGE_MAX_REQUESTS or len(items) >= _PAGE_MAX_ROWS:
                # A ceiling stopped us while more pages remained -> partial result.
                limit = ("max-requests" if requests_made >= _PAGE_MAX_REQUESTS
                         else "max-rows")
                _record_truncation(url, len(items), limit)
                break
            link = next_link if next_link.startswith("http") else urljoin(url, next_link)
            page = _get(link, token)
            if not isinstance(page, dict):
                break
            items.extend(page.get("value", []))
            next_link = page.get("@odata.nextLink")
            requests_made += 1
        return items

    # (b) No link: if the first page looks capped, advance $skip while new rows
    # keep arriving. Small collections are complete, so skip the extra request.
    page_size = len(items)
    if page_size < _PAGE_PROBE_MIN:
        return items
    seen = {_row_id(r) for r in items}
    skip = page_size
    requests_made = 1
    while True:
        if requests_made >= _PAGE_MAX_REQUESTS or len(items) >= _PAGE_MAX_ROWS:
            # A ceiling stopped us -> the last batch was full, so more rows exist.
            limit = ("max-requests" if requests_made >= _PAGE_MAX_REQUESTS
                     else "max-rows")
            _record_truncation(url, len(items), limit)
            break
        try:
            page = _get(_with_skip(url, skip), token)
        except Exception as exc:
            if "HTTP 400" in str(exc):
                # The endpoint doesn't support $skip: page one is the complete
                # answer it can give — don't make listing worse.
                log.debug("stopping $skip paging at skip=%s: %s", skip, exc)
            else:
                # A later page failed even after retries: rows exist that we
                # don't have, so say the result is partial instead of complete.
                _record_truncation(url, len(items), "page-error",
                                   reason=f"fetching the next page failed ({type(exc).__name__})")
            break
        batch = page.get("value", []) if isinstance(page, dict) else (page or [])
        if not batch:
            break
        new = [r for r in batch if _row_id(r) not in seen]
        if not new:  # endpoint ignored $skip, or no further data
            break
        items.extend(new)
        seen.update(_row_id(r) for r in new)
        skip += len(batch)
        requests_made += 1
        if len(batch) < page_size:  # a short page is the last page
            break
    return items


def _write(
    method: str,
    url: str,
    token: str,
    body: dict,
    if_match: str | None = None,
    content_type: str = "application/json",
    user_email: str | None = None,
) -> Any:
    """Send a JSON write request (POST/PATCH) and return the parsed response.

    Returns the parsed JSON body, or {} when the API responds with no content
    (e.g. 204 on a PATCH). `if_match` sets the If-Match header, required by the
    OData services (Process Authoring, Test Management) for PATCH/DELETE.
    `content_type` defaults to application/json; some endpoints (e.g. the
    processmanagement scopes PATCH) require application/merge-patch+json.
    `user_email` is included in request headers for audit logging in CALM.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": content_type,
    }
    if if_match:
        headers["If-Match"] = if_match
    if user_email:
        # SAP Cloud ALM may use these headers for audit logging
        headers["X-User-Email"] = user_email
        headers["X-Forwarded-User"] = user_email
    # DEBUG only; never logs Authorization or the request body.
    log.debug(
        "CALM write: %s %s (Content-Type=%s, If-Match=%s)",
        method, url, content_type, headers.get("If-Match", "-"),
    )
    data = json.dumps(body)
    resp = http_retry.send(
        lambda t: requests.request(method, url, headers=headers, data=data, timeout=t),
        method, url, repeatable=False, timeout=REQUEST_TIMEOUT,
    )
    _raise_for_status(resp, url)
    if resp.status_code == 204 or not (resp.text or "").strip():
        return {}
    return resp.json()


def _delete(url: str, token: str, if_match: str | None = None, user_email: str | None = None) -> dict:
    """Send a DELETE and return {} (or the parsed body if the API returns one)."""
    headers = {"Authorization": f"Bearer {token}"}
    if if_match:
        headers["If-Match"] = if_match
    if user_email:
        headers["X-User-Email"] = user_email
        headers["X-Forwarded-User"] = user_email
    log.debug("CALM delete: %s (If-Match=%s)", url, headers.get("If-Match", "-"))
    resp = http_retry.send(
        lambda t: requests.request("DELETE", url, headers=headers, timeout=t),
        "DELETE", url, repeatable=False, timeout=REQUEST_TIMEOUT,
    )
    _raise_for_status(resp, url)
    if resp.status_code == 204 or not (resp.text or "").strip():
        return {}
    return resp.json()


def _get_with_meta(url: str, token: str) -> tuple[Any, str | None]:
    """GET a single entity, returning (parsed_json, etag).

    etag is taken from the ETag response header when present. Used to obtain the
    If-Match token for OData updates when the caller did not supply one.
    """
    headers = {"Authorization": f"Bearer {token}"}
    resp = http_retry.send(
        lambda t: requests.get(url, headers=headers, timeout=t),
        "GET", url, repeatable=True, timeout=REQUEST_TIMEOUT,
    )
    _raise_for_status(resp, url)
    data = resp.json() if (resp.text or "").strip() else {}
    try:
        etag = resp.headers.get("ETag") or resp.headers.get("etag")
    except Exception:
        etag = None
    return data, etag


def _resolve_etag(
    url: str, token: str, if_match: str | None, body_field: str | None = None
) -> str | None:
    """Return the If-Match token: the caller's value, else fetched from the entity.

    The ETag comes from the response ETag header when present; otherwise it is read
    from the given response body field — `"etag"` for Projects (a numeric timestamp)
    or `"modifiedAt"` for Test Management.
    """
    if if_match:
        return if_match
    data, etag = _get_with_meta(url, token)
    if etag:
        return etag
    if body_field and isinstance(data, dict):
        return data.get(body_field)
    return None


def _tm_if_match(if_match: str | None) -> str:
    """If-Match token for Test Management PATCH/DELETE.

    The entity's modifiedAt timestamp is documented as the ETag but is rejected as
    an If-Match token in practice (412 Precondition Failed). The '*' wildcard —
    match any current version — is accepted, so it's the default here. Callers can
    still pass an explicit ETag for strict optimistic concurrency.
    """
    return if_match or "*"


def _base_url(base_url: str | None = None) -> str:
    return base_url or build_base_url()


# ---------------------------------------------------------------------------
# CALM read functions
# ---------------------------------------------------------------------------

def _tag_in_family(tags: Any, tag: str) -> bool:
    """True if any label in `tags` belongs to the `tag` FAMILY, case-sensitively.

    Mirrors the server-side test-case tag filter exactly, but client-side for
    endpoints (like calm-tasks) that carry tags as a plain inline list of label
    strings and offer no server ``$filter``. A label matches when it is the exact
    tag, or a sub-tag "<tag> - <area>" (startswith "<tag> ") or "<tag>-<area>"
    (startswith "<tag>-"). The trailing space/dash keeps "SIT" from catching
    unrelated tags that merely share the prefix (e.g. "SITE", "SITUATION").
    """
    if not tags:
        return False
    space_prefix = f"{tag} "
    dash_prefix = f"{tag}-"
    for label in tags:
        if not isinstance(label, str):
            continue
        if label == tag or label.startswith(space_prefix) or label.startswith(dash_prefix):
            return True
    return False


def get_tasks(
    project_id: str,
    token: str,
    base_url: str | None = None,
    task_type: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    """Return tasks for a project. `task_type` (human label or raw code) filters to
    one type — e.g. "Requirement" (CALMREQU) for requirements. The type is sent as a
    query param and also filtered client-side so the result is correct even if the
    API ignores the param.

    `tag` filters to tasks carrying that CALM tag, matching the whole tag FAMILY
    case-sensitively — the exact tag PLUS every "<tag> - <area>" sub-tag — the
    same semantics as the test-case tag filter. Unlike test cases (an OData
    service that filters server-side), the Tasks API is a bare-list endpoint with
    no tag filter, so the match is applied client-side; this is lossless because
    the task list is paged to completion first (no page cap drops matches).
    """
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks?projectId={project_id}"
    type_code: str | None = None
    if task_type:
        type_code = resolve_task_type_code(task_type)
        url += f"&type={type_code}"
    items = _get_all(url, token)
    if type_code:
        items = [it for it in items if it.get("type") == type_code]
    if tag:
        items = [it for it in items if _tag_in_family(it.get("tags"), tag)]
    # Resolve team / sprint names once per call, and only when some task carries
    # the ID, so plain task lists cost no extra request.
    team_names = timebox_names = None
    if any(it.get("responsibleTeamId") for it in items):
        team_names = _id_name_map(lambda: get_project_teams(project_id, token, base_url), "team")
    if any(it.get("timeboxId") for it in items):
        timebox_names = _id_name_map(lambda: get_timeboxes(project_id, token, base_url), "timebox")
    return [_format_task(item, team_names, timebox_names) for item in items]


def get_task(
    token: str, task_id: str, base_url: str | None = None, project_id: str | None = None,
) -> dict:
    """One task by UUID, or by Display ID / External ID within ``project_id``.

    Same row as tasks list (team / sprint names resolved). Lets an agent read a
    task back — e.g. to check a write — without listing the whole project.
    """
    ident = str(task_id or "").strip()
    if not ident:
        raise ValueError("resource_id is required: the task's ID (UUID) or display ID")
    if _UUID_RE.match(ident):
        try:
            item = _get(f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{ident}", token)
        except RuntimeError as exc:
            if _is_http_404(exc):
                raise NotFound(f"No task with ID {ident}") from exc
            raise
        if not isinstance(item, dict) or not item:
            raise NotFound(f"No task with ID {ident}")
        project = item.get("projectId") or project_id
        team_names = timebox_names = None
        if project and item.get("responsibleTeamId"):
            team_names = _id_name_map(lambda: get_project_teams(project, token, base_url), "team")
        if project and item.get("timeboxId"):
            timebox_names = _id_name_map(lambda: get_timeboxes(project, token, base_url), "timebox")
        return _format_task(item, team_names, timebox_names)
    if not project_id:
        raise ValueError(
            f"'{ident}' is not a task UUID; to look a task up by its display ID or "
            "external ID, pass project_id as well."
        )
    want = ident.lower()
    hits = [
        r for r in get_tasks(project_id, token, base_url)
        if any(str(r.get(k) or "").strip().lower() == want
               for k in ("Display ID", "External ID (FRICEF)"))
    ]
    if not hits:
        raise NotFound(
            f"No task with display ID or external ID '{ident}' in project {project_id} "
            "(it may be in another project)"
        )
    if len(hits) > 1:
        raise Ambiguous(
            f"{len(hits)} tasks have display/external ID '{ident}': "
            + ", ".join(f"{r['ID']} ({r.get('Title')})" for r in hits[:10])
            + " — use the task's ID (UUID).",
            hits[:10],
        )
    return hits[0]


# Formatted task fields a summary may group by.
TASK_SUMMARY_FIELDS = (
    "Timebox", "Responsible Team", "Type", "Status", "AssigneeName",
    "Priority", "Scope", "Workstream", "Assigned Role",
)

# Named fields whose ID is also on the row: a name missing while the ID is set
# means the name lookup failed, which is not the same as "not assigned".
_NAME_ID = {"Timebox": "Timebox ID", "Responsible Team": "Responsible Team ID", "Scope": "Scope ID"}


def _norm(value: Any) -> str:
    # CALM names can carry stray double spaces ("Consulting  - ABAP").
    return " ".join(str(value).split()).lower()


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    return [value] if isinstance(value, (str, int)) else list(value)


def _label(row: dict, field: str) -> Any:
    """A row's value for grouping/listing: the name, "(unresolved: <id>)" when
    only the ID is known, or None when nothing is assigned."""
    value = row.get(field)
    if value is None and row.get(_NAME_ID.get(field, "")):
        return f"(unresolved: {row[_NAME_ID[field]]})"
    return value


_FILTERS = (("timebox", "Timebox", "Timebox ID"), ("team", "Responsible Team", "Responsible Team ID"))
_UNRESOLVED = re.compile(r"^\(unresolved: (.+)\)$")


def _unwrap_unresolved(value: Any) -> Any:
    """'(unresolved: <id>)' -> '<id>', so a label the server printed filters by ID."""
    match = _UNRESOLVED.match(str(value).strip())
    return match.group(1) if match else value


def filter_tasks(rows: list[dict], timebox: Any = None, team: Any = None) -> list[dict]:
    """Keep tasks in the given timebox(es) / responsible team(s).

    Each filter takes a name (case- and spacing-insensitive) or an ID, or a list
    of them. With neither filter the rows are returned unchanged.
    """
    for (_, name_key, id_key), wanted in zip(_FILTERS, (_as_list(timebox), _as_list(team))):
        if wanted:
            want = {_norm(_unwrap_unresolved(w)) for w in wanted}
            rows = [
                r for r in rows
                if (r.get(name_key) is not None and _norm(r[name_key]) in want)
                or (r.get(id_key) is not None and _norm(r[id_key]) in want)
            ]
    return rows


def unmatched_filters(rows: list[dict], timebox: Any = None, team: Any = None) -> dict:
    """Filter values that match no task in ``rows``, with the values that do exist.

    Lets the caller tell a typo ("Sprnt 1") from a genuinely empty sprint, and
    shows the names to use instead. Empty dict when every value matched.
    """
    report: dict[str, Any] = {}
    for (arg, name_key, id_key), wanted in zip(_FILTERS, (_as_list(timebox), _as_list(team))):
        missing = [w for w in wanted if not filter_tasks(rows, **{arg: w})]
        if missing:
            present = {_label(r, name_key) for r in rows if _label(r, name_key) is not None}
            report[arg] = {"no tasks for": missing,
                           "values present": sorted(present, key=_natural)}
    return report


def classify_unmatched(report: dict, project_id: str, token: str, base_url: str | None = None) -> dict:
    """Tell an existing sprint / team that has no tasks yet from a typo.

    For each filter in ``report`` (from unmatched_filters) the project's sprint or
    team list is read once and every unmatched value is put under "exist but have
    no tasks" or "not found in the project", plus "all names in the project".
    When the list can't be read the entry is left as it was. Mutates and returns
    ``report``.
    """
    for arg, entry in report.items():
        fetch = get_timeboxes if arg == "timebox" else get_project_teams
        try:
            with http_retry.best_effort():
                catalog = [c for c in fetch(project_id, token, base_url) if isinstance(c, dict)]
        except Exception as exc:  # noqa: BLE001 — the plain report still stands
            log.debug("%s list for filter check skipped: %s", arg, type(exc).__name__)
            continue
        known = {_norm(c[k]) for c in catalog for k in ("ID", "Name") if c.get(k)}
        values = entry["no tasks for"]
        entry["exist but have no tasks"] = [v for v in values if _norm(_unwrap_unresolved(v)) in known]
        entry["not found in the project"] = [v for v in values if _norm(_unwrap_unresolved(v)) not in known]
        entry["all names in the project"] = sorted(
            {c["Name"] for c in catalog if c.get("Name")}, key=_natural)[:100]
    return report


def unknown_filter_values(report: dict) -> list:
    """Unmatched values not known to exist (all of them when unchecked)."""
    return [v for e in report.values() for v in e.get("not found in the project", e["no tasks for"])]


def unresolved_filters(rows: list[dict], timebox: Any = None, team: Any = None) -> dict:
    """Name filters that cannot be checked because the name lookup failed.

    When SAP did not answer the team / sprint name lookup, rows carry only the
    IDs, so a filter by name would wrongly look like "no tasks". Returns
    {filter: {"cannot match": [values], "IDs present": [ids]}}; empty when every
    value matched or the names are known.
    """
    report: dict[str, Any] = {}
    for (arg, name_key, id_key), wanted in zip(_FILTERS, (_as_list(timebox), _as_list(team))):
        if not wanted or not any(r.get(id_key) and r.get(name_key) is None for r in rows):
            continue
        missing = [w for w in wanted if not filter_tasks(rows, **{arg: w})]
        if missing:
            ids = sorted({r[id_key] for r in rows if r.get(id_key) and r.get(name_key) is None})
            report[arg] = {"cannot match": missing, "IDs present": ids[:30]}
    return report


# Words too common to tell two task titles apart.
_SEARCH_STOPWORDS = frozenset(
    "a an and are as at be by can could for from has have how if in into is it of "
    "on or our should that the their this to was we what when whether which will "
    "with".split()
)
SEARCH_MIN_OVERLAP = 0.6  # share of the search's words a title must contain


def _words(text: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text).lower())


def search_tasks(rows: list[dict], text: Any) -> list[dict]:
    """Tasks matching ``text``, best match first (see search_rows)."""
    return search_rows(rows, text, ("ID", "Display ID", "External ID (FRICEF)"))


def search_rows(rows: list[dict], text: Any, id_fields: tuple = ("ID", "Display ID")) -> list[dict]:
    """Rows matching ``text``, best match first, for lookups and duplicate checks.

    Matches, in this order: the exact ID / Display ID / External ID; the search
    as a phrase inside the title (case, spacing and punctuation ignored); then
    titles containing at least SEARCH_MIN_OVERLAP of the search's significant
    words, so a reworded title still turns up as a possible duplicate.
    """
    query = " ".join(str(text).split())
    if not query:
        return list(rows)
    exact = query.lower()
    phrase = " ".join(_words(query))
    significant = [w for w in _words(query) if w not in _SEARCH_STOPWORDS] or _words(query)
    scored: list[tuple[float, int, dict]] = []
    for pos, r in enumerate(rows):
        ids = tuple(r.get(f) for f in id_fields)
        title_words = _words(r.get("Title") or "")
        if any(i is not None and str(i).strip().lower() == exact for i in ids):
            score = 3.0
        elif phrase and f" {phrase} " in f" {' '.join(title_words)} ":
            score = 2.0
        elif significant:
            have = set(title_words)
            score = sum(w in have for w in significant) / len(significant)
            if score < SEARCH_MIN_OVERLAP:
                continue
        else:
            continue
        scored.append((-score, pos, r))
    return [r for *_, r in sorted(scored, key=lambda t: t[:2])]


def _effort(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _natural(value: Any) -> tuple:
    # "Sprint 2" before "Sprint 10"; unassigned (None) last.
    if value is None:
        return (1, ())
    parts = re.split(r"(\d+)", str(value).lower())
    return (0, tuple(int(p) if p.isdigit() else p for p in parts))


def check_summary_fields(by: Any) -> list:
    fields = _as_list(by)
    bad = [f for f in fields if f not in TASK_SUMMARY_FIELDS]
    if not fields or bad:
        raise ValueError(
            f"summarize_by must be one or more of {', '.join(TASK_SUMMARY_FIELDS)} "
            f"(got {bad or fields})"
        )
    return fields


def summarize_tasks(rows: list[dict], by: Any) -> dict:
    """Group tasks and return exact counts and effort sums per group.

    A whole project's task list is often too large for an agent's context, and
    summing it by hand is error-prone; this returns the finished table instead.
    """
    fields = check_summary_fields(by)
    groups: dict[tuple, list] = {}
    unresolved = 0
    for r in rows:
        key = tuple(_label(r, f) for f in fields)
        unresolved += any(isinstance(v, str) and v.startswith("(unresolved: ") for v in key)
        g = groups.setdefault(key, [0, 0.0, 0])
        g[0] += 1
        effort = _effort(r.get("Effort"))
        if effort is None:
            g[2] += 1
        else:
            g[1] += effort
    out = []
    for key in sorted(groups, key=lambda k: tuple(_natural(v) for v in k)):
        count, effort, no_effort = groups[key]
        row: dict[str, Any] = {f: ("(none)" if v is None else v) for f, v in zip(fields, key)}
        row.update({"Tasks": count, "Effort": round(effort, 2), "Tasks Without Effort": no_effort})
        out.append(row)
    result: dict[str, Any] = {
        "Grouped By": fields,
        "Groups": out,
        "Total Tasks": len(rows),
        "Total Effort": round(sum(g[1] for g in groups.values()), 2),
        "Tasks Without Effort": sum(g[2] for g in groups.values()),
        "Note": (
            "Computed by the MCP server from every matching task. Effort is summed as "
            "stored in SAP Cloud ALM; '(none)' means not assigned."
        ),
    }
    if unresolved:
        result["Warning"] = (
            f"{unresolved} task(s) are grouped as '(unresolved: <id>)': their team or "
            "sprint name could not be looked up just now, so they are shown by ID. "
            "Counts and effort are still exact."
        )
    return result


def get_projects(token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects"
    return [
        {
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Status": PROJECT_STATUS_MAP.get(item.get("status"), item.get("status")),
            "Purpose": item.get("purpose"),
            "OperationalStatus": item.get("operationalStatus"),
        }
        for item in _get_all(url, token)
    ]


def get_business_processes(token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses"
    return [
        {
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Description": item.get("description"),
        }
        for item in _get_all(url, token)
    ]


def get_solution_processes(token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses"
    return [
        {
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Description": item.get("description"),
            "Status": item.get("status"),
            "Countries": item.get("countries"),
            "State": item.get("state"),
            # Parent link (CALM returns only {id, uri}); join with business_processes.
            "Business Process ID": (item.get("businessProcess") or {}).get("id")
            if isinstance(item.get("businessProcess"), dict) else None,
        }
        for item in _get_all(url, token)
    ]


def get_scopes(token: str, base_url: str | None = None) -> list[dict]:
    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes"
    return [
        {
            "ID": item.get("id"),
            "Project ID": item.get("projectId"),
            "Name": item.get("name"),
            "Description": item.get("description"),
        }
        for item in _get_all(url, token)
    ]


def get_test_cases(
    token: str,
    base_url: str | None = None,
    tag: str | None = None,
    project_id: str | None = None,
    title_contains: str | None = None,
) -> list[dict]:
    """List manual test cases, optionally filtered by tag, project and/or title.

    Each returned case includes its CALM tags (the labels under
    ``toTagAssignments``, e.g. "SIT", "P2P"). All filters are applied
    server-side and combined with ``and``:

    - ``tag``: matches the whole tag FAMILY, case-sensitively. CALM groups
      related tags as "<tag> - <area>" (e.g. "SIT", "SIT - Finance",
      "SIT - POS"), so ``tag="SIT"`` returns the exact "SIT" tag PLUS every
      "SIT - *" sub-tag — everything a user means by "the SIT tag". A trailing
      space/dash on the prefix match keeps it from catching unrelated tags that
      merely share a prefix (e.g. "SITE", "SITUATION").
    - ``project_id``: restrict to one project.
    - ``title_contains``: case-insensitive substring match on the title
      (useful when a grouping like "SIT" lives in the title rather than a tag).
    """
    # Always expand tags so the "Tags" field is populated.
    query = "$expand=toTagAssignments"

    filters: list[str] = []
    if project_id:
        # projectId is Edm.Guid — it must NOT be quoted (quoting yields a 400).
        filters.append(f"projectId eq {project_id}")
    if tag:
        # Tag label is a string; escape embedded single quotes by doubling.
        esc = tag.replace("'", "''")
        # Family match: exact tag OR any sub-tag "<tag> - <area>". Covers both
        # "SIT - Finance" (space-separated) and a bare "SIT-Finance" just in case.
        filters.append(
            "toTagAssignments/any(t:"
            f"t/label eq '{esc}' or "
            f"startswith(t/label,'{esc} ') or "
            f"startswith(t/label,'{esc}-'))"
        )
    if title_contains:
        # Case-insensitive substring match via tolower() on both sides.
        esc = title_contains.replace("'", "''").lower()
        filters.append(f"contains(tolower(title),'{esc}')")
    if filters:
        query += "&$filter=" + quote(" and ".join(filters), safe="")

    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases?{query}"
    # Page through every record — the service caps a page at ~100 test cases, so
    # a single read would silently drop matches (incl. tag matches) beyond it.
    return [_format_test_case(item) for item in _get_all(url, token)]


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# One request returns the case, its tags and its full step tree. The navigation
# names are the same ones the deep-insert create path writes (toActivities /
# toActions), so read and write stay symmetric.
_TEST_CASE_DETAIL_EXPAND = "$expand=toTagAssignments,toTaskAssignments,toActivities($expand=toActions)"

# Attached to every test-case detail so an agent never goes hunting for data the
# public API does not carry. Run status lives in Analytics; testers' per-step
# actual results are UI-only.
TEST_EXECUTION_RESULTS_NOTE = (
    "Test runs and actual results are not part of the test case. Pass/fail status "
    "per test case: calm_resource(resource='analytics', data={'provider': 'DP_TESTS'}) "
    "— needs scope calm-api.tests.read on the service key. The actual result a "
    "tester records on each step is not exposed by any SAP Cloud ALM public API; it "
    "is only visible in the Test Execution app (or an export)."
)


# Rich-text editors emit lower-case tags whose attributes are name=value pairs.
# Anything else in angle brackets — "<Company Code>", "<Code>", "<Table Name>",
# "<HR Manager>", "<S/4HANA system>" — is a placeholder in the step text.
_HTML_TAG = re.compile(
    r"</?(?:p|br|b|i|u|s|em|strong|span|div|font|a|ul|ol|li|h[1-6]|table|thead|tbody|"
    r"tr|td|th|sub|sup|code|pre|blockquote|hr|img|strike|del|ins|mark|small|big)"
    r"""(?:\s+[a-z][a-z0-9:-]*\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))*\s*/?>"""
)


def _rich_text_to_plain(value: Any) -> Any:
    """CALM step fields are rich text (HTML). Keep line structure, drop markup."""
    if not isinstance(value, str) or not value:
        return value
    text = re.sub(r"<br\s*/?>", "\n", value)
    text = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"<li(?:\s[^>]*)?>", "- ", text)
    # Only real HTML tags: plain-text steps use angle brackets for placeholders
    # ("Enter <Company Code>") and those must survive.
    text = _HTML_TAG.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _by_sequence(rows: Any) -> list[dict]:
    items = [r for r in (rows or []) if isinstance(r, dict)]
    # Rows without a sequence keep their API order, after the sequenced ones.
    return sorted(items, key=lambda r: (r.get("sequence") is None, r.get("sequence") or 0))


def _format_test_case_detail(item: dict) -> dict:
    """The list formatter's fields, unchanged, plus the step tree.

    Steps are numbered "<activity>.<action>" by position after sorting on
    `sequence` — the same 1.1 / 1.2 numbering the CALM UI shows.
    """
    out = _format_test_case(item)
    activities: list[dict] = []
    steps: list[dict] = []
    for a_no, activity in enumerate(_by_sequence(item.get("toActivities")), start=1):
        actions = _by_sequence(activity.get("toActions"))
        activities.append({
            "Activity": a_no,
            "ID": activity.get("uuid") or activity.get("id"),
            "Title": activity.get("title"),
            "In Scope": activity.get("isInScope"),
            "Action Count": len(actions),
        })
        for s_no, action in enumerate(actions, start=1):
            steps.append({
                "Step": f"{a_no}.{s_no}",
                "Activity": activity.get("title"),
                "Action": action.get("title"),
                "Instructions": _rich_text_to_plain(action.get("description")),
                "Expected Result": _rich_text_to_plain(action.get("expectedResult")),
                "Evidence Required": action.get("isEvidenceRequired"),
                "Activity ID": activity.get("uuid") or activity.get("id"),
                "Action ID": action.get("uuid") or action.get("id"),
            })
    out["Activities"] = activities
    out["Steps"] = steps
    out["Execution Results"] = TEST_EXECUTION_RESULTS_NOTE
    # The requirements / tasks this test case covers (traceability).
    out["Linked Tasks"] = [
        {"Task ID": t.get("taskId"), "Task Display ID": t.get("taskDisplayId"), "Type": t.get("type")}
        for t in (item.get("toTaskAssignments") or []) if isinstance(t, dict)
    ]
    return out


def automated_test_case_row(item: dict, long_text: bool = False) -> dict:
    """An automated test case (Test Management ``AutomatedTestCases``): every
    field under its label, plus the priority as the same label manual test
    cases show."""
    from . import odata_service

    row = odata_service.format_row(item, long_text=long_text)
    if "priorityCode" in item:
        code = item.get("priorityCode")
        row["Priority"] = TESTCASE_PRIORITY_MAP.get(str(code), code)
    return row


def get_test_case(token: str, test_case_id: str, base_url: str | None = None) -> dict:
    """Return ONE manual test case with its full step tree.

    ``test_case_id`` is either the UUID or the display ID shown in the CALM UI
    (e.g. "8-1-1380"). The result carries the list fields (ID, Display ID,
    Title, Priority, Tags, …) plus ``Activities`` and ``Steps`` — each step
    with its Instructions and Expected Result — and an ``Execution Results``
    note explaining where run status / actual results can (and cannot) be read.
    """
    key = (test_case_id or "").strip()
    if not key:
        raise ValueError("test_case_id is required (UUID or display ID, e.g. '8-1-1380')")
    root = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases"
    if _UUID_RE.match(key):
        try:
            return _format_test_case_detail(_get(f"{root}/{key}?{_TEST_CASE_DETAIL_EXPAND}", token))
        except RuntimeError as exc:
            if _is_http_404(exc):
                raise NotFound(f"No test case with ID {key}") from exc
            raise
    esc = key.replace("'", "''")
    flt = quote(f"displayId eq '{esc}'", safe="")
    result = _get(f"{root}?{_TEST_CASE_DETAIL_EXPAND}&$filter={flt}", token)
    items = result.get("value", []) if isinstance(result, dict) else (result or [])
    if not items:
        raise NotFound(
            f"No test case with display ID '{key}'. Pass the test case UUID, or check "
            "the display ID with calm_resource(resource='test_cases', operation='list')."
        )
    return _format_test_case_detail(items[0])


_TM_SERVICE_ROOT = "api/calm-testmanagement/v1/"

# Entity-set names per tenant base URL: static per tenant, so the service
# document is read once per process, not on every test_plans call.
_TM_ENTITY_SETS: dict[str, list[str]] = {}
_TM_ENTITY_SETS_MAX = 64  # the key comes from the caller, so bound the memory

# Known plan fields -> the Title-Case names every other read uses; any field not
# listed is passed through under its CALM name (the plan schema isn't pinned).
_PLAN_FIELDS = {
    "uuid": "ID", "id": "ID", "displayId": "Display ID", "title": "Title", "name": "Name",
    "description": "Description", "projectId": "Project ID", "status": "Status",
    "statusCode": "Status", "startDate": "Start Date", "endDate": "End Date",
}


def _tm_entity_sets(base: str, token: str) -> list[str]:
    if base not in _TM_ENTITY_SETS:
        service = _get(f"{base}/{_TM_SERVICE_ROOT}", token)
        entries = service.get("value", []) if isinstance(service, dict) else []
        names = [e.get("url") or e.get("name") for e in entries if isinstance(e, dict)]
        names = [n for n in names if n]
        if not names:
            return names  # don't cache an empty/odd answer
        while len(_TM_ENTITY_SETS) >= _TM_ENTITY_SETS_MAX:
            _TM_ENTITY_SETS.pop(next(iter(_TM_ENTITY_SETS)))  # drop the oldest
        _TM_ENTITY_SETS[base] = names
    return _TM_ENTITY_SETS[base]


def _format_plan(item: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in item.items():
        if k.startswith("@") or isinstance(v, (dict, list)):
            continue
        out.setdefault(_PLAN_FIELDS.get(k, k), v)
    return out


def get_test_plans(
    token: str, base_url: str | None = None, project_id: str | None = None,
) -> list[dict] | dict:
    """List test plans from the Test Management service.

    SAP publishes the scope (calm-api.testplans.read) but no machine-readable
    entity name we could pin here, so the plan entity set is discovered from the
    service document (once per tenant). When the tenant's service exposes none, a
    structured ``unavailable`` result says so instead of failing. ``project_id``
    is applied client-side; if the plans carry no project field at all, the rows
    come back unfiltered with a "Warning" saying so.
    """
    base = _base_url(base_url)
    names = _tm_entity_sets(base, token)
    plan_sets = [n for n in names if "plan" in n.lower()]
    if not plan_sets:
        _TM_ENTITY_SETS.pop(base, None)  # re-check next call, e.g. once the scope is granted
        return {
            "status": "unavailable",
            "supported": False,
            "resource": "test_plans",
            "message": (
                "The connected Test Management service exposes no test-plan entity set. "
                "Test plans need scope calm-api.testplans.read on the service key; if it "
                "is granted, the tenant's API version does not offer plans yet."
            ),
            "available_entity_sets": names,
        }
    rows = [
        _format_plan(item)
        for item in _get_all(f"{base}/{_TM_SERVICE_ROOT}{plan_sets[0]}", token)
        if isinstance(item, dict)
    ]
    if project_id:
        if rows and not any("Project ID" in r for r in rows):
            return {
                "Warning": (
                    "These test plans carry no project field, so they could not be "
                    "filtered by project; all plans are listed."
                ),
                "Test Plans": rows,
            }
        rows = [r for r in rows if r.get("Project ID") == project_id]
    return rows


def get_timeboxes(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return timeboxes (sprints, iterations) for a project.

    Timeboxes are used to organize work into time-bounded periods. Common fields:
    name, type (numeric), startDate, endDate, closed (boolean).
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/timeboxes"
    items = _get_all(url, token)
    return [
        {
            "ID": item.get("id"),
            "Project ID": item.get("projectId") or project_id,
            "Name": item.get("name"),
            "Type": item.get("type"),
            "StartDate": item.get("startDate"),
            "EndDate": item.get("endDate"),
            "Closed": item.get("closed"),
        }
        for item in items
    ]


def get_teams(token: str, base_url: str | None = None) -> list[dict]:
    """Return all teams visible to the configured tenant.

    Teams group users for project collaboration. The exact fields depend on
    what the CALM API exposes; common fields: id, name, description, members.
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/teams"
    items = _get_all(url, token)
    return [
        {
            "ID": item.get("id"),
            "Name": item.get("name"),
            "Description": item.get("description"),
            "Project ID": item.get("projectId"),
        }
        for item in items
    ]


def get_project_teams(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return all teams for a specific project.

    Teams group users for project collaboration and assignment. This returns
    teams associated with a specific project, which may include both project-specific
    teams and global teams assigned to the project.

    Tries multiple endpoints in order:
    1. /projects/{id}/teams (project-specific)
    2. /teams with projectId filter (fallback)
    3. Falls back to all teams if project-specific endpoints fail
    """
    # Try project-specific endpoints first (deduped, in order).
    urls_to_try = list(dict.fromkeys([
        f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/teams",
        f"{_base_url(base_url)}/api/calm-projects/v1/teams?projectId={project_id}",
    ]))

    last_error = None
    for url in urls_to_try:
        try:
            items = _get_all(url, token)
            return [
                {
                    "ID": item.get("id"),
                    "Name": item.get("name"),
                    "Description": item.get("description"),
                    "Project ID": item.get("projectId") or project_id,
                    "Members": item.get("members", []),
                }
                for item in items
            ]
        except Exception as e:
            last_error = e
            continue

    # Project-specific endpoints errored (not merely empty) — fall back to
    # listing all teams and filtering client-side by project.
    log.warning(
        "Project-specific team endpoints failed for project %s. "
        "Falling back to all teams with client-side filtering. Last error: %s",
        project_id, last_error,
    )
    all_teams = get_teams(token, base_url)
    # Return the filtered list even when empty — a project with no teams is a
    # valid result, not an error worth blocking the caller (and retrying) over.
    return [t for t in all_teams if t.get("Project ID") == project_id]


# --- Tags -------------------------------------------------------------------

def get_tags(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return all tag definitions for a project.

    Tags are project-level metadata organized in groups. Each tag has a group
    name and tag name, formatted as "Group: Tag" (e.g. "Scope:Baseline",
    "Tshirt size:L"). Used to categorize tasks and requirements.
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/tags"
    items = _get_all(url, token)
    return [
        {
            "ID": item.get("id"),
            "Project ID": item.get("projectId") or project_id,
            "Group": item.get("group"),
            "Tag": item.get("tag"),
            "Full Name": f"{item.get('group')}: {item.get('tag')}" if item.get("group") and item.get("tag") else None,
        }
        for item in items
    ]


def create_tag(
    token: str,
    project_id: str,
    group: str,
    tag: str,
    base_url: str | None = None,
    user_email: str | None = None,
) -> dict:
    """Create a new tag definition in a project.

    Tags must be created before they can be assigned to tasks/requirements.
    The group and tag names are case-sensitive.

    Args:
        project_id: Target project ID
        group: Tag group name (e.g. "Scope", "Tshirt size")
        tag: Tag value (e.g. "Baseline", "L")
    """
    body = {
        "projectId": project_id,
        "group": group,
        "tag": tag,
    }
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/tags"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if isinstance(result, dict) and result else {"submitted": body}


# --- Users / Team Members ---------------------------------------------------

def get_project_users(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return all users/team members for a project with their assignable IDs.

    Use this to get the correct assignee IDs before creating/updating tasks.
    The returned 'ID' field is what should be passed as assignee_id to avoid
    'Former Member' issues.

    Tries multiple endpoints in order:
    1. /projects/{id}/users (most specific)
    2. /projects/{id}/team (alternative)
    3. /teams endpoint filtering by project (fallback)
    """
    # Try primary endpoint first
    urls_to_try = [
        f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/users",
        f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/team",
        f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/members",
    ]

    last_error = None
    for url in urls_to_try:
        try:
            items = _get_all(url, token)
            return [
                {
                    "ID": item.get("id") or item.get("userId") or item.get("memberId"),
                    "Email": item.get("email") or item.get("userEmail") or item.get("emailAddress"),
                    "Name": item.get("name") or item.get("displayName") or item.get("fullName"),
                    "Role": item.get("role") or item.get("projectRole"),
                    "Active": item.get("active", True),
                }
                for item in items
            ]
        except Exception as e:
            last_error = e
            continue

    # All endpoints failed
    raise RuntimeError(
        f"Could not fetch project users from any endpoint. "
        f"Last error: {last_error}. "
        f"Your OAuth2 client may need additional scopes (calm.users.read or similar)."
    )


# --- Features ---------------------------------------------------------------

def get_features(project_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return features for a project.

    Features are higher-level groupings used for transport tracking and
    release planning. Each feature can contain multiple requirements.

    Features have their own OData service — ``/api/calm-features/v1/Features``
    — which is what the ``features.read`` scope unlocks. Rows keep the columns
    agents already use (ID, Project ID, Name, Description, Status, External ID)
    read from SAP's real fields (uuid, title, statusCode, …), then every other
    field (Display ID, Priority Code, Responsible ID, Tags, Last Changed, …).
    """
    from . import odata_service

    service, set_name = odata_service.FEATURES
    try:
        es = odata_service.entity_set(service, set_name, token, base_url)
    except Exception as exc:  # noqa: BLE001 — no schema: use the documented fields
        log.debug("features schema unavailable: %s", type(exc).__name__)
        es = None
    if es is not None:
        filters = {"projectId": project_id} if project_id and "projectId" in es["props"] else None
        items = odata_service.list_raw(service, set_name, token, base_url, filters)
    else:
        items = _get_all(f"{_base_url(base_url)}/api/calm-features/v1/Features", token)
    mapped = [odata_service.feature_row(item) for item in items if isinstance(item, dict)]
    # Filter to the requested project. Guard against a field-name mismatch: if
    # no item carries a project id at all, return everything rather than hide
    # all results behind a wrong assumption about the field name.
    if project_id and any(f["Project ID"] for f in mapped):
        return [f for f in mapped if f["Project ID"] == project_id]
    return mapped


def create_feature(
    token: str,
    project_id: str,
    name: str,
    description: str | None = None,
    external_id: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None,
    user_email: str | None = None,
) -> dict:
    """Create a new feature in a project.

    Features group requirements for transport and release management. Used
    for baseline requirements in BP workflows.

    Args:
        project_id: Target project ID
        name: Feature name
        description: Optional description
        external_id: Optional external system reference
        extra_fields: Additional API fields (status, etc.)
    """
    from . import odata_service

    service, set_name = odata_service.FEATURES
    try:
        es = odata_service.entity_set(service, set_name, token, base_url)
    except Exception as exc:  # noqa: BLE001 — no schema: use the documented fields
        log.debug("features schema unavailable: %s", type(exc).__name__)
        es = None
    # SAP's Features API calls the name "title"; follow the tenant's schema when
    # it can be read, else the documented field.
    name_field = "name" if es is not None and "title" not in es["props"] and "name" in es["props"] else "title"
    body: dict[str, Any] = {"projectId": project_id, name_field: name}
    if description is not None:
        body["description"] = description
    if external_id is not None:
        body["externalId"] = external_id
    if extra_fields:
        body.update(_api_field_names(extra_fields))
    if es is not None:
        body = odata_service.body_for(es, body)

    # Features have their own service; the Projects-service path is not the
    # real Features API (see get_features).
    if es is not None:
        result, note = odata_service.create(service, set_name, token, body, base_url,
                                            user_email=user_email)
    else:
        url = f"{_base_url(base_url)}/api/calm-features/v1/Features"
        result, note = _write("POST", url, token, body, user_email=user_email), None
    if not (isinstance(result, dict) and result):
        return {"submitted": body}
    return _with_note(result, note) if note else result


def link_test_case_to_requirement(
    token: str,
    test_case_id: str,
    requirement_id: str,
    link_type: str = "covers",
    base_url: str | None = None,
    user_email: str | None = None,
) -> dict:
    """Link a test case to a requirement for traceability.

    Creates a reference from the test case to the requirement, establishing
    test coverage tracking. This is the standard way to track which test cases
    verify which requirements in CALM.

    Args:
        test_case_id: UUID of the test case (from get_calm_test_cases or create_calm_test_case)
        requirement_id: Task ID of the requirement (from get_calm_requirements or create_calm_requirement)
        link_type: Type of link (default "covers" for test coverage)

    Common link types:
        - "covers": Test case covers/verifies this requirement
        - "validates": Test case validates this requirement
        - "references": General reference link

    Returns the created reference object or submission confirmation.
    """
    # CALM links a test case to a requirement (or any task) as a task
    # assignment — what its UI shows as the test case's linked tasks. SAP
    # requires the parent test case in the body too (verified live).
    body: dict[str, Any] = {"taskId": requirement_id, "parentTestCase_ID": test_case_id}
    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases/{test_case_id}/toTaskAssignments"
    result = _write("POST", url, token, body, user_email=user_email)
    if isinstance(result, dict) and result:
        return {"Test Case ID": test_case_id, "Task ID": result.get("taskId") or requirement_id,
                "Task Display ID": result.get("taskDisplayId"), "Type": result.get("type"), "Linked": True}
    return {"Test Case ID": test_case_id, "Task ID": requirement_id, "Linked": True}


# --- Analytics --------------------------------------------------------------

# CALM Analytics DataSet rows are a pivoted key/value grid: dimensions arrive as
# d1k/d1v..d30k/d30v and metrics as m1k/m1v..m15k/m15v. Raw, that is unreadable.
# Collapse each row back into a flat {dimension: value, ...} dict plus a nested
# "Metrics" dict so an agent can group/count directly (e.g. by "statusText").
def _unpivot_analytics_row(row: dict) -> dict:
    dims: dict[str, Any] = {}
    for i in range(1, 31):
        k = row.get(f"d{i}k")
        if k:
            dims[k] = row.get(f"d{i}v")
    metrics: dict[str, Any] = {}
    for i in range(1, 16):
        k = row.get(f"m{i}k")
        if k:
            metrics[k] = row.get(f"m{i}v")
    out: dict[str, Any] = {"Provider": row.get("provider"), "Snapshot": row.get("date")}
    out.update(dims)
    out["Metrics"] = metrics
    return out


# Providers reachable with the standard implementation scopes. DP_REQUIREMENTS
# and DP_TESTS are listed in SAP docs but 403 on tenants that do not grant the
# matching scope (DP_TESTS: calm-api.tests.read), so they are not advertised as
# always-available here.
ANALYTICS_PROVIDERS = ("DP_TASKS", "DP_PROJECTS", "DP_FEATURES")


# The DataSet OData surface caps each page at 1000 rows and returns no
# @odata.nextLink/@odata.count, so completeness requires $skip paging. Guard a
# runaway with a hard ceiling (50 pages = 50k rows) — far beyond any real project.
_ANALYTICS_PAGE = 1000
_ANALYTICS_MAX_ROWS = 50_000


def get_analytics(
    token: str,
    provider: str = "DP_TASKS",
    base_url: str | None = None,
    top: int | None = None,
    project_id: str | None = None,
    raw_filter: str | None = None,
    where: dict | None = None,
) -> list[dict]:
    """Return CALM Analytics rows for a provider, unpivoted to flat dicts.

    ``provider`` is one of DP_TASKS / DP_PROJECTS / DP_FEATURES (others require
    extra scopes and 403). Each returned row carries the provider's dimensions
    flattened to top level (e.g. ``statusText``, ``team``, ``phase``,
    ``workstream``, ``priority``, ``dueDate``, ``overdue``) plus a ``Metrics``
    dict (e.g. ``counter``, ``storyPoints``, ``effort``). This is the efficient
    way to compute status breakdowns / readiness % without paging every task.

    All pages are fetched (the server caps each page at 1000 rows), so counts
    are complete; pass ``top`` to cap the number of rows returned. ``project_id``
    filters client-side on the ``project`` dimension (the DataSet OData surface
    does not filter on pivoted dimension columns server-side). ``raw_filter``
    appends a raw OData clause to the mandatory provider filter. ``where`` keeps
    rows whose dimensions equal the given values ({"timebox": "Sprint 1"}, case
    ignored; a list matches any) — applied after reading, because the DataSet
    can't filter on its pivoted dimension columns server-side.
    """
    flt = f"provider eq '{provider}'"
    if raw_filter:
        flt += f" and {raw_filter}"
    encoded = quote(flt, safe="")
    base = _base_url(base_url)

    raw: list[dict] = []
    skip = 0
    url = f"{base}/api/calm-analytics/v1/odata/v4/analytics/DataSet"
    while skip < _ANALYTICS_MAX_ROWS:
        query = f"$filter={encoded}&$top={_ANALYTICS_PAGE}&$skip={skip}"
        result = _get(f"{url}?{query}", token)
        items = result.get("value", []) if isinstance(result, dict) else (result or [])
        raw.extend(items)
        if len(items) < _ANALYTICS_PAGE:
            break  # last (partial) page
        # Short-circuit on `top` ONLY when every raw row is a returned row. With a
        # project_id filter the kept count isn't known until after unpivot+filter,
        # so stopping at `top` RAW rows could miss project rows further down the
        # DataSet and under-count — page fully (to the ceiling) in that case.
        if top is not None and project_id is None and len(raw) >= top:
            break
        skip += _ANALYTICS_PAGE
    else:
        # Loop exited on the row ceiling while a full page was still arriving —
        # more analytics rows exist than we fetched. Surface it like every other
        # list, so the user is never silently given a partial breakdown.
        _record_truncation(url, len(raw), "max-rows")

    rows = [_unpivot_analytics_row(r) for r in raw]
    if project_id:
        rows = [r for r in rows if r.get("project") == project_id]
    for dim, want in (where or {}).items():
        wanted = {str(v).strip().lower() for v in (want if isinstance(want, list) else [want])}
        rows = [r for r in rows if str(r.get(dim, "")).strip().lower() in wanted]
    if top is not None:
        rows = rows[:top]
    return rows


# --- Team roles / staffing --------------------------------------------------

def get_team_roles(team_id: str, token: str, base_url: str | None = None) -> list[dict]:
    """Return the roles (and their staffed members) of a project team.

    ``team_id`` comes from resource='teams'. Each role lists its members, so this
    answers "who is staffed as the <role> on this team".
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/teams/{team_id}/roles"
    items = _get_all(url, token)
    return [
        {
            "Role ID": item.get("roleId"),
            "Role Name": item.get("roleName"),
            "Description": item.get("roleDescription"),
            "Custom": item.get("isCustom"),
            "Member Count": len(item.get("members") or []),
            "Members": item.get("members") or [],
        }
        for item in items
    ]


# --- Feature reference data -------------------------------------------------

def get_feature_status(token: str, base_url: str | None = None) -> list[dict]:
    """Return the Feature status value help (code -> name), e.g. CREATED -> 'In Specification'."""
    url = f"{_base_url(base_url)}/api/calm-features/v1/FeatureStatus"
    items = _get_all(url, token)
    return [{"Code": item.get("code"), "Name": item.get("name")} for item in items]


def get_feature_priorities(token: str, base_url: str | None = None) -> list[dict]:
    """Return the Feature priority value help (code -> name), e.g. 10 -> 'Very High'."""
    url = f"{_base_url(base_url)}/api/calm-features/v1/FeaturePriorities"
    items = _get_all(url, token)
    return [{"Code": item.get("code"), "Name": item.get("name")} for item in items]


# --- Project Customization Values -------------------------------------------

def get_project_customization(project_id: str, token: str, base_url: str | None = None) -> dict:
    """Return all customization values for a project.

    Returns picklist values for workstreams, deliverables, and other
    project-specific custom fields. Used to validate task field values
    against the project's allowed options.

    Returns dict with keys: workstreams, deliverables, customFields
    """
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/customization"
    result = _get(url, token)

    return {
        "Project ID": project_id,
        "Workstreams": result.get("workstreams", []),
        "Deliverables": result.get("deliverables", []),
        "Custom Fields": result.get("customFields", []),
    }


# ---------------------------------------------------------------------------
# CALM write functions
#
# Payloads use the same camelCase field names the read functions parse back,
# so create/read stay consistent. Field contracts should be confirmed against
# the target tenant; raw CALM codes are accepted for `type`/`status` so callers
# can bypass label mapping if a tenant differs.
# ---------------------------------------------------------------------------

def _format_task(
    item: dict,
    team_names: dict | None = None,
    timebox_names: dict | None = None,
) -> dict:
    """Format a single raw task the same way get_tasks() formats a list item.

    ``team_names`` / ``timebox_names`` map IDs to names; get_tasks() passes them
    so each row carries the team and sprint by name. Without them the names are
    None and only the IDs are set.
    """
    return {
        "ID": item.get("id"),
        "Display ID": item.get("displayId") or item.get("externalId"),
        # FRICEF/RICEFW/FS codes live in externalId on CALM tasks (e.g. "FTS-DEV-01").
        "External ID (FRICEF)": item.get("externalId"),
        "Title": item.get("title"),
        "Type": TASK_TYPE_MAP.get(item.get("type"), item.get("type")),
        "Status": TASK_STATUS_MAP.get(item.get("status"), item.get("status")),
        # parentId links a task/user story to its parent work item (e.g. a requirement).
        "Parent ID": item.get("parentId"),
        "StartDate": item.get("startDate"),
        "DueDate": item.get("dueDate"),
        "AssigneeName": item.get("assigneeName"),
        "AssigneeID": item.get("assigneeId"),  # UUID needed for auto-resolution
        "ApprovalState": TASK_APPROVAL_STATE_MAP.get(item.get("approvalState"), item.get("approvalState")),
        "Obsolete": item.get("obsolete"),
        "Effort": item.get("effort"),
        # Tasks carry tags as a plain inline list of label strings (NOT the
        # toTagAssignments navigation test cases use); surface them so callers
        # can see and filter on them.
        "Tags": item.get("tags") or [],
        # Sprint planning: the owning team and the timebox (sprint) the task is
        # planned in — what per-team / per-sprint counts and effort group by.
        "Responsible Team ID": item.get("responsibleTeamId"),
        "Responsible Team": (team_names or {}).get(item.get("responsibleTeamId")),
        "Timebox ID": item.get("timeboxId"),
        "Timebox": (timebox_names or {}).get(item.get("timeboxId")),
        # Filled on (almost) every task but previously dropped, so agents could
        # not report by priority, scope, workstream or recent change.
        "Priority": TASK_PRIORITY_MAP.get(str(item.get("priorityId")), item.get("priorityId")),
        "Scope ID": item.get("scopeId"),
        "Scope": item.get("scopeName"),
        # A customization code (e.g. "WS006"); its names aren't in the public API.
        "Workstream": item.get("workstream"),
        "Assigned Role": item.get("assignedRoleName"),
        "Created": item.get("createdTimestamp"),
        "Last Changed": item.get("lastChangedTimestamp"),
    }


TASK_FIELDS = tuple(_format_task({}))


def select_task_fields(rows: list[dict], fields: Any) -> list[dict]:
    """Keep only the named fields (plus "ID") on each row, to shrink large lists."""
    wanted = _as_list(fields)
    bad = [f for f in wanted if f not in TASK_FIELDS]
    if not wanted or bad:
        raise ValueError(f"fields must be one or more of {', '.join(TASK_FIELDS)} (got {bad or wanted})")
    keep = ["ID"] + [f for f in wanted if f != "ID"]
    return [{k: r.get(k) for k in keep} for r in rows]


def _id_name_map(fetch, what: str) -> dict:
    """{ID: Name} from a formatted list, or {} if the lookup fails — a missing
    name must never fail the task read itself. One short attempt only, so a
    slow lookup can't hold up the task list it decorates."""
    try:
        with http_retry.best_effort():
            rows = fetch()
        return {r["ID"]: r.get("Name") for r in rows if isinstance(r, dict) and r.get("ID")}
    except Exception as exc:  # noqa: BLE001 — best-effort enrichment
        log.debug("task %s name lookup skipped: %s", what, type(exc).__name__)
        return {}


# --- Recovering a task write SAP did not confirm ----------------------------
# A dropped connection leaves a write unconfirmed ("may or may not have been
# applied"). For tasks the outcome can be checked, so instead of handing that
# doubt to the agent: read the result back, and send the write once more only
# when it is certainly not there. An update sets fixed values, so sending it
# again is harmless; a create is re-sent only after a complete read of the
# project shows no such task AND SAP dropped it quickly.
#
# A SLOW drop is different: SAP held the request for many seconds, then its
# gateway gave up while the backend was still working (seen in production: a
# create dropped after 18s, an update after 31s). Such a write may still land
# after we look, so a create is never re-sent then and "not there" is reported
# as "not there yet", not "not created".
WRITE_SETTLE = 2.0           # let SAP finish a fast-dropped write before checking
SLOW_WRITE_SETTLE = 5.0      # more time when SAP was slow to begin with
SLOW_WRITE = 5.0             # a drop after this many seconds may still be in progress
_CREATE_LOOKBACK = 300.0     # seconds of clock skew allowed on createdTimestamp
_TIMESTAMP = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)
# Fields SAP may store in another form than sent (rich text, email -> user ID):
# a difference there can't prove the write is missing.
_UNCOMPARABLE = frozenset({"description", "assigneeId"})


def _ts_epoch(value: Any) -> float | None:
    """CALM timestamp ("2026-04-22T12:18:26.311368800Z") -> epoch seconds."""
    match = _TIMESTAMP.match(str(value or "").strip())
    if not match:
        return None
    *parts, zone = match.groups()
    tz = timezone.utc
    if zone and zone != "Z":
        sign = -1 if zone[0] == "-" else 1
        hours, minutes = int(zone[1:3]), int(zone[-2:])
        tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
    try:
        return datetime(*map(int, parts), tzinfo=tz).timestamp()
    except ValueError:
        return None


def _same(sent: Any, stored: Any, key: str) -> bool:
    if key in ("startDate", "dueDate") and isinstance(sent, str) and isinstance(stored, str):
        return sent[:10] == stored[:10]
    if isinstance(sent, bool) or isinstance(stored, bool):
        return sent is stored
    if isinstance(sent, (int, float)) or isinstance(stored, (int, float)):
        try:
            return float(sent) == float(stored)
        except (TypeError, ValueError):
            return False
    if isinstance(sent, str) and isinstance(stored, str):
        return sent.strip() == stored.strip()
    return sent == stored


def _task_has(stored: dict, body: dict) -> bool | None:
    """True: every sent field is on the task. False: a field certainly differs.
    None: only fields SAP may reshape differ, so it can't be told."""
    unsure = False
    for key, value in body.items():
        if _same(value, stored.get(key), key):
            continue
        if key in _UNCOMPARABLE or key not in stored:
            unsure = True
        else:
            return False
    return None if unsure else True


def _with_note(result: Any, note: str) -> Any:
    if isinstance(result, dict):
        result = dict(result)
        result["Note"] = note
    return result


def _read_task_back(url: str, token: str) -> dict | None:
    try:
        data, _ = _get_with_meta(url, token)
    except Exception as exc:  # noqa: BLE001 — "could not check" is a valid outcome
        log.warning("reading task back after an unconfirmed write failed: %s", type(exc).__name__)
        return None
    return data if isinstance(data, dict) else None


def _recover_task_update(
    url: str, token: str, body: dict, task_id: str, user_email: str | None,
    first: http_retry.WriteUnconfirmed, started: float,
) -> dict:
    applied_note = ("SAP dropped the connection, but reading the task back shows the "
                    "update was applied.")
    took = http_retry._clock() - started

    def check(slow: bool) -> tuple[dict | None, bool | None]:
        http_retry._sleep(SLOW_WRITE_SETTLE if slow else WRITE_SETTLE)
        stored = _read_task_back(url, token)
        return stored, (_task_has(stored, body) if stored is not None else None)

    def failed(cause: http_retry.WriteUnconfirmed, state: bool | None, resent: bool,
               seconds: float) -> RuntimeError:
        tries = "both attempts" if resent else "the request"
        if state is False and seconds > SLOW_WRITE:
            outcome = (f"the change is not on the task yet — SAP took {seconds:.0f}s before "
                       "dropping it, so it may still be finishing; read the task again in a "
                       "minute")
        elif state is False:
            outcome = "reading the task back shows the change was NOT applied"
        else:
            outcome = "the task could not be read back to confirm the change"
        return RuntimeError(
            f"SAP Cloud ALM dropped the connection on {tries} to update task {task_id} "
            f"({cause.reason or 'no response'}), and {outcome}. Retrying is safe: an update "
            "only sets the same values again and cannot create duplicates. Reads work, so "
            "SAP is failing or timing out on write requests on this tenant right now, not "
            "rejecting this request; if it keeps happening, ask the tenant's SAP Cloud ALM "
            "administrator to check the service."
        )

    stored, state = check(took > SLOW_WRITE)
    if state is True:
        return _with_note(_format_task(stored), applied_note)
    # Not on the task yet. An update only sets values, so sending it again is
    # safe even if the first attempt is still finishing (slow tenants drop
    # writes after 18-31s): both set the same values.
    log.warning("task update %s unconfirmed (%s); sending the same update again",
                task_id, first.reason)
    again_started = http_retry._clock()
    try:
        result = _write("PATCH", url, token, body, user_email=user_email)
    except http_retry.WriteUnconfirmed as again:
        again_took = http_retry._clock() - again_started
        stored, state = check(again_took > SLOW_WRITE)
        if state is True:
            return _with_note(_format_task(stored), applied_note)
        raise failed(again, state, resent=True, seconds=again_took) from again
    except Exception:
        # SAP answered the second attempt with an error; if the first one had
        # landed after all, the update is done.
        stored, state = check(False)
        if state is True:
            return _with_note(_format_task(stored), applied_note)
        raise
    out = _format_task(result) if isinstance(result, dict) and result else {"updated": task_id, "fields": body}
    return _with_note(out, "SAP dropped the first attempt; the same update was sent again and succeeded.")


def _new_tasks_like(base: str, token: str, body: dict, since: float) -> tuple[list[dict], bool] | None:
    """Tasks in the project with the sent title/type/parent created since ``since``.

    Returns (matches, conclusive) — conclusive means the listing was complete and
    every same-titled task had a readable timestamp, so an empty match proves the
    task does not exist — or None when the project could not be read.
    """
    url = f"{base}/api/calm-tasks/v1/tasks?projectId={body['projectId']}&type={body['type']}"
    sink, sink_token = install_truncation_sink()  # a partial read is ours to judge, not an alert
    try:
        items = _get_all(url, token)
    except Exception as exc:  # noqa: BLE001
        log.warning("reading tasks back after an unconfirmed create failed: %s", type(exc).__name__)
        return None
    finally:
        reset_truncation_sink(sink_token)
    title = " ".join(str(body.get("title") or "").split())
    matches, conclusive = [], not sink
    for it in items:
        if not isinstance(it, dict) or " ".join(str(it.get("title") or "").split()) != title:
            continue
        if it.get("type") not in (None, body["type"]):
            continue
        if body.get("parentId") and it.get("parentId") != body["parentId"]:
            continue
        created = _ts_epoch(it.get("createdTimestamp"))
        if created is None:
            conclusive = False
        elif created >= since - _CREATE_LOOKBACK:
            matches.append(it)
    return matches, conclusive


def _recover_task_create(
    base: str, url: str, token: str, body: dict, user_email: str | None,
    first: http_retry.WriteUnconfirmed, started: float, since: float,
) -> dict:
    title = body.get("title")
    created_note = ("SAP dropped the connection, but the task was created — confirmed by "
                    "reading the project back.")
    took = http_retry._clock() - started

    def check(slow: bool) -> tuple[list[dict], bool] | None:
        http_retry._sleep(SLOW_WRITE_SETTLE if slow else WRITE_SETTLE)
        return _new_tasks_like(base, token, body, since)

    def created(matches: list[dict]) -> dict:
        if len(matches) > 1:
            raise RuntimeError(
                f"SAP Cloud ALM did not confirm the create of task '{title}', and the project "
                f"now has {len(matches)} tasks with that title created in the last few minutes "
                f"(IDs: {', '.join(str(m.get('id')) for m in matches)}). Check them before "
                "creating it again, and delete any duplicate."
            )
        return _with_note(_format_task(matches[0]), created_note)

    def still_finishing(cause: http_retry.WriteUnconfirmed, seconds: float) -> RuntimeError:
        return RuntimeError(
            f"SAP Cloud ALM took {seconds:.0f}s and then dropped the connection on the create "
            f"of task '{title}' ({cause.reason or 'no response'}). The task is not in the "
            "project yet, but SAP may still be finishing it. Do NOT create it again yet: in a "
            "minute, search the project for this title; create it only if it is still "
            "missing. SAP is slow on write requests on this tenant right now."
        )

    found = check(took > SLOW_WRITE)
    if found is None:
        raise first  # could not check: the original "may or may not" message stands
    matches, conclusive = found
    if matches:
        return created(matches)
    if not conclusive:
        raise first
    if took > SLOW_WRITE:
        raise still_finishing(first, took) from first
    log.warning("task create unconfirmed (%s) and not found; sending it again", first.reason)
    again_started = http_retry._clock()
    try:
        result = _write("POST", url, token, body, user_email=user_email)
    except http_retry.WriteUnconfirmed as again:
        again_took = http_retry._clock() - again_started
        found = check(again_took > SLOW_WRITE)
        if found is not None and found[0]:
            return created(found[0])
        if found is not None and found[1] and again_took > SLOW_WRITE:
            raise still_finishing(again, again_took) from again
        if found is not None and found[1]:
            raise RuntimeError(
                f"SAP Cloud ALM dropped the connection on both attempts to create task "
                f"'{title}' ({again.reason or 'no response'}), and reading the project back "
                "shows it was NOT created. Reads work, so SAP is failing write requests on "
                "this tenant right now, not rejecting this request. It is safe to create it "
                "again in a few minutes; if it keeps happening, ask the tenant's SAP Cloud ALM "
                "administrator to check the service."
            ) from again
        raise
    out = _format_task(result) if isinstance(result, dict) and result else {"submitted": body}
    return _with_note(out, "SAP dropped the first attempt (nothing was created); the task "
                           "was sent again and created once.")


def create_task(
    token: str,
    project_id: str,
    title: str,
    task_type: str,
    status: str | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    assignee_id: str | None = None,
    description: str | None = None,
    priority_id: int | None = None,
    external_id: str | None = None,
    parent_id: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create a task in a Cloud ALM project. Returns the created task, formatted.

    `assignee_id` is the assignee's email address. `priority_id` is 10/20/30/40
    or its label (Very High/High/Medium/Low); dates are YYYY-MM-DD (a datetime or
    month-name date is converted). `parent_id` links a sub-task to
    its parent. `extra_fields` merges any other documented task field
    (e.g. subStatus, scopeId, storyPoints, effort, workstream, involvedParties,
    classificationId, customField1..20) — used for the long tail not exposed as
    named args. snake_case keys are sent as camelCase (scope_id -> scopeId).
    """
    type_code = resolve_task_type_code(task_type)
    body: dict[str, Any] = {
        "projectId": project_id,
        "title": title,
        "type": type_code,
    }
    if status is not None:
        body["status"] = resolve_status_code(status, type_code)
    if start_date is not None:
        body["startDate"] = api_date(start_date, "start_date")
    if due_date is not None:
        body["dueDate"] = api_date(due_date, "due_date")
    if assignee_id is not None:
        body["assigneeId"] = assignee_id
    if description is not None:
        body["description"] = description
    if priority_id is not None:
        body["priorityId"] = resolve_priority(priority_id)
    if external_id is not None:
        body["externalId"] = external_id
    if parent_id is not None:
        body["parentId"] = parent_id
    if extra_fields:
        body.update(_api_field_names(extra_fields))
    if body.get("approvalState") is not None:
        body["approvalState"] = resolve_approval_state(body["approvalState"])

    base = _base_url(base_url)
    url = f"{base}/api/calm-tasks/v1/tasks"
    started, since = http_retry._clock(), time.time()
    try:
        result = _write("POST", url, token, body, user_email=user_email)
    except http_retry.WriteUnconfirmed as exc:
        return _recover_task_create(base, url, token, body, user_email, exc, started, since)
    return _format_task(result) if isinstance(result, dict) and result else {"submitted": body}


def update_task(
    token: str,
    task_id: str,
    title: str | None = None,
    task_type: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    due_date: str | None = None,
    assignee_id: str | None = None,
    description: str | None = None,
    priority_id: int | None = None,
    external_id: str | None = None,
    obsolete: bool | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Update fields of an existing task (partial PATCH). Only provided fields are sent.

    `status` needs the task type to resolve a human label to a code; pass
    `task_type` alongside a human status, or pass a raw CALM status code.
    Tasks are a plain REST API — no If-Match/ETag needed. `extra_fields` merges
    any other documented task field; snake_case keys are sent as camelCase.
    """
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if task_type is not None:
        body["type"] = resolve_task_type_code(task_type)
    if status is not None:
        # If a human label is given we need the type to pick the right code.
        type_code = body.get("type") or (resolve_task_type_code(task_type) if task_type else None)
        if status not in _KNOWN_STATUS_CODES and not type_code:
            # Auto-fetch the task's type so a human status label works standalone.
            try:
                data, _ = _get_with_meta(
                    f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}", token
                )
                if isinstance(data, dict) and data.get("type"):
                    type_code = data["type"]
            except Exception:
                pass
        if status in _KNOWN_STATUS_CODES or type_code:
            body["status"] = resolve_status_code(status, type_code or "")
        else:
            raise ValueError(
                "Updating status by human label requires `task_type` (could not "
                "auto-detect the task's type); or pass a raw CALM status code."
            )
    if start_date is not None:
        body["startDate"] = api_date(start_date, "start_date")
    if due_date is not None:
        body["dueDate"] = api_date(due_date, "due_date")
    if assignee_id is not None:
        body["assigneeId"] = assignee_id
    if description is not None:
        body["description"] = description
    if priority_id is not None:
        body["priorityId"] = resolve_priority(priority_id)
    if external_id is not None:
        body["externalId"] = external_id
    if obsolete is not None:
        body["obsolete"] = obsolete
    if extra_fields:
        body.update(_api_field_names(extra_fields))
    if body.get("approvalState") is not None:
        body["approvalState"] = resolve_approval_state(body["approvalState"])

    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}"
    started = http_retry._clock()
    try:
        result = _write("PATCH", url, token, body, user_email=user_email)
    except http_retry.WriteUnconfirmed as exc:
        return _recover_task_update(url, token, body, task_id, user_email, exc, started)
    return _format_task(result) if isinstance(result, dict) and result else {"updated": task_id, "fields": body}


# --- Projects ---------------------------------------------------------------

def _format_project(item: dict) -> dict:
    return {
        "ID": item.get("id"),
        "Name": item.get("name"),
        "Status": PROJECT_STATUS_MAP.get(item.get("status"), item.get("status")),
        "Purpose": item.get("purpose"),
        "OperationalStatus": item.get("operationalStatus"),
    }


def create_project(
    token: str,
    name: str,
    program_id: str | None = None,
    deployment_plan_id: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create a Cloud ALM project. Returns the created project, formatted.

    Plain REST POST — no If-Match. The spec confirms only `name` (and optionally
    `programId`) on the create body; `status`/`purpose`/`operationalStatus`/`phaseId`
    are managed elsewhere (not settable here). Anything extra can still be attempted
    via `extra_fields`.
    """
    body: dict[str, Any] = {"name": name}
    if program_id is not None:
        body["programId"] = program_id
    if deployment_plan_id is not None:
        body["deploymentPlanId"] = deployment_plan_id
    if extra_fields:
        body.update(_api_field_names(extra_fields))

    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects"
    result = _write("POST", url, token, body, user_email=user_email)
    return _format_project(result) if isinstance(result, dict) and result else {"submitted": body}


def update_project(
    token: str,
    project_id: str,
    name: str | None = None,
    program_id: str | None = None,
    deployment_plan_id: str | None = None,
    if_match: str | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Partial-update a project. Only provided fields are sent.

    The spec confirms the PATCH body is exactly {name, deploymentPlanId, programId};
    status/operationalStatus/purpose/phaseId are NOT patchable via this API.
    PATCH requires If-Match — the project's `etag` field (a numeric timestamp). If
    `if_match` is not supplied it is fetched from the entity first.
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if program_id is not None:
        body["programId"] = program_id
    if deployment_plan_id is not None:
        body["deploymentPlanId"] = deployment_plan_id
    if extra_fields:
        body.update(_api_field_names(extra_fields))
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}"
    etag = _resolve_etag(url, token, if_match, body_field="etag")
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
    return _format_project(result) if isinstance(result, dict) and result else {"updated": project_id, "fields": body}


# --- Business processes -----------------------------------------------------

def _format_business_process(item: dict) -> dict:
    return {
        "ID": item.get("id"),
        "Name": item.get("name"),
        "Description": item.get("description"),
    }


def create_business_process(
    token: str,
    name: str,
    description: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create a business process. Returns the created process, formatted."""
    body: dict[str, Any] = {"name": name}
    if description is not None:
        body["description"] = description

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses"
    result = _write("POST", url, token, body, user_email=user_email)
    return _format_business_process(result) if isinstance(result, dict) and result else {"submitted": body}


def update_business_process(
    token: str,
    business_process_id: str,
    name: str | None = None,
    description: str | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Partial-update a business process. Only provided fields are sent.

    OData service — PATCH requires If-Match. If `if_match` is not supplied, the
    current ETag is fetched from the entity first.
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses/{business_process_id}"
    etag = _resolve_etag(url, token, if_match)
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
    return _format_business_process(result) if isinstance(result, dict) and result else {"updated": business_process_id, "fields": body}


# --- Solution processes -----------------------------------------------------

def _format_solution_process(item: dict) -> dict:
    return {
        "ID": item.get("id"),
        "Name": item.get("name"),
        "Description": item.get("description"),
        "Status": item.get("status"),
        "Countries": item.get("countries"),
        "State": item.get("state"),
    }


def _countries_to_str(countries: Any) -> str:
    """CALM expects countries as a comma-separated string ("DE,FR"), not an array."""
    if isinstance(countries, (list, tuple)):
        return ",".join(str(c).strip() for c in countries)
    return str(countries)


def create_solution_process(
    token: str,
    name: str,
    description: str | None = None,
    status: str | None = None,
    countries: Any = None,
    state: str | None = None,
    business_process_id: str | None = None,
    external_id: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create a solution process. Returns the created process, formatted.

    `countries` may be a list (["DE","FR"]) or a comma-string ("DE,FR"); it is
    sent as a comma-separated string. `business_process_id` links the parent
    business process (sent as the nested {"businessProcess": {"id": ...}}).
    """
    body: dict[str, Any] = {"name": name}
    if description is not None:
        body["description"] = description
    if status is not None:
        body["status"] = status
    if countries is not None:
        body["countries"] = _countries_to_str(countries)
    if state is not None:
        body["state"] = state
    if external_id is not None:
        body["externalId"] = external_id
    if not business_process_id:
        # SAP refuses it otherwise ("'$businessProcess' must not be null").
        raise ValueError("business_process_id is required: the business process this solution "
                         "process belongs to (its ID, or its name as data.business_process)")
    body["businessProcess"] = {"id": business_process_id}

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses"
    result = _write("POST", url, token, body, user_email=user_email)
    return _format_solution_process(result) if isinstance(result, dict) and result else {"submitted": body}


def update_solution_process(
    token: str,
    solution_process_id: str,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    countries: Any = None,
    state: str | None = None,
    external_id: str | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Partial-update a solution process. Only provided fields are sent.

    OData service — PATCH requires If-Match (auto-fetched if not supplied).
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if status is not None:
        body["status"] = status
    if countries is not None:
        body["countries"] = _countries_to_str(countries)
    if state is not None:
        body["state"] = state
    if external_id is not None:
        body["externalId"] = external_id
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses/{solution_process_id}"
    etag = _resolve_etag(url, token, if_match)
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
    return _format_solution_process(result) if isinstance(result, dict) and result else {"updated": solution_process_id, "fields": body}


# --- Scopes -----------------------------------------------------------------

def _format_scope(item: dict) -> dict:
    return {
        "ID": item.get("id"),
        "Project ID": item.get("projectId"),
        "Name": item.get("name"),
        "Description": item.get("description"),
    }


def create_scope(
    token: str,
    project_id: str,
    name: str,
    description: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create a process-management scope in a project. Returns it, formatted."""
    body: dict[str, Any] = {"projectId": project_id, "name": name}
    if description is not None:
        body["description"] = description

    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes"
    result = _write("POST", url, token, body, user_email=user_email)
    return _format_scope(result) if isinstance(result, dict) and result else {"submitted": body}


def update_scope(
    token: str,
    scope_id: str,
    name: str | None = None,
    description: str | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Partial-update a scope. Only provided fields are sent.

    OData service, but the spec confirms scopes need NO If-Match, so none is
    fetched; a caller-supplied `if_match` is still honoured if given.
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes/{scope_id}"
    # The processmanagement scopes PATCH rejects application/json with 415; it
    # follows JSON Merge Patch (RFC 7386) and requires this media type.
    result = _write(
        "PATCH", url, token, body, if_match=if_match, content_type="application/merge-patch+json"
    , user_email=user_email)
    return _format_scope(result) if isinstance(result, dict) and result else {"updated": scope_id, "fields": body}


# --- Manual test cases ------------------------------------------------------

def _format_test_case(item: dict) -> dict:
    priority_code = str(item.get("priorityCode"))
    # Tags (CALM "tags") come from the toTagAssignments navigation collection,
    # present only when the caller expanded it. Each entry carries a `label`.
    tags = [
        t.get("label")
        for t in (item.get("toTagAssignments") or [])
        if isinstance(t, dict) and t.get("label")
    ]
    return {
        # Test Management is OData; the key is `uuid` (fall back to `id`).
        "ID": item.get("uuid") or item.get("id"),
        "Display ID": item.get("displayId"),
        "Project ID": item.get("projectId"),
        "Scope ID": item.get("scopeId"),
        "Solution Process ID": item.get("solutionProcessId"),
        "Title": item.get("title"),
        "Prepared": item.get("isPrepared"),
        "Priority": TESTCASE_PRIORITY_MAP.get(priority_code, priority_code),
        "Tags": tags,
        "Last Changed": item.get("modifiedAt"),
    }


def create_test_case(
    token: str,
    title: str,
    project_id: str | None = None,
    scope_id: str | None = None,
    solution_process_id: str | None = None,
    priority: str | None = None,
    is_prepared: bool | None = None,
    activities: list | None = None,
    references: list | None = None,
    solution_process_flow_id: str | None = None,
    solution_process_flow_diagram_id: str | None = None,
    content_package_id: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create a manual test case. Returns the created test case, formatted.

    `priorityCode` is sent numeric (10/20/30/40). POST supports deep insert of
    nested steps: pass `activities` as a list of activity dicts (each may contain
    a `toActions` list) and `references` as a list of {name, url}.

    To create a *process-linked* test case, all four of solution_process_id,
    solution_process_flow_id, solution_process_flow_diagram_id, and
    content_package_id must be provided together (content_package_id is "CUSTOM"
    for custom processes).
    """
    body: dict[str, Any] = {"title": title}
    if project_id is not None:
        body["projectId"] = project_id
    if scope_id is not None:
        body["scopeId"] = scope_id
    if solution_process_id is not None:
        body["solutionProcessId"] = solution_process_id
    if solution_process_flow_id is not None:
        body["solutionProcessFlowId"] = solution_process_flow_id
    if solution_process_flow_diagram_id is not None:
        body["solutionProcessFlowDiagramId"] = solution_process_flow_diagram_id
    if content_package_id is not None:
        body["contentPackageId"] = content_package_id
    if priority is not None:
        body["priorityCode"] = int(resolve_testcase_priority(priority))
    if is_prepared is not None:
        body["isPrepared"] = is_prepared
    if activities is not None:
        body["toActivities"] = test_activities_body(activities)
    if references is not None:
        body["toReferences"] = references

    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases"
    result = _write("POST", url, token, body, user_email=user_email)
    return _format_test_case(result) if isinstance(result, dict) and result else {"submitted": body}


def update_test_case(
    token: str,
    test_case_id: str,
    title: str | None = None,
    scope_id: str | None = None,
    solution_process_id: str | None = None,
    priority: str | None = None,
    is_prepared: bool | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Partial-update a manual test case. Only provided fields are sent.

    OData service — PATCH requires If-Match. The ETag is the entity's modifiedAt
    timestamp; if `if_match` is not supplied it is fetched from the entity.
    Note: deep updates of nested Activities/Actions are not supported here — use
    their own endpoints.
    """
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if scope_id is not None:
        body["scopeId"] = scope_id
    if solution_process_id is not None:
        body["solutionProcessId"] = solution_process_id
    if priority is not None:
        body["priorityCode"] = int(resolve_testcase_priority(priority))
    if is_prepared is not None:
        body["isPrepared"] = is_prepared
    if not body:
        raise ValueError("No fields to update — provide at least one field.")

    url = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases/{test_case_id}"
    etag = _tm_if_match(if_match)
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
    return _format_test_case(result) if isinstance(result, dict) and result else {"updated": test_case_id, "fields": body}


# ---------------------------------------------------------------------------
# CALM delete functions (guarded at the tool layer by CALM_ENABLE_WRITES)
# ---------------------------------------------------------------------------

def delete_task(token: str, task_id: str, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Delete a task. Plain REST — no If-Match. Returns {"deleted": task_id}."""
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}"
    _delete(url, token, user_email=user_email)
    return {"deleted": task_id}


def delete_business_process(
    token: str, business_process_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    """Delete a business process. OData — DELETE needs If-Match (auto-fetched)."""
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/businessProcesses/{business_process_id}"
    etag = _resolve_etag(url, token, if_match)
    _delete(url, token, if_match=etag, user_email=user_email)
    return {"deleted": business_process_id}


def delete_solution_process(
    token: str, solution_process_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    """Delete a solution process. OData — DELETE needs If-Match (auto-fetched)."""
    url = f"{_base_url(base_url)}/api/calm-processauthoring/v1/solutionProcesses/{solution_process_id}"
    etag = _resolve_etag(url, token, if_match)
    _delete(url, token, if_match=etag, user_email=user_email)
    return {"deleted": solution_process_id}


def delete_scope(
    token: str, scope_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    """Delete a scope. OData; spec confirms no If-Match needed (honoured if given)."""
    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes/{scope_id}"
    _delete(url, token, if_match=if_match, user_email=user_email)
    return {"deleted": scope_id}


def delete_test_case(
    token: str,
    test_case_id: str,
    force: bool = False,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Delete a manual test case. OData — DELETE needs If-Match (= modifiedAt).

    Plain DELETE fails (412) if the test case has execution history. Set
    `force=True` to call the force-delete action, which also removes test runs
    and results (requires the calm-api.testcases.force-delete scope).
    """
    base = f"{_base_url(base_url)}/api/calm-testmanagement/v1/ManualTestCases/{test_case_id}"
    etag = _tm_if_match(if_match)
    if force:
        action_url = f"{base}/api.v1.ExternalTestCaseServiceAPI.forceDeletionIncludingTestRunsAndResults"
        _write("POST", action_url, token, {}, if_match=etag, user_email=user_email)
        return {"deleted": test_case_id, "force": True}
    _delete(base, token, if_match=etag, user_email=user_email)
    return {"deleted": test_case_id}


# ===========================================================================
# Sub-entity write functions
# ===========================================================================

# --- Generic escape hatch ---------------------------------------------------

def api_read(
    token: str,
    path: str,
    params: dict | None = None,
    base_url: str | None = None,
) -> Any:
    """Low-level GET for any CALM API path (read-only escape hatch, mirroring
    api_write/api_delete). `path` is relative to the tenant base URL, e.g.
    "api/calm-projects/v1/projects" or "api/calm-tasks/v1/tasks/{id}". Optional
    `params` are appended as the query string. Uses the same GET path as the
    dedicated read tools so it works against the CALM read endpoints. Read-only —
    never gated by CALM_ENABLE_WRITES.
    """
    url = f"{_base_url(base_url)}/{path.lstrip('/')}"
    if params:
        from urllib.parse import urlencode

        sep = "&" if "?" in url else "?"
        # quote_via=quote (not the default quote_plus): spaces must encode as %20,
        # not '+'. An OData $filter passed through params with '+' is rejected by
        # CALM (HTTP 400) — the same mangle that once silently capped filtered
        # listings at 100 rows. Encode OData query strings the %20 way.
        url = f"{url}{sep}{urlencode(params, quote_via=quote)}"

    # The escape hatch obeys the SAME no-silent-truncation contract as every
    # dedicated list tool. If the caller drives paging themselves ($top/$skip),
    # honor that single page. Otherwise, when the response is an OData collection
    # envelope ({"value":[...]}), page it to exhaustion via _get_all (which also
    # raises the ⚠️ alert on a hard ceiling) and return the SAME envelope shape
    # with its value fully populated. Single entities and bare lists (already
    # complete, and $skip-rejecting) pass straight through unchanged.
    lowered = url.lower()
    caller_paging = "$top" in lowered or "%24top" in lowered or "$skip" in lowered or "%24skip" in lowered
    first = _get(url, token, allow_text=True)
    if caller_paging or not isinstance(first, dict) or "value" not in first:
        return first
    rows = _get_all(url, token)  # one redundant first GET; correctness over a hot path
    out = dict(first)
    out["value"] = rows
    out["@odata.count"] = len(rows)
    return out


def api_write(
    token: str,
    method: str,
    path: str,
    body: dict | list | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> Any:
    """Low-level POST/PATCH to any CALM API path (escape hatch for endpoints
    without a dedicated tool). `path` is relative to the tenant base URL, e.g.
    "api/calm-tasks/v1/tasks/{id}/comments". Returns the parsed response or a
    small ack. Pass `if_match` where the target service requires an ETag.
    """
    url = f"{_base_url(base_url)}/{path.lstrip('/')}"
    result = _write(method.upper(), url, token, body if body is not None else {}, if_match=if_match, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "method": method.upper(), "path": path}


def api_delete(token: str, path: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Low-level DELETE to any CALM API path (escape hatch). `path` is relative to
    the tenant base URL. Pass `if_match` where the target service requires an ETag.
    """
    url = f"{_base_url(base_url)}/{path.lstrip('/')}"
    _delete(url, token, if_match=if_match, user_email=user_email)
    return {"deleted": path}


# --- Task sub-entities (plain REST, no If-Match) ---------------------------

def get_task_comments(token: str, task_id: str, base_url: str | None = None) -> list[dict]:
    """A task's comments, oldest first."""
    items = _get(f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}/comments", token) or []
    rows = [{"ID": c.get("id"), "Text": c.get("text"), "Created": c.get("createdTimestamp"),
             "Changed": c.get("changedTimestamp"), "Created By": c.get("createdBy")}
            for c in items if isinstance(c, dict)]
    return sorted(rows, key=lambda r: str(r.get("Created") or ""))


_RELATED_READ_MAX = 25


def get_task_relations(token: str, task_id: str, base_url: str | None = None) -> list[dict]:
    """A task's relations — on a requirement, the user stories and tasks linked
    under it — each with the related task's display ID, title and type."""
    base = _base_url(base_url)
    items = _get(f"{base}/api/calm-tasks/v1/tasks/{task_id}/relations", token) or []
    rows = []
    for n, rel in enumerate(r for r in items if isinstance(r, dict)):
        related = _read_task_back(f"{base}/api/calm-tasks/v1/tasks/{rel.get('relationTaskId')}", token) \
            if n < _RELATED_READ_MAX else None
        rows.append({
            "Relation ID": rel.get("id"), "Relation Type": rel.get("type"),
            "Related Task ID": rel.get("relationTaskId"),
            "Related Display ID": (related or {}).get("displayId"),
            "Related Title": (related or {}).get("title"),
            "Related Type": TASK_TYPE_MAP.get((related or {}).get("type"), (related or {}).get("type")),
        })
    return rows


def create_task_relation(
    token: str, task_id: str, relation_task_id: str, relation_type: str = "0", base_url: str | None = None, user_email: str | None = None
) -> dict:
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}/relations"
    result = _write("POST", url, token, {"type": relation_type, "relationTaskId": relation_task_id}, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True}


def delete_task_relation(token: str, relation_id: str, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/relations/{relation_id}"
    _delete(url, token, user_email=user_email)
    return {"deleted": relation_id}


def _tag_key(tag: Any) -> str:
    return " ".join(str(tag).replace(":", ": ").split()).lower()


def set_task_tags(token: str, task_id: str, tags: list, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Replace a task's tag assignments. Tags look like "Group: Tag".

    Setting tags replaces them all, so it is safe to repeat: when SAP drops the
    connection, the task is read back and, if the tags aren't there, they are
    sent once more."""
    base = _base_url(base_url)
    url = f"{base}/api/calm-tasks/v1/tasks/updateTags"
    body = {"taskId": task_id, "tags": tags}
    done = {"ok": True, "taskId": task_id, "tags": tags}

    def stored_ok() -> bool:
        http_retry._sleep(WRITE_SETTLE)
        item = _read_task_back(f"{base}/api/calm-tasks/v1/tasks/{task_id}", token)
        return item is not None and {_tag_key(t) for t in item.get("tags") or []} == {_tag_key(t) for t in tags}

    for attempt in (1, 2):
        try:
            result = _write("POST", url, token, body, user_email=user_email)
        except http_retry.WriteUnconfirmed as exc:
            if stored_ok():
                return _with_note(done, "SAP dropped the connection, but reading the task back shows the tags are set.")
            if attempt == 2:
                raise RuntimeError(
                    f"SAP Cloud ALM dropped the connection on both attempts to set the tags of task "
                    f"{task_id} ({exc.reason or 'no response'}), and they are not on the task. Setting "
                    "tags is safe to retry; if it keeps happening, SAP is failing writes on this tenant."
                ) from exc
            log.warning("tag update for %s unconfirmed; sending it again", task_id)
            continue
        out = result if (isinstance(result, dict) and result) else done
        return _with_note(out, "SAP dropped the first attempt; the tags were sent again and set.") if attempt == 2 else out
    return done  # pragma: no cover - the loop always returns or raises


def create_task_comment(
    token: str, task_id: str, text: str | None = None, extra_fields: dict | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    """Add a comment to a task. The exact body field is not documented; `text` is
    sent as-is and `extra_fields` can override/augment it."""
    body: dict[str, Any] = {}
    if text is not None:
        body["text"] = text
    if extra_fields:
        body.update(_api_field_names(extra_fields))
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/{task_id}/comments"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "submitted": body}


def update_task_comment(
    token: str, comment_id: str, text: str | None = None, extra_fields: dict | None = None, base_url: str | None = None, user_email: str | None = None
) -> dict:
    body: dict[str, Any] = {}
    if text is not None:
        body["text"] = text
    if extra_fields:
        body.update(_api_field_names(extra_fields))
    if not body:
        raise ValueError("No fields to update — provide at least one field.")
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/comments/{comment_id}"
    result = _write("PATCH", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"updated": comment_id}


def delete_task_comment(token: str, comment_id: str, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = f"{_base_url(base_url)}/api/calm-tasks/v1/tasks/comments/{comment_id}"
    _delete(url, token, user_email=user_email)
    return {"deleted": comment_id}


# --- Project timeboxes (plain REST, no If-Match) ---------------------------

# Timebox types as CALM numbers them (verified on live projects).
TIMEBOX_TYPES = {"milestone": 0, "phase": 1, "sprint": 2, "iteration": 2}


def resolve_timebox_type(value: Any) -> int:
    """A timebox type as CALM's number: 0 milestone, 1 phase, 2 sprint."""
    if isinstance(value, bool):
        raise ValueError(f"Unknown timebox type {value!r}. Use sprint, phase or milestone (2/1/0).")
    if isinstance(value, int) or str(value).strip().isdigit():
        return int(value)
    code = TIMEBOX_TYPES.get(_squash(value).rstrip("s"))
    if code is None:
        raise ValueError(f"Unknown timebox type {value!r}. Use sprint, phase or milestone (2/1/0).")
    return code


def create_timebox(
    token: str,
    project_id: str,
    name: str | None = None,
    timebox_type: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    closed: bool | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    # SAP requires the type; a timebox asked for without one is a sprint.
    body["type"] = resolve_timebox_type(2 if timebox_type is None else timebox_type)
    if start_date is not None:
        body["startDate"] = api_date(start_date, "start_date")
    if end_date is not None:
        body["endDate"] = api_date(end_date, "end_date")
    if closed is not None:
        body["closed"] = closed
    if extra_fields:
        body.update(_api_field_names(extra_fields))
    url = f"{_base_url(base_url)}/api/calm-projects/v1/projects/{project_id}/timeboxes"
    result = _write("POST", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "submitted": body}


def update_timebox(
    token: str,
    timebox_id: str,
    name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    closed: bool | None = None,
    extra_fields: dict | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if start_date is not None:
        body["startDate"] = api_date(start_date, "start_date")
    if end_date is not None:
        body["endDate"] = api_date(end_date, "end_date")
    if closed is not None:
        body["closed"] = closed
    if extra_fields:
        body.update(_api_field_names(extra_fields))
    if not body:
        raise ValueError("No fields to update — provide at least one field.")
    url = f"{_base_url(base_url)}/api/calm-projects/v1/timeboxes/{timebox_id}"
    result = _write("PATCH", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"updated": timebox_id}


def delete_timebox(token: str, timebox_id: str, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = f"{_base_url(base_url)}/api/calm-projects/v1/timeboxes/{timebox_id}"
    _delete(url, token, user_email=user_email)
    return {"deleted": timebox_id}


# --- Process management: scope assignments & scenario versions -------------

def assign_scenario_versions(token: str, scope_id: str, version_ids: list, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Assign one or more solution-scenario versions to a scope."""
    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/scopes/{scope_id}/solutionScenarioVersions"
    body = {"value": [{"id": v} for v in version_ids]}
    result = _write("POST", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "scopeId": scope_id}


def update_scope_assignments(token: str, assignments: list, base_url: str | None = None, user_email: str | None = None) -> dict:
    """Scope/unscope solution processes. Each assignment is a dict with
    scopeId, solutionScenarioVersionId, solutionProcessVersionId, isScoped
    (required) and an optional statusId
    (EMPTY/DESIGN/REALIZATION/PRODUCTION/MAINTENANCE/OBSOLETE)."""
    url = f"{_base_url(base_url)}/api/calm-processmanagement/v1/solutionProcesses/scopeAssignments"
    result = _write("PATCH", url, token, {"value": assignments}, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "count": len(assignments)}


# --- Test management: activities & actions (OData, If-Match = modifiedAt) ---

def _tm_url(base_url: str | None, path: str) -> str:
    return f"{_base_url(base_url)}/api/calm-testmanagement/v1/{path}"


_ACTION_KEYS = {"expected_result": "expectedResult", "expected": "expectedResult",
                "is_evidence_required": "isEvidenceRequired", "evidence_required": "isEvidenceRequired",
                "instructions": "description", "step": "title", "action": "title"}
_ACTIVITY_KEYS = {"is_in_scope": "isInScope", "actions": "toActions", "steps": "toActions",
                  "to_actions": "toActions"}


def test_action_body(action: dict, position: int) -> dict:
    """One test step the way SAP requires it: title, a non-empty description
    (the title when none is given), expectedResult, isEvidenceRequired, sequence."""
    a = {_ACTION_KEYS.get(k, k): v for k, v in dict(action).items() if v is not None}
    if not a.get("title"):
        raise ValueError(f"each test step needs a title (step {position} has none)")
    a["description"] = a.get("description") or a["title"]
    a.setdefault("expectedResult", "")
    a.setdefault("isEvidenceRequired", False)
    a.setdefault("sequence", position)
    return a


def test_activities_body(activities: list) -> list:
    """Activities (with their steps) for a deep insert, completed as SAP requires."""
    out = []
    for n, activity in enumerate(activities or [], start=1):
        act = {_ACTIVITY_KEYS.get(k, k): v for k, v in dict(activity).items() if v is not None}
        act.setdefault("sequence", n)
        if act.get("toActions") is not None:
            act["toActions"] = [test_action_body(a, i) for i, a in enumerate(act["toActions"], start=1)]
        out.append(act)
    return out


def create_test_action(
    token: str,
    activity_id: str,
    title: str,
    description: str | None = None,
    expected_result: str | None = None,
    sequence: int | None = None,
    is_evidence_required: bool | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    """Create an action (step) under an activity (POST /Activities/{id}/toActions).

    SAP requires the parent activity in the body, a non-empty description, an
    expected result and a sequence: a missing description is the step's title,
    a missing sequence comes after the activity's last step."""
    if sequence is None:
        try:
            existing = _get(_tm_url(base_url, f"Activities/{activity_id}/toActions?$select=sequence"), token)
            rows = existing.get("value", []) if isinstance(existing, dict) else []
            sequence = max([int(a.get("sequence") or 0) for a in rows] or [0]) + 1
        except Exception:  # noqa: BLE001 — SAP orders by sequence; 1 is always valid
            sequence = 1
    body = test_action_body({"title": title, "description": description, "expectedResult": expected_result,
                             "isEvidenceRequired": is_evidence_required}, sequence)
    body["parent_ID"] = activity_id
    url = _tm_url(base_url, f"Activities/{activity_id}/toActions")
    result = _write("POST", url, token, body, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"ok": True, "submitted": body}


def update_test_action(
    token: str,
    action_id: str,
    title: str | None = None,
    description: str | None = None,
    expected_result: str | None = None,
    sequence: int | None = None,
    is_evidence_required: bool | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if description is not None:
        body["description"] = description
    if expected_result is not None:
        body["expectedResult"] = expected_result
    if sequence is not None:
        body["sequence"] = sequence
    if is_evidence_required is not None:
        body["isEvidenceRequired"] = is_evidence_required
    if not body:
        raise ValueError("No fields to update — provide at least one field.")
    url = _tm_url(base_url, f"Actions/{action_id}")
    etag = _tm_if_match(if_match)
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"updated": action_id}


def delete_test_action(token: str, action_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = _tm_url(base_url, f"Actions/{action_id}")
    etag = _tm_if_match(if_match)
    _delete(url, token, if_match=etag, user_email=user_email)
    return {"deleted": action_id}


def update_test_activity(
    token: str,
    activity_id: str,
    title: str | None = None,
    sequence: int | None = None,
    is_in_scope: bool | None = None,
    if_match: str | None = None,
    base_url: str | None = None, user_email: str | None = None,
) -> dict:
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if sequence is not None:
        body["sequence"] = sequence
    if is_in_scope is not None:
        body["isInScope"] = is_in_scope
    if not body:
        raise ValueError("No fields to update — provide at least one field.")
    url = _tm_url(base_url, f"Activities/{activity_id}")
    etag = _tm_if_match(if_match)
    result = _write("PATCH", url, token, body, if_match=etag, user_email=user_email)
    return result if (isinstance(result, dict) and result) else {"updated": activity_id}


def delete_test_activity(token: str, activity_id: str, if_match: str | None = None, base_url: str | None = None, user_email: str | None = None) -> dict:
    url = _tm_url(base_url, f"Activities/{activity_id}")
    etag = _tm_if_match(if_match)
    _delete(url, token, if_match=etag, user_email=user_email)
    return {"deleted": activity_id}
