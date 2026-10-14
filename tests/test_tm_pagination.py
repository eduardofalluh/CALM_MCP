"""Hardening tests for the list/truncation layer across BOTH clients.

Three groups, all pinning the "no list endpoint silently truncates" contract:

1. TM paging — the BTP Test Management OData V4 client (`tm_client`) now follows
   ``@odata.nextLink`` to exhaustion via its own ``_get_all``. These tests pin
   nextLink exhaustion, the CAP *relative* nextLink path-preservation regression
   (resolving against the current request URL so the ``/odata/v4/...`` service
   path is kept, not dropped), and that a hard ceiling feeds the SHARED CALM
   truncation sink so a TM cut-off raises the same ``⚠️`` alert.

2. Worker-thread sink proof — the whole alert mechanism depends on a ContextVar
   whose *list* object is shared across the context copy FastMCP makes when it
   runs a sync tool in a worker thread. This drives ``_record_truncation`` from a
   real worker thread and asserts the installed sink still sees the notice.

3. All-getters paging lock-in — every ``client.py`` list getter is driven through
   a 2-page ``_get`` mock and must return BOTH pages' rows, proving each is wired
   to ``_get_all`` and locking out any future revert to a single-page ``_get``.
"""

from unittest.mock import patch

import anyio
import pytest

from src.calm import client
from src.calm import tm_client as tm


# ===========================================================================
# 1. Test Management (CAP OData V4) paging
# ===========================================================================

TM_BASE = "https://tm.example.hana.ondemand.com/odata/v4/test-management"


def test_tm_follows_relative_next_link_keeping_service_path():
    # CAP emits a RELATIVE nextLink ("TestCases?$skiptoken=..."). It must resolve
    # against the current request URL so the /odata/v4/test-management service
    # path is preserved — resolving against the host root alone would drop it and
    # the next GET would 404, silently truncating at page one.
    seen_urls: list[str] = []

    def fake(url, token, params=None):
        seen_urls.append(url)
        if "$skiptoken" in url:
            return {"value": [{"ID": "b"}]}  # short page -> stop
        return {"value": [{"ID": "a"}], "@odata.nextLink": "TestCases?$skiptoken=X"}

    with patch("src.calm.tm_client._get", fake):
        out = tm._get_all(f"{TM_BASE}/TestCases", "tok")

    assert [r["ID"] for r in out["items"]] == ["a", "b"]
    # The second request kept the full service path (regression guard).
    assert seen_urls[1] == f"{TM_BASE}/TestCases?$skiptoken=X"
    assert "/odata/v4/test-management/" in seen_urls[1]


def test_tm_follows_absolute_next_link():
    def fake(url, token, params=None):
        if "page2" in url:
            return {"value": [{"ID": "b"}]}
        return {"value": [{"ID": "a"}],
                "@odata.nextLink": "https://tm.example.hana.ondemand.com/page2"}

    with patch("src.calm.tm_client._get", fake):
        out = tm._get_all(f"{TM_BASE}/TestCases", "tok")
    assert [r["ID"] for r in out["items"]] == ["a", "b"]


def test_tm_dedupes_and_stops_if_link_loops():
    # A link that loops back to the same page must not run away.
    def fake(url, token, params=None):
        return {"value": [{"ID": "a"}], "@odata.nextLink": "TestCases?$skiptoken=same"}

    with patch("src.calm.tm_client._get", fake):
        out = tm._get_all(f"{TM_BASE}/TestCases", "tok")
    assert [r["ID"] for r in out["items"]] == ["a"]  # dedup caught the loop


def test_tm_single_page_has_no_next_link():
    def fake(url, token, params=None):
        return {"value": [{"ID": "a"}, {"ID": "b"}], "@odata.count": 2}

    with patch("src.calm.tm_client._get", fake):
        out = tm._get_all(f"{TM_BASE}/TestCases", "tok")
    assert [r["ID"] for r in out["items"]] == ["a", "b"]
    assert out["count"] == 2
    assert "next_link" not in out  # fully consumed


def test_tm_non_collection_shape_passes_through():
    # A single entity / metadata_xml has no "value" — nothing to page.
    with patch("src.calm.tm_client._get",
               lambda url, token, params=None: {"ID": "solo", "title": "x"}):
        out = tm._get_all(f"{TM_BASE}/TestCases('solo')", "tok")
    assert out == {"ID": "solo", "title": "x"}


def test_tm_ceiling_feeds_shared_calm_truncation_sink():
    # Endless distinct pages: only the row ceiling can stop paging, and when it
    # does it must record on the SHARED CALM sink so the same middleware alert
    # fires for a TM cut-off as for a CALM one.
    counter = {"n": 0}

    def endless(url, token, params=None):
        base = counter["n"] * 100
        counter["n"] += 1
        return {"value": [{"ID": f"id-{base + i}"} for i in range(100)],
                "@odata.nextLink": "TestCases?$skiptoken=more"}

    sink, token = client.install_truncation_sink()
    orig = client._PAGE_MAX_ROWS
    client._PAGE_MAX_ROWS = 250
    try:
        with patch("src.calm.tm_client._get", endless):
            out = tm._get_all(f"{TM_BASE}/TestCases", "tok")
    finally:
        client._PAGE_MAX_ROWS = orig
        client.reset_truncation_sink(token)

    assert len(out["items"]) >= 100           # returned what it fetched
    assert len(sink) == 1                      # exactly one truncation recorded
    assert sink[0]["limit"] == "max-rows"
    assert sink[0]["resource"] == "TestCases"
    assert "TRUNCATED" in sink[0]["message"]


def test_tm_odata_read_routes_collection_through_pager():
    # A plain collection read (no explicit $top/$skip) must page to exhaustion.
    def fake(url, token, params=None):
        if "$skiptoken" in url:
            return {"value": [{"ID": "b"}]}
        return {"value": [{"ID": "a"}], "@odata.nextLink": "TestCases?$skiptoken=X"}

    with patch("src.calm.tm_client._get", fake):
        out = tm.odata_read("tok", TM_BASE, "TestCases")
    assert [r["ID"] for r in out["items"]] == ["a", "b"]


def test_tm_odata_read_honors_explicit_top_as_single_page():
    # An explicit $top means the caller is driving paging — one request only.
    calls = []

    def fake(url, token, params=None):
        calls.append(params)
        return {"value": [{"ID": "a"}], "@odata.nextLink": "TestCases?$skiptoken=X"}

    with patch("src.calm.tm_client._get", fake):
        out = tm.odata_read("tok", TM_BASE, "TestCases", query="$top=1")
    assert out["items"] == [{"ID": "a"}]
    assert len(calls) == 1  # did NOT follow the nextLink


def test_tm_odata_read_single_entity_is_single_request():
    calls = []

    def fake(url, token, params=None):
        calls.append(url)
        return {"ID": "solo"}

    with patch("src.calm.tm_client._get", fake):
        out = tm.odata_read("tok", TM_BASE, "TestCases('solo')")
    assert out == {"ID": "solo"}
    assert len(calls) == 1


def test_tm_get_test_cases_pages_when_unbounded():
    def fake(url, token, params=None):
        if "$skiptoken" in url:
            return {"value": [{"ID": "b"}]}
        return {"value": [{"ID": "a"}], "@odata.nextLink": "TestCases?$skiptoken=X"}

    with patch("src.calm.tm_client._get", fake):
        out = tm.get_test_cases("tok", TM_BASE)
    assert [r["ID"] for r in out["items"]] == ["a", "b"]


def test_tm_get_requirements_pages_when_unbounded():
    def fake(url, token, params=None):
        if "$skiptoken" in url:
            return {"value": [{"ID": "r2"}]}
        return {"value": [{"ID": "r1"}], "@odata.nextLink": "Requirements?$skiptoken=X"}

    with patch("src.calm.tm_client._get", fake):
        out = tm.get_requirements("tok", TM_BASE)
    assert [r["ID"] for r in out["items"]] == ["r1", "r2"]


def test_tm_odata_key_doubles_single_quote():
    assert tm._odata_key("a'b") == "a''b"
    assert tm._odata_key("plain-guid") == "plain-guid"


# ===========================================================================
# 2. Worker-thread truncation sink propagation
# ===========================================================================

def test_record_truncation_propagates_from_worker_thread():
    # FastMCP runs a sync tool via anyio.to_thread.run_sync, which copies the
    # context. _record_truncation only APPENDS to the sink list (never .set()),
    # so the copy — sharing the SAME list object the middleware installed — must
    # still see the notice. This exercises that path off the main thread.
    async def main():
        sink, token = client.install_truncation_sink()
        try:
            await anyio.to_thread.run_sync(
                lambda: client._record_truncation(
                    "https://x/api/calm-tasks/v1/tasks", 42, "max-rows")
            )
        finally:
            client.reset_truncation_sink(token)
        return sink

    sink = anyio.run(main)
    assert len(sink) == 1
    assert sink[0]["resource"] == "tasks"
    assert sink[0]["count"] == 42
    assert sink[0]["limit"] == "max-rows"


def test_record_truncation_from_thread_without_sink_is_safe():
    # No sink installed in the parent context — a worker-thread record must not
    # raise (alerting must never break a read).
    async def main():
        await anyio.to_thread.run_sync(
            lambda: client._record_truncation("https://x/api/calm-tasks/v1/tasks", 1, "max-rows")
        )

    anyio.run(main)  # no exception == pass


# ===========================================================================
# 3. All CALM list getters page end-to-end (lock-in)
# ===========================================================================

BASE = "https://x.alm.cloud.sap"
_NEXT = "https://x.alm.cloud.sap/__next_page__"


def _two_page_get():
    """A _get mock: first call -> 100 rows + absolute nextLink, then 1 short page.

    Rows carry no projectId so project-filtering getters (get_features) keep both
    pages; ids are distinct so the de-dup guard never trims them.
    """
    def fake(url, token):
        if "__next_page__" in url:
            return {"value": [{"id": 100, "uuid": "u100", "displayId": "100"}]}
        return {"value": [{"id": i, "uuid": f"u{i}", "displayId": str(i)} for i in range(100)],
                "@odata.nextLink": _NEXT}
    return fake


# name -> thunk that invokes the getter with the right positional args.
_GETTERS = {
    "get_tasks": lambda: client.get_tasks("proj", "tok", BASE),
    "get_projects": lambda: client.get_projects("tok", BASE),
    "get_business_processes": lambda: client.get_business_processes("tok", BASE),
    "get_solution_processes": lambda: client.get_solution_processes("tok", BASE),
    "get_scopes": lambda: client.get_scopes("tok", BASE),
    "get_test_cases": lambda: client.get_test_cases("tok", BASE),
    "get_timeboxes": lambda: client.get_timeboxes("proj", "tok", BASE),
    "get_teams": lambda: client.get_teams("tok", BASE),
    "get_project_teams": lambda: client.get_project_teams("proj", "tok", BASE),
    "get_tags": lambda: client.get_tags("proj", "tok", BASE),
    "get_project_users": lambda: client.get_project_users("proj", "tok", BASE),
    "get_features": lambda: client.get_features("proj", "tok", BASE),
    "get_team_roles": lambda: client.get_team_roles("team", "tok", BASE),
    "get_feature_status": lambda: client.get_feature_status("tok", BASE),
    "get_feature_priorities": lambda: client.get_feature_priorities("tok", BASE),
}


@pytest.mark.parametrize("name", sorted(_GETTERS))
def test_every_list_getter_pages_both_server_pages(name):
    with patch("src.calm.client._get", _two_page_get()):
        rows = _GETTERS[name]()
    # 100 (page one) + 1 (page two) — the 101st row proves the getter followed
    # the nextLink instead of returning only the first server page.
    assert len(rows) == 101, f"{name} returned {len(rows)} rows — not paging past page one"
