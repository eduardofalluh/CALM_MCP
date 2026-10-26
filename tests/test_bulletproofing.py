"""Bulletproofing sweep: close the read/write gaps a two-sided audit surfaced.

Three groups:

1. READ defects — the two real under-return paths the audit flagged, now fixed:
   * calm_api_read escape hatch pages OData collections to exhaustion and feeds
     the ⚠️ truncation sink on a ceiling (was: single page, silent cut-off).
   * get_analytics with BOTH top and project_id no longer short-circuits on the
     RAW row count (which could drop project rows past the cutoff), and its
     max-rows ceiling records a truncation notice.

2. CALM-native WRITE wiring — functions that had NO test now assert their real
   URL / body / If-Match construction (patching the HTTP boundary helpers).

3. TM write surface — the entire tm_client write surface was untested; pin URL,
   OData-key escaping, and ETag handling.

Plus a low-level contract test proving an HTTP error surfaces status+url but
NEVER leaks the bearer token.
"""

from unittest.mock import patch

import pytest

from src.calm import client
from src.calm import tm_client as tm

TOKEN = "secret-bearer-token-DO-NOT-LEAK"
BASE = "https://x.alm.cloud.sap"
TM_BASE = "https://tm.example.hana.ondemand.com/odata/v4/test-management"


# ===========================================================================
# 1. READ defects
# ===========================================================================

def test_api_read_pages_odata_collection_to_exhaustion():
    # A collection fetched via the escape hatch must NOT stop at the first server
    # page — it pages like every dedicated list tool and returns the full value.
    def fake_get(url, token, **kw):
        if "__next_page__" in url or "%24skip=100" in url or "$skip=100" in url:
            return {"value": [{"id": 100}]}
        return {"value": [{"id": i} for i in range(100)],
                "@odata.nextLink": f"{BASE}/__next_page__"}

    with patch("src.calm.client._get", side_effect=fake_get):
        out = client.api_read(token=TOKEN, path="api/calm-projects/v1/projects", base_url=BASE)
    assert isinstance(out, dict) and "value" in out
    assert len(out["value"]) == 101            # both pages, not just the first 100
    assert out["@odata.count"] == 101


def test_api_read_honors_explicit_top_as_single_page():
    calls = []

    def fake_get(url, token, **kw):
        calls.append(url)
        return {"value": [{"id": 1}], "@odata.nextLink": f"{BASE}/__next_page__"}

    with patch("src.calm.client._get", side_effect=fake_get):
        out = client.api_read(token=TOKEN, path="api/calm-projects/v1/projects",
                              params={"$top": 1}, base_url=BASE)
    # Caller is driving paging — one request, nextLink NOT followed.
    assert len(calls) == 1
    assert out["value"] == [{"id": 1}]


def test_api_read_single_entity_passes_through_unchanged():
    entity = {"id": "3-1", "title": "One task"}  # no "value" -> not a collection
    with patch("src.calm.client._get", return_value=entity):
        out = client.api_read(token=TOKEN, path="api/calm-tasks/v1/tasks/3-1", base_url=BASE)
    assert out == entity


def test_api_read_bare_list_passes_through_unchanged():
    bare = [{"id": 1}, {"id": 2}]  # bare list is already complete
    with patch("src.calm.client._get", return_value=bare):
        out = client.api_read(token=TOKEN, path="api/calm-tasks/v1/tasks", base_url=BASE)
    assert out == bare


def test_api_read_ceiling_feeds_truncation_sink():
    # Endless distinct pages: only the row ceiling can stop it, and when it does
    # the shared sink must record the cut-off so the ⚠️ alert fires.
    counter = {"n": 0}

    def endless(url, token, **kw):
        base = counter["n"] * 100
        counter["n"] += 1
        return {"value": [{"id": base + i} for i in range(100)],
                "@odata.nextLink": f"{BASE}/__next_page__"}

    sink, tok = client.install_truncation_sink()
    orig = client._PAGE_MAX_ROWS
    client._PAGE_MAX_ROWS = 250
    try:
        with patch("src.calm.client._get", side_effect=endless):
            client.api_read(token=TOKEN, path="api/calm-projects/v1/projects", base_url=BASE)
    finally:
        client._PAGE_MAX_ROWS = orig
        client.reset_truncation_sink(tok)
    assert len(sink) == 1
    assert sink[0]["limit"] == "max-rows"


def test_analytics_top_with_project_id_does_not_undercount():
    # Project rows live PAST the raw `top` cutoff. The old early-break on raw
    # count returned 0 project rows; the fix pages fully then filters then caps.
    pages = [
        [{"project": "OTHER"}, {"project": "OTHER"}],  # page 1 (full)
        [{"project": "P1"}, {"project": "P1"}],        # page 2 (full)
        [{"project": "P1"}],                            # page 3 (short -> stop)
    ]

    def fake_get(url, token, **kw):
        # pick the page by $skip
        import re
        m = re.search(r"(?:\$|%24)skip=(\d+)", url)
        idx = int(m.group(1)) // 2 if m else 0
        page = pages[idx] if idx < len(pages) else []
        return {"value": page}

    with patch("src.calm.client._ANALYTICS_PAGE", 2), \
         patch("src.calm.client._unpivot_analytics_row", lambda r: r), \
         patch("src.calm.client._get", side_effect=fake_get):
        rows = client.get_analytics("tasks", TOKEN, BASE, project_id="P1", top=1)
    # Exactly `top` project rows — found despite living beyond the raw cutoff.
    assert len(rows) == 1
    assert rows[0]["project"] == "P1"


def test_analytics_ceiling_feeds_truncation_sink():
    def endless(url, token, **kw):
        return {"value": [{"project": "P1"}, {"project": "P1"}]}  # always a full page

    sink, tok = client.install_truncation_sink()
    with patch("src.calm.client._ANALYTICS_PAGE", 2), \
         patch("src.calm.client._ANALYTICS_MAX_ROWS", 4), \
         patch("src.calm.client._unpivot_analytics_row", lambda r: r), \
         patch("src.calm.client._get", side_effect=endless):
        try:
            client.get_analytics("tasks", TOKEN, BASE)
        finally:
            client.reset_truncation_sink(tok)
    assert len(sink) == 1
    assert sink[0]["limit"] == "max-rows"


# ===========================================================================
# 2. CALM-native write wiring (previously untested)
# ===========================================================================

def test_update_business_process_patches_with_resolved_etag():
    with patch("src.calm.client._resolve_etag", return_value="etag-7") as re_, \
         patch("src.calm.client._write", return_value={}) as w:
        client.update_business_process(TOKEN, "BP1", name="New", base_url=BASE)
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "PATCH"
    assert url == f"{BASE}/api/calm-processauthoring/v1/businessProcesses/BP1"
    assert body == {"name": "New"}                 # only provided fields
    assert w.call_args.kwargs["if_match"] == "etag-7"
    assert re_.called                               # auto-fetched the ETag


def test_update_business_process_empty_body_raises():
    with pytest.raises(ValueError):
        client.update_business_process(TOKEN, "BP1", base_url=BASE)


def test_update_solution_process_patches_resolved_etag():
    with patch("src.calm.client._resolve_etag", return_value="e9"), \
         patch("src.calm.client._write", return_value={}) as w:
        client.update_solution_process(TOKEN, "SP1", status="Active", base_url=BASE)
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "PATCH"
    assert url == f"{BASE}/api/calm-processauthoring/v1/solutionProcesses/SP1"
    assert body == {"status": "Active"}
    assert w.call_args.kwargs["if_match"] == "e9"


def test_create_scope_posts_body_to_processmanagement():
    with patch("src.calm.client._write", return_value={"id": "SC1"}) as w:
        client.create_scope(TOKEN, "P1", "Finance", description="d", base_url=BASE)
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "POST"
    assert url == f"{BASE}/api/calm-processmanagement/v1/scopes"
    assert body == {"projectId": "P1", "name": "Finance", "description": "d"}


def test_update_test_case_patches_with_priority_code_and_wildcard_etag():
    with patch("src.calm.client._write", return_value={}) as w:
        client.update_test_case(TOKEN, "TC1", title="T", priority="High", base_url=BASE)
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "PATCH"
    assert url == f"{BASE}/api/calm-testmanagement/v1/ManualTestCases/TC1"
    assert body["title"] == "T"
    assert isinstance(body["priorityCode"], int)   # resolved to a numeric code
    # TM If-Match defaults to the "*" wildcard when the caller passes none.
    assert w.call_args.kwargs["if_match"] == "*"


def test_update_test_case_empty_body_raises():
    with pytest.raises(ValueError):
        client.update_test_case(TOKEN, "TC1", base_url=BASE)


def test_update_timebox_patches_projects_service():
    with patch("src.calm.client._write", return_value={}) as w:
        client.update_timebox(TOKEN, "TB1", name="Sprint 2", base_url=BASE)
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "PATCH"
    assert url == f"{BASE}/api/calm-projects/v1/timeboxes/TB1"
    assert body == {"name": "Sprint 2"}


def test_api_write_uppercases_method_and_passes_if_match():
    with patch("src.calm.client._write", return_value={"ok": 1}) as w:
        client.api_write(TOKEN, "patch", "api/calm-tasks/v1/tasks/3-1",
                         body={"x": 1}, if_match="E1", base_url=BASE)
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "PATCH"
    assert url == f"{BASE}/api/calm-tasks/v1/tasks/3-1"
    assert body == {"x": 1}
    assert w.call_args.kwargs["if_match"] == "E1"


def test_api_delete_builds_url_and_returns_ack():
    with patch("src.calm.client._delete", return_value={}) as d:
        out = client.api_delete(TOKEN, "/api/calm-tasks/v1/tasks/3-1", if_match="E", base_url=BASE)
    url = d.call_args.args[0]
    assert url == f"{BASE}/api/calm-tasks/v1/tasks/3-1"
    assert d.call_args.kwargs["if_match"] == "E"
    assert out == {"deleted": "/api/calm-tasks/v1/tasks/3-1"}


# ===========================================================================
# 3. TM (Test Management) write surface (previously untested)
# ===========================================================================

def test_tm_create_requirement_posts_to_requirements():
    with patch("src.calm.tm_client._write", return_value={"ID": "r1"}) as w:
        tm.create_requirement(TOKEN, TM_BASE, {"tr_id": "R-1"})
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "POST"
    assert url == f"{TM_BASE}/Requirements"
    assert body == {"tr_id": "R-1"}


def test_tm_create_test_case_posts_deep_insert():
    deep = {"title": "TC", "activities": [{"actions": [{"fields": []}]}]}
    with patch("src.calm.tm_client._write", return_value={"ID": "tc1"}) as w:
        tm.create_test_case(TOKEN, TM_BASE, deep)
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "POST"
    assert url == f"{TM_BASE}/TestCases"
    assert body == deep                             # deep tree passed through verbatim


def test_tm_update_test_case_escapes_key_and_resolves_etag():
    with patch("src.calm.tm_client._resolve_etag", return_value="W/\"1\"") as re_, \
         patch("src.calm.tm_client._write", return_value={}) as w:
        tm.update_test_case(TOKEN, TM_BASE, "a'b", {"title": "X"})
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "PATCH"
    # OData key single-quote doubled -> no breakage/injection.
    assert url == f"{TM_BASE}/TestCases('a''b')"
    assert body == {"title": "X"}
    assert w.call_args.kwargs["if_match"] == "W/\"1\""
    assert re_.called


def test_tm_delete_requirement_escapes_key_and_cascades():
    with patch("src.calm.tm_client._resolve_etag", return_value="*"), \
         patch("src.calm.tm_client._delete", return_value={}) as d:
        out = tm.delete_requirement(TOKEN, TM_BASE, "r'1")
    assert d.call_args.args[0] == f"{TM_BASE}/Requirements('r''1')"
    assert out["deleted"] == "r'1"
    assert "cascade" in out


def test_tm_delete_test_case_escapes_key():
    with patch("src.calm.tm_client._resolve_etag", return_value="*"), \
         patch("src.calm.tm_client._delete", return_value={}) as d:
        out = tm.delete_test_case(TOKEN, TM_BASE, "tc'9")
    assert d.call_args.args[0] == f"{TM_BASE}/TestCases('tc''9')"
    assert out == {"deleted": "tc'9"}


def test_tm_odata_write_rejects_non_post_patch():
    with pytest.raises(ValueError):
        tm.odata_write(TOKEN, TM_BASE, "DELETE", "Activities('x')", {})


def test_tm_odata_write_passes_method_and_path():
    with patch("src.calm.tm_client._write", return_value={}) as w:
        tm.odata_write(TOKEN, TM_BASE, "patch", "Activities('x')", {"n": 1}, if_match="E")
    method, url, _tok, body = w.call_args.args[:4]
    assert method == "PATCH"
    assert url == f"{TM_BASE}/Activities('x')"
    assert body == {"n": 1}
    assert w.call_args.kwargs["if_match"] == "E"


def test_tm_odata_delete_defaults_wildcard_if_match():
    with patch("src.calm.tm_client._delete", return_value={}) as d:
        out = tm.odata_delete(TOKEN, TM_BASE, "Actions('x')")
    assert d.call_args.args[0] == f"{TM_BASE}/Actions('x')"
    assert d.call_args.kwargs["if_match"] == "*"
    assert out == {"deleted": "Actions('x')"}


# ===========================================================================
# Low-level contract: HTTP errors surface status+url, NEVER the token
# ===========================================================================

class _Resp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.reason = "Bad Request"
        self.text = text
        self.headers = {}

    def json(self):
        return {}


def test_write_error_surfaces_status_and_url_without_leaking_token():
    class _FakeRequests:
        def request(self, *a, **k):
            return _Resp(400, text="field 'name' is required")

    with patch("src.calm.client.requests", _FakeRequests()):
        with pytest.raises(RuntimeError) as ei:
            client._write("POST", f"{BASE}/api/calm-projects/v1/projects", TOKEN, {"x": 1})
    msg = str(ei.value)
    assert "400" in msg
    assert f"{BASE}/api/calm-projects/v1/projects" in msg
    assert "field 'name' is required" in msg       # the API's real reason is shown
    assert TOKEN not in msg                          # ...but never the bearer token


def test_delete_error_surfaces_status_without_leaking_token():
    class _FakeRequests:
        def request(self, *a, **k):
            return _Resp(412, text="precondition failed")

    with patch("src.calm.client.requests", _FakeRequests()):
        with pytest.raises(RuntimeError) as ei:
            client._delete(f"{BASE}/api/calm-tasks/v1/tasks/3-1", TOKEN, if_match="stale")
    msg = str(ei.value)
    assert "412" in msg
    assert TOKEN not in msg
