"""Tests for test-case step reads, test plans and the DP_TESTS analytics guidance.

Covers three additive capabilities, all read-only:

- ``client.get_test_case`` — one test case with its step tree
  (``toActivities($expand=toActions)``), addressable by UUID or display ID,
  numbered 1.1 / 1.2 … like the CALM UI, rich text flattened to plain text.
- ``client.get_test_plans`` — plan entity set discovered from the Test
  Management service document; structured ``unavailable`` when absent.
- ``calm_resource`` wiring for both, plus the analytics 403 message naming
  calm-api.tests.read for DP_TESTS.

Also pins the existing list formatter so the new detail read can never change
what ``operation="list"`` returns. Everything runs against mocks — no network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client  # noqa: E402

TOKEN = "test-token-12345"
BASE_URL = "https://test.calm.cloud.sap"
TC_UUID = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"

LIST_KEYS = {
    "ID", "Display ID", "Project ID", "Scope ID", "Solution Process ID",
    "Title", "Prepared", "Priority", "Tags", "Last Changed",
}


def _raw_case(**over):
    """A ManualTestCases payload as CALM returns it with the detail $expand."""
    item = {
        "uuid": TC_UUID,
        "displayId": "8-1-1380",
        "projectId": "p1",
        "scopeId": "s1",
        "solutionProcessId": None,
        "title": "FRICEW 112 - License history boundary values",
        "isPrepared": True,
        "priorityCode": 30,
        "toTagAssignments": [{"label": "SIT"}],
        # Deliberately out of order: numbering must follow `sequence`, not API order.
        "toActivities": [
            {
                "uuid": "act-2", "title": "Create equipment", "sequence": 20, "isInScope": True,
                "toActions": [
                    {"uuid": "a-2-2", "title": "Save", "sequence": 2,
                     "description": "<p>Press <b>Save</b>.</p>",
                     "expectedResult": "<p>Equipment saved.</p>", "isEvidenceRequired": True},
                    {"uuid": "a-2-1", "title": "Enter license", "sequence": 1,
                     "description": "<p>Enter License Number &amp; plate</p><ul><li>ABCD123456</li></ul>",
                     "expectedResult": "Value accepted<br/>without truncation",
                     "isEvidenceRequired": False},
                ],
            },
            {
                "uuid": "act-1", "title": "Log on", "sequence": 10, "isInScope": True,
                "toActions": [
                    {"uuid": "a-1-1", "title": "Log on", "sequence": 1,
                     "description": "Log on as Equipment Administrator.",
                     "expectedResult": "Launchpad opens."},
                ],
            },
        ],
    }
    item.update(over)
    return item


# --------------------------------------------------------------------------- #
# client.get_test_case
# --------------------------------------------------------------------------- #

def _get_case(test_case_id, payload):
    calls = []

    def fake_get(url, token):
        calls.append(url)
        return payload

    with patch("src.calm.client._get", fake_get):
        out = client.get_test_case(TOKEN, test_case_id, BASE_URL)
    return calls, out


def test_get_by_uuid_uses_key_path_and_full_expand():
    calls, out = _get_case(TC_UUID, _raw_case())
    assert len(calls) == 1
    url = calls[0]
    assert url.startswith(f"{BASE_URL}/api/calm-testmanagement/v1/ManualTestCases/{TC_UUID}?")
    assert "$expand=toTagAssignments,toTaskAssignments,toActivities($expand=toActions)" in url
    assert "$filter" not in url
    assert out["Display ID"] == "8-1-1380"


def test_get_by_display_id_filters_server_side():
    calls, out = _get_case("8-1-1380", {"value": [_raw_case()]})
    url = calls[0]
    assert url.startswith(f"{BASE_URL}/api/calm-testmanagement/v1/ManualTestCases?")
    assert "$expand=toTagAssignments,toTaskAssignments,toActivities($expand=toActions)" in url
    assert "$filter=displayId%20eq%20%278-1-1380%27" in url
    assert out["ID"] == TC_UUID


def test_display_id_quotes_are_escaped():
    calls, _ = _get_case("8-1-'x", {"value": [_raw_case()]})
    # A single quote inside the literal is doubled ('' -> %27%27).
    assert "%278-1-%27%27x%27" in calls[0]


def test_display_id_not_found_raises_clear_error():
    with pytest.raises(ValueError, match="No test case with display ID '9-9-9'"):
        _get_case("9-9-9", {"value": []})


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_missing_id_raises(bad):
    with pytest.raises(ValueError, match="test_case_id is required"):
        client.get_test_case(TOKEN, bad, BASE_URL)


def test_steps_numbered_by_sequence_like_the_ui():
    _, out = _get_case(TC_UUID, _raw_case())
    assert [s["Step"] for s in out["Steps"]] == ["1.1", "2.1", "2.2"]
    # Activity 1 is the lower sequence (10 "Log on"), not the first in the payload.
    assert out["Steps"][0]["Activity"] == "Log on"
    step_1_2 = out["Steps"][1]
    assert (step_1_2["Activity"], step_1_2["Action"]) == ("Create equipment", "Enter license")
    assert step_1_2["Action ID"] == "a-2-1"
    assert step_1_2["Activity ID"] == "act-2"
    assert out["Steps"][2]["Evidence Required"] is True


def test_rich_text_flattened_to_plain_text():
    _, out = _get_case(TC_UUID, _raw_case())
    enter = out["Steps"][1]
    assert enter["Instructions"] == "Enter License Number & plate\n- ABCD123456"
    assert enter["Expected Result"] == "Value accepted\nwithout truncation"
    assert out["Steps"][2]["Instructions"] == "Press Save."


def test_activities_summary():
    _, out = _get_case(TC_UUID, _raw_case())
    assert out["Activities"] == [
        {"Activity": 1, "ID": "act-1", "Title": "Log on", "In Scope": True, "Action Count": 1},
        {"Activity": 2, "ID": "act-2", "Title": "Create equipment", "In Scope": True, "Action Count": 2},
    ]


def test_execution_results_note_names_the_scope_and_ui_limit():
    _, out = _get_case(TC_UUID, _raw_case())
    note = out["Execution Results"]
    assert "DP_TESTS" in note and "calm-api.tests.read" in note
    assert "not exposed" in note


def test_detail_keeps_every_list_field_identical():
    """The detail is a strict superset: list fields are produced by the SAME
    formatter, so nothing an existing agent prompt relies on changes."""
    raw = _raw_case()
    _, out = _get_case(TC_UUID, raw)
    listed = client._format_test_case(raw)
    for key, value in listed.items():
        assert out[key] == value
    assert set(out) == LIST_KEYS | {"Activities", "Steps", "Execution Results", "Linked Tasks"}


def test_case_without_steps_returns_empty_tree():
    _, out = _get_case(TC_UUID, _raw_case(toActivities=None))
    assert out["Activities"] == [] and out["Steps"] == []
    _, out = _get_case(TC_UUID, _raw_case(toActivities=[
        {"uuid": "act-x", "title": "Empty", "sequence": 1, "toActions": []},
    ]))
    assert out["Activities"][0]["Action Count"] == 0 and out["Steps"] == []


def test_missing_sequence_and_non_dict_rows_are_tolerated():
    _, out = _get_case(TC_UUID, _raw_case(toActivities=[
        "garbage",
        {"uuid": "act-b", "title": "No seq", "toActions": [{"title": "x"}]},
        {"uuid": "act-a", "title": "Has seq", "sequence": 5, "toActions": [{"title": "y", "description": None}]},
    ]))
    # Sequenced rows first, unsequenced after; None text stays None.
    assert [a["Title"] for a in out["Activities"]] == ["Has seq", "No seq"]
    assert out["Steps"][0]["Instructions"] is None


# --------------------------------------------------------------------------- #
# The list read must be untouched
# --------------------------------------------------------------------------- #

def test_list_formatter_output_unchanged():
    row = client._format_test_case(_raw_case())
    assert set(row) == LIST_KEYS
    assert "Steps" not in row and "Activities" not in row


def test_list_query_unchanged():
    captured = {}

    def fake_get(url, token):
        captured["url"] = url
        return {"value": [_raw_case()]}

    with patch("src.calm.client._get", fake_get):
        rows = client.get_test_cases(TOKEN, BASE_URL)
    assert captured["url"] == f"{BASE_URL}/api/calm-testmanagement/v1/ManualTestCases?$expand=toTagAssignments"
    assert set(rows[0]) == LIST_KEYS


# --------------------------------------------------------------------------- #
# client.get_test_plans
# --------------------------------------------------------------------------- #

SERVICE_DOC_NO_PLANS = {"value": [
    {"name": "ManualTestCases", "url": "ManualTestCases"},
    {"name": "Activities", "url": "Activities"},
    {"name": "Actions", "url": "Actions"},
]}


def test_test_plans_unavailable_when_service_has_no_plan_set():
    calls = []

    def fake_get(url, token):
        calls.append(url)
        return SERVICE_DOC_NO_PLANS

    with patch("src.calm.client._get", fake_get), \
         patch("src.calm.client._get_all", side_effect=AssertionError("must not page")):
        out = client.get_test_plans(TOKEN, BASE_URL)
    assert calls == [f"{BASE_URL}/api/calm-testmanagement/v1/"]
    assert out["status"] == "unavailable" and out["resource"] == "test_plans"
    assert "calm-api.testplans.read" in out["message"]
    assert out["available_entity_sets"] == ["ManualTestCases", "Activities", "Actions"]


@pytest.fixture(autouse=True)
def fresh_entity_set_cache():
    client._TM_ENTITY_SETS.clear()
    yield
    client._TM_ENTITY_SETS.clear()


def _plans(doc, rows, **kw):
    paged = []

    def fake_get_all(url, token):
        paged.append(url)
        return rows

    with patch("src.calm.client._get", return_value=doc) as g, \
         patch("src.calm.client._get_all", fake_get_all):
        out = client.get_test_plans(TOKEN, BASE_URL, **kw)
    return out, paged, g


PLAN_DOC = {"value": SERVICE_DOC_NO_PLANS["value"] + [{"name": "TestPlans", "url": "TestPlans"}]}
PLAN_ROWS = [
    {"@odata.etag": "W/1", "uuid": "tp1", "title": "SIT Cycle 1", "projectId": "p1",
     "toTestCases": [{"uuid": "x"}], "details": {"a": 1}, "planType": "SIT"},
    {"uuid": "tp2", "title": "UAT", "projectId": "p2"},
]


def test_test_plans_discovered_and_formatted_like_other_reads():
    out, paged, _ = _plans(PLAN_DOC, PLAN_ROWS)
    assert paged[0] == f"{BASE_URL}/api/calm-testmanagement/v1/TestPlans"
    # Known fields use the Title-Case contract; unknown scalars pass through;
    # @odata annotations and nested navigation/objects are dropped.
    assert out[0] == {"ID": "tp1", "Title": "SIT Cycle 1", "Project ID": "p1", "planType": "SIT"}
    assert len(out) == 2


def test_test_plans_project_filter_is_exact():
    out, *_ = _plans(PLAN_DOC, PLAN_ROWS, project_id="p1")
    assert [p["ID"] for p in out] == ["tp1"]


def test_test_plans_without_project_field_say_they_are_unfiltered():
    out, *_ = _plans(PLAN_DOC, [{"uuid": "tp9", "title": "No project field"}], project_id="p1")
    assert "Warning" in out and out["Test Plans"] == [{"ID": "tp9", "Title": "No project field"}]


def test_test_plans_service_document_read_once_per_tenant():
    _, _, g1 = _plans(PLAN_DOC, PLAN_ROWS)
    _, _, g2 = _plans(PLAN_DOC, PLAN_ROWS)
    assert g1.call_count == 1 and g2.call_count == 0  # second call served from the cache


def test_test_plans_propagates_http_errors_to_caller():
    with patch("src.calm.client._get", side_effect=RuntimeError("HTTP 403 Forbidden")):
        with pytest.raises(RuntimeError, match="HTTP 403"):
            client.get_test_plans(TOKEN, BASE_URL)


# --------------------------------------------------------------------------- #
# calm_resource wiring
# --------------------------------------------------------------------------- #

class Ctx:
    """Minimal context: no request_context, so get_calm_headers falls through to env."""


def _fn():
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("test")
    register(mcp)
    return asyncio.run(mcp.get_tool("calm_resource")).fn


@pytest.fixture(autouse=True)
def read_env(monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", TOKEN)
    monkeypatch.setenv("CALM_BASE_URL", BASE_URL)
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("CALM_ENABLE_WRITES", raising=False)  # reads must not need writes
    yield


def test_resource_get_routes_to_get_test_case():
    with patch("src.calm.client.get_test_case", return_value={"ok": 1}) as m:
        out = _fn()(Ctx(), resource="test_cases", operation="get", resource_id="8-1-1380")
    assert out == {"ok": 1}
    m.assert_called_once_with(TOKEN, "8-1-1380", BASE_URL)


def test_resource_get_requires_resource_id():
    with pytest.raises(ValueError, match="resource_id is required for get"):
        _fn()(Ctx(), resource="test_cases", operation="get")


def test_resource_list_test_cases_unchanged():
    with patch("src.calm.client.get_test_cases", return_value=[]) as m:
        _fn()(Ctx(), resource="test_cases", operation="list", project_id="p1",
              data={"tag": "SIT", "title_contains": "login"})
    m.assert_called_once_with(TOKEN, BASE_URL, tag="SIT", project_id="p1", title_contains="login")


def test_resource_test_plans_list_routes_with_project():
    with patch("src.calm.client.get_test_plans", return_value=[]) as m:
        _fn()(Ctx(), resource="test_plans", operation="list", project_id="p1")
    m.assert_called_once_with(TOKEN, BASE_URL, project_id="p1")


@pytest.mark.parametrize("status", ["HTTP 403", "HTTP 401", "HTTP 404"])
def test_resource_test_plans_scope_missing_is_structured(status):
    with patch("src.calm.client.get_test_plans", side_effect=RuntimeError(f"{status} denied")):
        out = _fn()(Ctx(), resource="test_plans", operation="list")
    assert out["status"] == "unavailable"
    assert "calm-api.testplans.read" in out["message"]


def test_resource_test_plans_server_error_is_not_swallowed():
    with patch("src.calm.client.get_test_plans", side_effect=RuntimeError("HTTP 500 boom")):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            _fn()(Ctx(), resource="test_plans", operation="list")


@pytest.mark.parametrize("op", ["get", "create", "update", "delete"])
def test_resource_test_plans_is_read_only(op):
    with pytest.raises(ValueError, match="not supported for test_plans"):
        _fn()(Ctx(), resource="test_plans", operation=op, resource_id="x", data={"a": 1})


def test_analytics_dp_tests_403_names_the_scope():
    with patch("src.calm.client.get_analytics", side_effect=RuntimeError("HTTP 403 Forbidden")):
        out = _fn()(Ctx(), resource="analytics", operation="list", data={"provider": "DP_TESTS"})
    assert out["status"] == "unavailable" and out["provider"] == "DP_TESTS"
    assert "calm-api.tests.read" in out["message"]


def test_analytics_dp_tests_passes_through_when_granted():
    rows = [{"Provider": "DP_TESTS", "status": "Failed", "testcaseID": "8-1-1380", "Metrics": {"total": 1}}]
    with patch("src.calm.client.get_analytics", return_value=rows) as m:
        out = _fn()(Ctx(), resource="analytics", operation="list", project_id="p1",
                    data={"provider": "DP_TESTS"})
    assert out == rows
    assert m.call_args.kwargs["provider"] == "DP_TESTS"
    assert m.call_args.kwargs["project_id"] == "p1"


def test_test_plans_is_an_advertised_resource():
    import typing

    from src.calm.tools import unified

    fn = _fn()
    resource_type = typing.get_type_hints(fn, globalns=vars(unified))["resource"]
    assert "test_plans" in typing.get_args(resource_type)
    assert "test_cases" in typing.get_args(resource_type)
