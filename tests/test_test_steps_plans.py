"""Tests for test-case step reads, test plans and the DP_TESTS analytics guidance.

Covers three additive capabilities, all read-only:

- ``client.get_test_case`` — one test case with its step tree
  (``toActivities($expand=toActions)``), addressable by UUID or display ID,
  numbered 1.1 / 1.2 … like the CALM UI, rich text flattened to plain text.
- ``client.get_test_plans`` / ``get_test_plan`` — read from CALM's test analytics
  (DP_TESTS): SAP's Test Plans API answers on no tenant (live 2026-11-09), the
  analytics rows carry each test case's plan, plan status, dates and result.
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

import re

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
# client.get_test_plans / get_test_plan — from CALM's test analytics
# --------------------------------------------------------------------------- #

def _t(pid, pname, plan, pstatus, tid, tname, result, tag=None, tester="t1"):
    return {"Provider": "DP_TESTS", "Snapshot": "20261108", "projectGUID": pid, "project": pname,
            "testPlan": plan, "testPlanStatus": pstatus, "testPlanStartDate": "2026-11-01",
            "testPlanEndDate": None, "testcaseId": tid, "testcaseName": tname, "status": result,
            "type": "Manual", "priority": "High", "process": "(Not Assigned)", "scopeName": "S1",
            "tag": tag, "testerId": tester, "Metrics": {"total": "1"}}


DP_TESTS_ROWS = [
    _t("p1", "Project One", "SIT Cycle 1", "In Testing", "tc1", "Login", "Passed", tag="A"),
    _t("p1", "Project One", "SIT Cycle 1", "In Testing", "tc1", "Login", "Passed", tag="B"),  # same test, 2nd tag
    _t("p1", "Project One", "SIT Cycle 1", "In Testing", "tc2", "Order", "Failed"),
    _t("p1", "Project One", "SIT Cycle 1", "In Testing", "tc3", "Invoice", "Initial"),
    _t("p1", "Project One", "SIT Cycle 1", "In Testing", "tc3", "Invoice", "In Progress", tester="t2"),  # 2nd tester
    _t("p2", "Project Two", "UAT Cycle 1", "In Preparation", "tc9", "Payroll", "Initial"),
    _t("p1", "Project One", "(None)", None, "tc7", "Loose test", "Failed"),  # in no plan
]


def _plans(**kw):
    with patch("src.calm.client.get_analytics", return_value=DP_TESTS_ROWS) as ga:
        out = client.get_test_plans(TOKEN, BASE_URL, **kw)
    ga.assert_called_once_with(TOKEN, provider="DP_TESTS", base_url=BASE_URL)
    return out


def test_test_plans_come_from_test_analytics_each_test_case_counted_once():
    out = _plans()
    assert out == [
        {"Test Plan": "SIT Cycle 1", "Project": "Project One", "Project ID": "p1", "Status": "In Testing",
         "Start Date": "2026-11-01", "End Date": None, "Test Cases": 3, "Test Runs": 4,
         "Results": {"Failed": 1, "In Progress": 1, "Initial": 1, "Passed": 1}, "As Of": "2026-11-08"},
        {"Test Plan": "UAT Cycle 1", "Project": "Project Two", "Project ID": "p2", "Status": "In Preparation",
         "Start Date": "2026-11-01", "End Date": None, "Test Cases": 1, "Test Runs": 1, "Results": {"Initial": 1},
         "As Of": "2026-11-08"},
    ]  # tc1's two tag rows count once; tc3 has two testers = two runs, each result kept; tc7 is in no plan


@pytest.mark.parametrize("project", ["p1", "project one", "Project One"])
def test_test_plans_project_filter_by_id_or_name(project):
    assert [p["Test Plan"] for p in _plans(project_id=project)] == ["SIT Cycle 1"]


def test_one_test_plan_lists_every_run_with_its_result_and_tags():
    with patch("src.calm.client.get_analytics", return_value=DP_TESTS_ROWS):
        out = client.get_test_plan(TOKEN, "sit cycle 1", BASE_URL)
        partial = client.get_test_plan(TOKEN, "SIT", BASE_URL)
    assert out == partial and out["Test Cases"] == 3 and out["Test Runs"] == 4
    assert [(c["Test Case"], c["Tester ID"], c["Result"], c["Tags"]) for c in out["Test Runs List"]] == [
        ("Order", "t1", "Failed", []), ("Invoice", "t2", "In Progress", []), ("Invoice", "t1", "Initial", []),
        ("Login", "t1", "Passed", ["A", "B"])]


def test_an_unknown_or_ambiguous_test_plan_says_so():
    with patch("src.calm.client.get_analytics", return_value=DP_TESTS_ROWS):
        with pytest.raises(client.NotFound, match="SIT Cycle 1, UAT Cycle 1"):
            client.get_test_plan(TOKEN, "Regression", BASE_URL)
        with pytest.raises(client.Ambiguous, match="SIT Cycle 1 .*UAT Cycle 1"):
            client.get_test_plan(TOKEN, "cycle 1", BASE_URL)


def test_test_plans_propagate_http_errors_to_caller():
    with patch("src.calm.client.get_analytics", side_effect=RuntimeError("HTTP 403 Forbidden")):
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
    _refused(_fn()(Ctx(), resource="test_cases", operation="get"), "resource_id is required for get")


def test_resource_list_test_cases_unchanged():
    with patch("src.calm.client.get_test_cases", return_value=[]) as m:
        _fn()(Ctx(), resource="test_cases", operation="list", project_id="p1",
              data={"tag": "SIT", "title_contains": "login"})
    m.assert_called_once_with(TOKEN, BASE_URL, tag="SIT", project_id="p1", title_contains="login")


def test_resource_test_plans_list_routes_with_project():
    with patch("src.calm.client.get_test_plans", return_value=[]) as m:
        _fn()(Ctx(), resource="test_plans", operation="list", project_id="p1")
    m.assert_called_once_with(TOKEN, BASE_URL, project_id="p1")


def test_resource_test_plans_get_routes_by_name():
    with patch("src.calm.client.get_test_plan", return_value={"Test Plan": "SIT"}) as m:
        out = _fn()(Ctx(), resource="test_plans", operation="get", resource_id="SIT")
    assert out == {"Test Plan": "SIT"}
    m.assert_called_once_with(TOKEN, "SIT", BASE_URL, project_id=None)


@pytest.mark.parametrize("status", ["HTTP 403", "HTTP 401", "HTTP 404"])
def test_resource_test_plans_missing_access_names_the_scopes_that_matter(status):
    with patch("src.calm.client.get_test_plans", side_effect=RuntimeError(f"{status} denied")):
        out = _fn()(Ctx(), resource="test_plans", operation="list")
    assert out["status"] == "unavailable"
    assert "calm-api.analytics.read" in out["message"] and "calm-api.tests.read" in out["message"]
    assert "testplans.read" not in out["message"]  # it isn't what SAP checks: plans come from analytics


def test_resource_test_plans_server_error_is_not_swallowed():
    with patch("src.calm.client.get_test_plans", side_effect=RuntimeError("HTTP 500 boom")):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            _fn()(Ctx(), resource="test_plans", operation="list")


def test_resource_test_plans_get_returns_one_plan_or_says_not_found():
    with patch("src.calm.client.get_analytics", return_value=DP_TESTS_ROWS):
        one = _fn()(Ctx(), resource="test_plans", operation="get", resource_id="uat cycle 1")
        missing = _fn()(Ctx(), resource="test_plans", operation="get", resource_id="p9")
    assert one["Test Plan"] == "UAT Cycle 1" and one["Test Runs List"][0]["Test Case"] == "Payroll"
    assert missing["status"] == "not_found" and "No test plan named 'p9'" in missing["message"]


@pytest.mark.parametrize("op", ["create", "update", "delete"])
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


def _refused(out, match=""):
    """A read the MCP can't run as asked: an answer saying why, not a tool error."""
    assert isinstance(out, dict) and out.get("status") == "invalid_request", out
    assert re.search(match, out["message"]), out["message"]
    return out["message"]
