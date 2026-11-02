"""Every calm_resource list filters, counts and pages server-side, with a Check.

Before 2026-11-02 most lists (test cases, teams, scopes, processes, features …)
silently ignored the data an agent passed: data={"status": "Failed"} on test
cases returned every test case, and any count was left to the agent, which
counts a trimmed copy of a long list. Now every data key a list doesn't read
itself filters on that field (or is refused naming the fields); summarize_by
counts on the server; and every such answer carries a Check.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class Ctx:
    """No request_context — credentials come from env."""


@pytest.fixture
def calm(monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", "tok")
    monkeypatch.setenv("CALM_BASE_URL", "https://x.alm.cloud.sap")
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("t")
    register(mcp)
    return asyncio.run(mcp.get_tool("calm_resource")).fn


CASES = [
    {"ID": "tc1", "Display ID": "8-1-1", "Title": "Order to cash", "Status": "Failed", "Priority": "High",
     "Tags": ["SIT"], "Last Changed": "2026-10-01T10:00:00Z"},
    {"ID": "tc2", "Display ID": "8-1-2", "Title": "Procure to pay", "Status": "Failed", "Priority": "Low",
     "Tags": ["SIT", "UAT"], "Last Changed": "2026-10-02T10:00:00Z"},
    {"ID": "tc3", "Display ID": "8-1-3", "Title": "Record to report", "Status": "Passed", "Priority": "High",
     "Tags": [], "Last Changed": "2026-10-02T11:00:00Z"},
]


def _cases(calm, **data):
    with patch("src.calm.client.get_test_cases", return_value=CASES) as gt:
        out = calm(Ctx(), resource="test_cases", operation="list", project_id="p1", data=data)
    return out, gt


def test_a_filter_is_applied_not_ignored(calm):
    out, gt = _cases(calm, status="failed", tag="SIT")
    assert gt.call_args.kwargs["tag"] == "SIT"  # the list's own option still goes to SAP
    assert out["Total Matching"] == 2 and [r["ID"] for r in out["Items"]] == ["tc1", "tc2"]
    assert out["Filters"] == {"Status": "failed"}
    assert out["Check"] == {"Rows Read": 3, "Matched": 2, "Returned": 2, "Not Returned": 0}


def test_counts_are_made_by_the_server(calm):
    out, _ = _cases(calm, summarize_by=["Status", "Priority"])
    assert out["Total"] == 3 and out["Check"]["Groups Add Up"] is True
    assert {(g["Status"], g["Priority"], g["Count"]) for g in out["Groups"]} == {
        ("Failed", "High", 1), ("Failed", "Low", 1), ("Passed", "High", 1)}


def test_lists_dates_and_unset_values_match(calm):
    out, _ = _cases(calm, filter={"Tags": "uat"}, summarize_by="Status")
    assert out["Total"] == 1
    out, _ = _cases(calm, filter={"Last Changed": "2026-10-02"}, summarize_by="Status")
    assert out["Total"] == 2
    out, _ = _cases(calm, filter={"Tags": None}, summarize_by="Status")
    assert out["Total"] == 1


def test_a_value_nobody_has_is_said_not_counted_as_zero(calm):
    out, _ = _cases(calm, status="Faild")
    assert out["status"] == "invalid_request" and "Failed" in out["message"] and "Passed" in out["message"]
    out, _ = _cases(calm, status="Faild", summarize_by="Status")
    assert out["Total"] == 0
    assert out["Filter Values With No Items"]["Status"]["values present"] == ["Failed", "Passed"]


def test_an_unknown_field_is_refused_with_the_fields(calm):
    out, _ = _cases(calm, colour="red")
    assert out["status"] == "invalid_request" and "Priority" in out["message"]


def test_top_and_fields(calm):
    out, _ = _cases(calm, top=1, fields=["Title"])
    assert out["Items"] == [{"Title": "Order to cash"}]
    assert out["Total Matching"] == 3 and out["Check"]["Not Returned"] == 2


def test_plain_list_is_unchanged(calm):
    out, _ = _cases(calm)
    assert out == CASES


def test_other_lists_too_and_empty_lists(calm):
    teams = [{"ID": "T1", "Name": "Finance"}, {"ID": "T2", "Name": "Logistics"}]
    with patch("src.calm.client.get_project_teams", return_value=teams):
        out = calm(Ctx(), resource="teams", operation="list", project_id="p1", data={"name": "finance"})
    assert out["Total Matching"] == 1 and out["Items"][0]["ID"] == "T1"
    with patch("src.calm.client.get_project_teams", return_value=[]):
        out = calm(Ctx(), resource="teams", operation="list", project_id="p1",
                   data={"name": "finance", "summarize_by": "Name"})
    assert out["Total"] == 0 and out["Check"]["Rows Read"] == 0


def test_odata_list_keeps_its_own_filters_and_gains_summarize(calm):
    docs = [{"ID": "d1", "Status": "Draft"}, {"ID": "d2", "Status": "Draft"}]
    with patch("src.calm.odata_service.list_rows", return_value=docs) as lr:
        out = calm(Ctx(), resource="documents", operation="list", project_id="p1",
                   data={"type": "Spec", "summarize_by": "Status"})
    assert lr.call_args.kwargs["data"] == {"type": "Spec"}
    assert out["Groups"] == [{"Status": "Draft", "Count": 2}] and out["Check"]["Groups Add Up"]


def test_an_answer_that_is_not_rows_says_what_was_not_applied(calm):
    unavailable = {"status": "unavailable", "message": "no scope"}
    with patch("src.calm.client.get_test_cases", return_value=unavailable):
        out = calm(Ctx(), resource="test_cases", operation="list", project_id="p1",
                   data={"summarize_by": "Status"})
    assert out["status"] == "unavailable" and "summarize_by" in out["Not Applied"]


def test_sub_item_list_takes_its_parent_from_data(calm):
    comments = [{"ID": "c1", "Text": "hi"}]
    with patch("src.calm.client.get_task", return_value={"ID": "t-1"}), \
            patch("src.calm.client.get_task_comments", return_value=comments) as gc:
        out = calm(Ctx(), resource="task_comments", operation="list", data={"id": "t-1"})
    assert gc.called and out == comments


# --------------------------------------------------------------------------- #
# Row cap: never a list too long to read or count right (Lutron trace,
# 2026-11-02 15:59: tasks list with only fields -> 7,756 rows -> 23 counted, 25 real)
# --------------------------------------------------------------------------- #

def _tasks(n):
    return [{"ID": f"id-{i}", "Display ID": f"3-{i}", "Title": f"T{i}", "Type": "Project Task" if i % 4 else "Sub-task",
             "Status": "Open" if i % 2 else "Done", "DueDate": "2026-01-01", "AssigneeName": "Person Alpha",
             "AssigneeID": "u-a", "Timebox": None, "Timebox ID": None, "Responsible Team": None,
             "Responsible Team ID": None} for i in range(n)]


def _task_list(calm, rows, **data):
    with patch("src.calm.client.get_tasks", return_value=rows):
        return calm(Ctx(), resource="tasks", operation="list", project_id="p1", data=data)


def test_a_long_task_list_gives_totals_and_counts_not_rows(calm):
    from src.calm.tools.unified import LIST_ROW_LIMIT
    out = _task_list(calm, _tasks(LIST_ROW_LIMIT + 100), fields=["Title", "Status", "Type"])
    assert out["Total Matching"] == LIST_ROW_LIMIT + 100 and out["Returned"] == 0 and "Tasks" not in out
    assert sum(c["Count"] for c in out["Counts"]) == LIST_ROW_LIMIT + 100
    assert {"Type", "Status", "Count"} == set(out["Counts"][0])
    assert "summarize_by" in out["How To Get Rows"] and out["Check"]["Not Returned"] == LIST_ROW_LIMIT + 100


def test_a_short_list_is_unchanged(calm):
    rows = _tasks(5)
    assert _task_list(calm, rows) == rows


def test_paging_with_top_and_skip(calm):
    from src.calm.tools.unified import LIST_ROW_LIMIT
    n = LIST_ROW_LIMIT + 100
    first = _task_list(calm, _tasks(n), top=1000)
    assert first["Returned"] == LIST_ROW_LIMIT and first["Next Skip"] == LIST_ROW_LIMIT
    rest = _task_list(calm, _tasks(n), top=1000, skip=first["Next Skip"])
    assert rest["Returned"] == 100 and "Next Skip" not in rest
    assert rest["Tasks"][0]["ID"] == f"id-{LIST_ROW_LIMIT}"


def test_a_long_filtered_list_keeps_its_exact_total(calm):
    from src.calm.tools.unified import LIST_ROW_LIMIT
    out = _task_list(calm, _tasks(2 * LIST_ROW_LIMIT + 2), status="Open")
    assert out["Total Matching"] == LIST_ROW_LIMIT + 1 and out["Returned"] == 0
    assert out["Check"]["Matched"] == LIST_ROW_LIMIT + 1


def test_any_long_list_is_capped_and_pages(calm):
    from src.calm.tools.unified import LIST_ROW_LIMIT
    cases = [{"ID": f"tc{i}", "Status": "Failed"} for i in range(LIST_ROW_LIMIT + 1)]
    with patch("src.calm.client.get_test_cases", return_value=cases):
        out = calm(Ctx(), resource="test_cases", operation="list", project_id="p1")
        assert out["Total Matching"] == LIST_ROW_LIMIT + 1 and out["Returned"] == 0
        page = calm(Ctx(), resource="test_cases", operation="list", project_id="p1", data={"skip": LIST_ROW_LIMIT})
    assert page["Items"] == [{"ID": f"tc{LIST_ROW_LIMIT}", "Status": "Failed"}] and "Next Skip" not in page


def test_api_read_never_returns_a_list_too_long_to_count(monkeypatch):
    from fastmcp import FastMCP

    from src.calm.tools.advanced_write import register
    from src.calm.tools.unified import LIST_ROW_LIMIT

    monkeypatch.setenv("CALM_TOKEN", "tok")
    monkeypatch.setenv("CALM_BASE_URL", "https://x.alm.cloud.sap")
    mcp = FastMCP("t")
    register(mcp)
    read = asyncio.run(mcp.get_tool("calm_api_read")).fn
    rows = [{"id": i} for i in range(LIST_ROW_LIMIT + 1)]
    with patch("src.calm.client.api_read", return_value=rows):
        out = read("api/calm-tasks/v1/tasks", Ctx(), params={"projectId": "p1"})
    assert out["Total Rows"] == LIST_ROW_LIMIT + 1 and out["Returned"] == 0 and "summarize_by" in out["hint"]
    with patch("src.calm.client.api_read", return_value={"value": rows[:100]}):
        assert read("api/x/v1/Things", Ctx(), params={"$top": 100}) == {"value": rows[:100]}


# --------------------------------------------------------------------------- #
# Analytics: one row per task x tag x workstream -> rollups count a task once
# --------------------------------------------------------------------------- #

def _an(task, tag, status="Open", sp="3"):
    return {"Provider": "DP_TASKS", "taskGUID": task, "taskID": task, "tag": tag, "statusText": status,
            "Metrics": {"counter": "1", "storyPoints": sp, "effort": "2.00"}}


ANALYTICS = [_an("t1", "SIT"), _an("t1", "UAT"), _an("t2", "SIT", "Done", "5"), _an("t3", None, "Done", "8")]


def _analytics(calm, **data):
    with patch("src.calm.client.get_analytics", return_value=list(ANALYTICS)) as ga:
        return calm(Ctx(), resource="analytics", operation="list", project_id="p1", data=data), ga


def test_analytics_rollup_counts_each_task_once(calm):
    out, _ = _analytics(calm, summarize_by="statusText")
    groups = {g["statusText"]: g for g in out["Groups"]}
    assert groups["Open"]["Items"] == 1 and groups["Open"]["Rows"] == 2 and groups["Open"]["storyPoints"] == 3
    assert groups["Done"]["Items"] == 2 and groups["Done"]["storyPoints"] == 13
    assert out["Total Items"] == 3 and out["Totals"]["storyPoints"] == 16 and out["Totals"]["effort"] == 6
    assert out["Check"] == {"Rows Read": 4, "Distinct Items": 3, "Counted By": "taskGUID"}


def test_analytics_rollup_by_tag_counts_a_task_in_each_of_its_tags(calm):
    out, _ = _analytics(calm, summarize_by="TAG")
    assert {(g["tag"], g["Items"]) for g in out["Groups"]} == {("SIT", 2), ("UAT", 1), ("(none)", 1)}
    assert out["Total Items"] == 3


def test_analytics_pages_and_refuses_unknown_dimensions(calm):
    out, ga = _analytics(calm, top=2, skip=1)
    assert ga.call_args.kwargs["top"] == 3 and len(out) == 3  # mock ignores top; the slice starts at skip
    out, _ = _analytics(calm, summarize_by="colour")
    assert out["status"] == "invalid_request" and "statusText" in out["message"]


def test_odata_shaped_answer_is_capped_too(calm):
    from src.calm.tools.unified import LIST_ROW_LIMIT
    docs = {"Total Matching": LIST_ROW_LIMIT + 5, "Returned": LIST_ROW_LIMIT + 5,
            "Documents": [{"ID": f"d{i}", "Status": "Draft"} for i in range(LIST_ROW_LIMIT + 5)]}
    with patch("src.calm.odata_service.list_rows", return_value=docs):
        out = calm(Ctx(), resource="documents", operation="list", project_id="p1", data={"top": 1000})
    assert out["Returned"] == 0 and "Documents" not in out and out["Total Matching"] == LIST_ROW_LIMIT + 5
