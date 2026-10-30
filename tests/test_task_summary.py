"""Tests for server-side task filtering and summaries (summarize_by).

A production trace showed the sprint-planning question failing in the Studio
front end: the agent listed a project's 301 tasks, the result was too large to
survive the agent's context trimming, and its fallback (calm_api_read with
OData $filter/$select on the REST Tasks API) returned HTTP 400. The fix computes
the table on the server: filter by timebox / team, group with summarize_by, and
return exact counts and effort sums in one small result.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client  # noqa: E402


def row(i, team, sprint, effort, type_="Project Task", status="Open"):
    return {
        "ID": f"t{i}", "Title": f"Task {i}", "Type": type_, "Status": status, "Effort": effort,
        "Responsible Team": team, "Responsible Team ID": None if team is None else f"id-{team}",
        "Timebox": sprint, "Timebox ID": None if sprint is None else f"tb-{sprint}",
        "AssigneeName": None,
    }


ROWS = [
    row(1, "Consulting - Finance", "Sprint 1", 8.0),
    row(2, "Consulting - Finance", "Sprint 1", 4.0),
    row(3, "Consulting  - ABAP", "Sprint 2", 16.0),   # CALM's real double space
    row(4, "Consulting - Finance", "Sprint 10", 2.0),
    row(5, None, "Sprint 1", None),                   # no team, no effort
    row(6, "Consulting - OTC", "Explore", 3.0),
    row(7, "Consulting - OTC", None, "5"),            # effort as a string
    row(8, "Business - PTP", "Sprint 2", 1.5, type_="Sub-task"),
]


# --------------------------------------------------------------------------- #
# filter_tasks
# --------------------------------------------------------------------------- #

def test_no_filter_returns_rows_unchanged():
    assert client.filter_tasks(ROWS) is ROWS


def test_filter_by_sprint_name_case_insensitive():
    assert [r["ID"] for r in client.filter_tasks(ROWS, timebox="sprint 1")] == ["t1", "t2", "t5"]


def test_filter_by_several_sprints():
    got = client.filter_tasks(ROWS, timebox=["Sprint 1", "Sprint 2"])
    assert [r["ID"] for r in got] == ["t1", "t2", "t3", "t5", "t8"]


def test_filter_by_sprint_id():
    assert [r["ID"] for r in client.filter_tasks(ROWS, timebox="tb-Sprint 10")] == ["t4"]


def test_filter_by_team_ignores_spacing():
    assert [r["ID"] for r in client.filter_tasks(ROWS, team="Consulting - ABAP")] == ["t3"]


def test_filter_team_and_sprint_together():
    got = client.filter_tasks(ROWS, timebox="Sprint 1", team="Consulting - Finance")
    assert [r["ID"] for r in got] == ["t1", "t2"]


def test_filter_never_matches_unassigned_by_accident():
    assert client.filter_tasks(ROWS, team="None") == []


# --------------------------------------------------------------------------- #
# summarize_tasks
# --------------------------------------------------------------------------- #

def test_summary_by_sprint_and_team_is_exact():
    s = client.summarize_tasks(client.filter_tasks(ROWS, timebox=["Sprint 1", "Sprint 2", "Sprint 10"]),
                               ["Timebox", "Responsible Team"])
    assert s["Grouped By"] == ["Timebox", "Responsible Team"]
    assert s["Groups"] == [
        {"Timebox": "Sprint 1", "Responsible Team": "Consulting - Finance", "Tasks": 2, "Effort": 12.0, "Tasks Without Effort": 0},
        {"Timebox": "Sprint 1", "Responsible Team": "(none)", "Tasks": 1, "Effort": 0.0, "Tasks Without Effort": 1},
        {"Timebox": "Sprint 2", "Responsible Team": "Business - PTP", "Tasks": 1, "Effort": 1.5, "Tasks Without Effort": 0},
        {"Timebox": "Sprint 2", "Responsible Team": "Consulting  - ABAP", "Tasks": 1, "Effort": 16.0, "Tasks Without Effort": 0},
        {"Timebox": "Sprint 10", "Responsible Team": "Consulting - Finance", "Tasks": 1, "Effort": 2.0, "Tasks Without Effort": 0},
    ]
    assert (s["Total Tasks"], s["Total Effort"], s["Tasks Without Effort"]) == (6, 31.5, 1)


def test_sprints_sort_naturally_and_unassigned_last():
    s = client.summarize_tasks(ROWS, "Timebox")
    assert [g["Timebox"] for g in s["Groups"]] == ["Explore", "Sprint 1", "Sprint 2", "Sprint 10", "(none)"]


def test_numeric_string_effort_is_summed():
    s = client.summarize_tasks(client.filter_tasks(ROWS, team="Consulting - OTC"), "Responsible Team")
    assert s["Groups"] == [{"Responsible Team": "Consulting - OTC", "Tasks": 2, "Effort": 8.0, "Tasks Without Effort": 0}]


def test_totals_match_the_rows():
    s = client.summarize_tasks(ROWS, ["Type"])
    assert s["Total Tasks"] == len(ROWS) == sum(g["Tasks"] for g in s["Groups"])
    assert s["Total Effort"] == pytest.approx(sum(g["Effort"] for g in s["Groups"]))


def test_summary_of_nothing():
    s = client.summarize_tasks([], "Timebox")
    assert s["Groups"] == [] and s["Total Tasks"] == 0 and s["Total Effort"] == 0


@pytest.mark.parametrize("bad", [None, [], "Sprint", ["Timebox", "Title"]])
def test_unknown_group_field_is_rejected(bad):
    with pytest.raises(ValueError, match="summarize_by must be one or more of"):
        client.summarize_tasks(ROWS, bad)


def test_summary_is_small_compared_with_the_rows():
    big = [row(i, f"Team {i % 9}", f"Sprint {i % 3 + 1}", 8.0) for i in range(300)]
    summary = client.summarize_tasks(big, ["Timebox", "Responsible Team"])
    assert len(json.dumps(summary)) < len(json.dumps(big)) / 10


# --------------------------------------------------------------------------- #
# calm_resource wiring
# --------------------------------------------------------------------------- #

class Ctx:
    """No request_context — credentials come from env."""


@pytest.fixture
def fn(monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", "tok")
    monkeypatch.setenv("CALM_BASE_URL", "https://x.alm.cloud.sap")
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("t")
    register(mcp)
    return asyncio.run(mcp.get_tool("calm_resource")).fn


def test_plain_list_is_unchanged(fn):
    with patch("src.calm.client.get_tasks", return_value=list(ROWS)) as m:
        out = fn(Ctx(), resource="tasks", operation="list", project_id="p1")
    assert out == ROWS
    m.assert_called_once_with("p1", "tok", "https://x.alm.cloud.sap", task_type=None, tag=None)


def test_list_with_filters_and_summary(fn):
    with patch("src.calm.client.get_tasks", return_value=list(ROWS)) as m:
        out = fn(Ctx(), resource="tasks", operation="list", project_id="p1", task_type="Project Task",
                 data={"timebox": ["Sprint 1", "Sprint 2"], "summarize_by": ["Timebox", "Responsible Team"]})
    m.assert_called_once_with("p1", "tok", "https://x.alm.cloud.sap", task_type="Project Task", tag=None)
    assert out["Total Tasks"] == 5 and out["Total Effort"] == 29.5


def test_list_with_filter_only_returns_rows(fn):
    with patch("src.calm.client.get_tasks", return_value=list(ROWS)):
        out = fn(Ctx(), resource="tasks", operation="list", project_id="p1", data={"team": "Consulting - OTC"})
    assert [r["ID"] for r in out] == ["t6", "t7"]


# --------------------------------------------------------------------------- #
# calm_api_read hint for the exact failure in the trace
# --------------------------------------------------------------------------- #

def _api_read(monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", "tok")
    monkeypatch.setenv("CALM_BASE_URL", "https://x.alm.cloud.sap")
    from fastmcp import FastMCP

    from src.calm.tools.advanced_write import register

    mcp = FastMCP("t")
    register(mcp)
    return asyncio.run(mcp.get_tool("calm_api_read")).fn


def _sap_400(message: str) -> RuntimeError:
    return RuntimeError("CALM API error: HTTP 400 Bad Request at https://x/api/calm-tasks/v1/tasks — response: "
                        + json.dumps({"message": message}))


def test_api_read_tasks_filter_error_is_an_answer_with_a_hint(monkeypatch):
    read = _api_read(monkeypatch)
    err = _sap_400("Required request parameter 'projectId' for method parameter type UUID is not present")
    with patch("src.calm.client.api_read", side_effect=err):
        got = read("api/calm-tasks/v1/tasks", Ctx(), params={"$filter": "projectId eq x"})
    assert got["status"] == "invalid_request" and "HTTP 400" in got["message"]
    assert "summarize_by" in got["hint"]


def test_api_read_drops_top_sap_does_not_support(monkeypatch):
    # Langfuse 2026-10-30: the Tasks API answered 400 'Query parameter "$top" is not supported yet.'
    read = _api_read(monkeypatch)
    rows = [{"id": "T1"}, {"id": "T2"}]
    with patch("src.calm.client.api_read",
               side_effect=[_sap_400('Query parameter "$top" is not supported yet.'), rows]) as m:
        got = read("api/calm-tasks/v1/tasks", Ctx(), params={"projectId": "P1", "$top": 1000})
    assert m.call_args.kwargs["params"] == {"projectId": "P1"}
    assert got["Ignored Parameters"] == ["$top"] and got["Result"] == rows
    assert "complete answer" in got["Note"]


def test_api_read_drops_each_unsupported_option_in_turn(monkeypatch):
    read = _api_read(monkeypatch)
    with patch("src.calm.client.api_read",
               side_effect=[_sap_400('Query parameter "$top" is not supported yet.'),
                            _sap_400('Query parameter "$skip" is not supported yet.'), []]) as m:
        got = read("api/calm-tasks/v1/tasks", Ctx(), params={"projectId": "P1", "$top": 5, "$skip": 5})
    assert m.call_count == 3 and m.call_args.kwargs["params"] == {"projectId": "P1"}
    assert got["Ignored Parameters"] == ["$top", "$skip"]


def test_api_read_never_drops_filter(monkeypatch):
    # Leaving $filter out would answer a different question: say so instead.
    read = _api_read(monkeypatch)
    with patch("src.calm.client.api_read",
               side_effect=_sap_400('Query parameter "$filter" is not supported yet.')) as m:
        got = read("api/calm-tasks/v1/tasks", Ctx(), params={"projectId": "P1", "$filter": "status eq 'x'"})
    assert m.call_count == 1
    assert got["status"] == "invalid_request" and "calm_resource" in got["hint"]


def test_api_read_404_is_an_answer(monkeypatch):
    read = _api_read(monkeypatch)
    with patch("src.calm.client.api_read", side_effect=RuntimeError("CALM API error: HTTP 404 Not Found")):
        got = read("api/calm-projects/v1/projects/x", Ctx())
    assert got["status"] == "not_found" and "api/calm-projects/v1/projects/x" in got["message"]


def test_api_read_outage_still_fails(monkeypatch):
    read = _api_read(monkeypatch)
    with patch("src.calm.client.api_read", side_effect=RuntimeError("CALM API error: HTTP 503 Service Unavailable")):
        with pytest.raises(RuntimeError, match="503"):
            read("api/calm-projects/v1/projects", Ctx())
