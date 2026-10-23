"""Regression tests for the findings of the stx deep review of f4430a1..191cc16.

One test (or a few) per confirmed finding, so each fix stays fixed:

- pagination: a later page failing is reported as a truncation, not silent;
- CALM_TOKEN never goes to a request that names its own tenant;
- task rows gain the fields CALM fills but the MCP dropped (priority, scope,
  workstream, assigned role, created / last changed), and ``fields`` trims rows;
- summaries label unresolved names, report filter values with no tasks, and
  validate summarize_by before reading; a filter typo on a list is an error;
- team/sprint name lookups run as one short best-effort attempt;
- rich-text cleanup keeps "<placeholder>" text in plain-text steps;
- features reads answer a missing scope with a structured "unavailable";
- solution processes carry their parent business process ID.
Everything runs against mocks — no network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client, http_retry  # noqa: E402

BASE = "https://x.alm.cloud.sap"


class Ctx:
    """No request_context — credentials come from env."""


@pytest.fixture
def calm(monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", "tok")
    monkeypatch.setenv("CALM_BASE_URL", BASE)
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("t")
    register(mcp)
    return asyncio.run(mcp.get_tool("calm_resource")).fn


# --------------------------------------------------------------------------- #
# Pagination: a failing later page is a truncation, not a silent complete list
# --------------------------------------------------------------------------- #

def _page(n, start=0):
    return {"value": [{"id": f"r{i}"} for i in range(start, start + n)]}


def test_later_page_failure_is_reported_as_truncated():
    sink, token = client.install_truncation_sink()
    try:
        with patch("src.calm.client._get", side_effect=[_page(100), RuntimeError("SAP Cloud ALM did not respond")]):
            rows = client._get_all(f"{BASE}/api/calm-testmanagement/v1/ManualTestCases", "tok")
    finally:
        client.reset_truncation_sink(token)
    assert len(rows) == 100
    assert sink and sink[0]["limit"] == "page-error" and "PARTIAL" in sink[0]["message"]


def test_endpoint_without_skip_support_stays_silent():
    sink, token = client.install_truncation_sink()
    try:
        with patch("src.calm.client._get", side_effect=[_page(100), RuntimeError("CALM API error: HTTP 400 Bad Request")]):
            rows = client._get_all(f"{BASE}/api/x", "tok")
    finally:
        client.reset_truncation_sink(token)
    assert len(rows) == 100 and sink == []


# --------------------------------------------------------------------------- #
# CALM_TOKEN must never be sent to a header-chosen tenant
# --------------------------------------------------------------------------- #

class _Req:
    def __init__(self, headers):
        self.headers = headers


class _HeaderCtx:
    def __init__(self, headers):
        self.request_context = type("RC", (), {"request": _Req(headers)})()


def test_calm_token_is_not_used_for_a_request_naming_its_own_tenant(monkeypatch):
    from src.calm.dependencies import get_calm_headers

    monkeypatch.setenv("CALM_TOKEN", "server-static-token")
    monkeypatch.setenv("CALM_BASE_URL", BASE)
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("CALM_MULTI_TENANT", raising=False)
    ctx = _HeaderCtx({"x-calm-base-url": "https://attacker.example.com"})
    with pytest.raises(ValueError):
        get_calm_headers(ctx)


def test_calm_token_still_works_without_tenant_headers(monkeypatch):
    from src.calm.dependencies import get_calm_headers

    monkeypatch.setenv("CALM_TOKEN", "server-static-token")
    monkeypatch.setenv("CALM_BASE_URL", BASE)
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    h = get_calm_headers(Ctx())
    assert h.token == "server-static-token" and h.base_url == BASE


# --------------------------------------------------------------------------- #
# Task rows: previously dropped fields + fields selection
# --------------------------------------------------------------------------- #

RAW = {
    "id": "t1", "displayId": "3-1", "title": "Configure GL", "type": "CALMTASK", "status": "CIPTKOPEN",
    "effort": 8.0, "tags": [], "responsibleTeamId": None, "timeboxId": None,
    "priorityId": 20, "scopeId": "s1", "scopeName": "Finance", "workstream": "WS006",
    "assignedRoleName": "Consultant", "createdTimestamp": "2026-07-01T10:00:00Z",
    "lastChangedTimestamp": "2026-10-20T08:00:00Z",
}


def test_previously_dropped_fields_are_returned():
    row = client._format_task(RAW)
    assert (row["Priority"], row["Scope ID"], row["Scope"], row["Workstream"], row["Assigned Role"],
            row["Created"], row["Last Changed"]) == (
        "High", "s1", "Finance", "WS006", "Consultant", "2026-07-01T10:00:00Z", "2026-10-20T08:00:00Z")


def test_unknown_priority_code_passes_through():
    assert client._format_task({**RAW, "priorityId": 99})["Priority"] == 99
    assert client._format_task({**RAW, "priorityId": None})["Priority"] is None


def test_select_task_fields_keeps_id_and_only_the_requested_fields():
    rows = [client._format_task(RAW)]
    assert client.select_task_fields(rows, ["Title", "Priority"]) == [{"ID": "t1", "Title": "Configure GL", "Priority": "High"}]
    with pytest.raises(ValueError, match="fields must be one or more of"):
        client.select_task_fields(rows, ["Title", "Nope"])


def test_fields_option_through_calm_resource(calm):
    with patch("src.calm.client.get_tasks", return_value=[client._format_task(RAW)]):
        out = calm(Ctx(), resource="tasks", operation="list", project_id="p1", data={"fields": ["Scope"]})
    assert out == [{"ID": "t1", "Scope": "Finance"}]


# --------------------------------------------------------------------------- #
# Summaries and filters
# --------------------------------------------------------------------------- #

def _row(i, team=None, team_id=None, sprint=None, sprint_id=None, effort=1.0, scope="Finance", priority="Medium"):
    return {"ID": f"t{i}", "Responsible Team": team, "Responsible Team ID": team_id, "Timebox": sprint,
            "Timebox ID": sprint_id, "Effort": effort, "Scope": scope, "Scope ID": "s1" if scope else None,
            "Priority": priority, "Type": "Project Task", "Status": "Open", "AssigneeName": None,
            "Workstream": "WS006", "Assigned Role": None}


def test_unresolved_names_are_not_reported_as_unassigned():
    rows = [_row(1, team=None, team_id="team-a", sprint="Sprint 1", sprint_id="tb1"),
            _row(2, team=None, team_id=None, sprint="Sprint 1", sprint_id="tb1")]
    s = client.summarize_tasks(rows, "Responsible Team")
    labels = [g["Responsible Team"] for g in s["Groups"]]
    assert "(unresolved: team-a)" in labels and "(none)" in labels
    assert "Warning" in s and "1 task(s)" in s["Warning"]


def test_summary_by_new_fields():
    rows = [_row(1, priority="High", scope="Finance", effort=2), _row(2, priority="High", scope="OTC", effort=3),
            _row(3, priority="Low", scope="Finance", effort=5)]
    s = client.summarize_tasks(rows, ["Priority", "Scope"])
    assert {(g["Priority"], g["Scope"]): (g["Tasks"], g["Effort"]) for g in s["Groups"]} == {
        ("High", "Finance"): (1, 2.0), ("High", "OTC"): (1, 3.0), ("Low", "Finance"): (1, 5.0)}


def test_unmatched_filter_values_are_reported():
    rows = [_row(1, team="Consulting - Finance", team_id="tf", sprint="Sprint 1", sprint_id="tb1")]
    assert client.unmatched_filters(rows, timebox=["Sprint 1", "Sprnt 2"]) == {
        "timebox": {"no tasks for": ["Sprnt 2"], "values present": ["Sprint 1"]}}
    assert client.unmatched_filters(rows, timebox="sprint 1", team="consulting - finance") == {}


def test_summary_includes_filter_values_with_no_tasks(calm):
    rows = [_row(1, team="Consulting - Finance", team_id="tf", sprint="Sprint 1", sprint_id="tb1")]
    with patch("src.calm.client.get_tasks", return_value=rows):
        out = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                   data={"timebox": ["Sprint 1", "Sprint 3"], "summarize_by": ["Timebox"]})
    assert out["Total Tasks"] == 1
    assert out["Filter Values With No Tasks"]["timebox"]["no tasks for"] == ["Sprint 3"]


def test_list_with_a_typo_is_an_error_naming_the_real_values(calm):
    rows = [_row(1, team="Consulting - Finance", team_id="tf", sprint="Sprint 1", sprint_id="tb1")]
    with patch("src.calm.client.get_tasks", return_value=rows):
        with pytest.raises(ValueError) as err:
            calm(Ctx(), resource="tasks", operation="list", project_id="p1", data={"timebox": "Sprnt 1"})
    assert "Sprnt 1" in str(err.value) and "Sprint 1" in str(err.value)


def test_list_filter_with_some_matches_returns_them(calm):
    rows = [_row(1, sprint="Sprint 1", sprint_id="tb1"), _row(2, sprint="Sprint 2", sprint_id="tb2")]
    with patch("src.calm.client.get_tasks", return_value=rows):
        out = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                   data={"timebox": ["Sprint 2", "Sprint 9"]})
    assert [r["ID"] for r in out] == ["t2"]


@pytest.mark.parametrize("bad", [[], ["Title"], "Sprint"])
def test_summarize_by_is_validated_before_reading(calm, bad):
    with patch("src.calm.client.get_tasks") as m:
        with pytest.raises(ValueError, match="summarize_by must be one or more of"):
            calm(Ctx(), resource="tasks", operation="list", project_id="p1", data={"summarize_by": bad})
    m.assert_not_called()


def test_fields_are_validated_before_reading(calm):
    with patch("src.calm.client.get_tasks") as m:
        with pytest.raises(ValueError, match="fields must be one or more of"):
            calm(Ctx(), resource="tasks", operation="list", project_id="p1", data={"fields": ["Bogus"]})
    m.assert_not_called()


# --------------------------------------------------------------------------- #
# Best-effort name lookups
# --------------------------------------------------------------------------- #

def test_name_lookups_are_single_short_attempts():
    budgets = []

    def teams(*a, **kw):
        budgets.append(http_retry._budget.get())
        return [{"ID": "tf", "Name": "Consulting - Finance"}]

    with patch("src.calm.client._get_all", return_value=[{**RAW, "responsibleTeamId": "tf"}]), \
         patch("src.calm.client.get_project_teams", teams):
        rows = client.get_tasks("p1", "tok", BASE)
    assert rows[0]["Responsible Team"] == "Consulting - Finance"
    assert budgets == [(1, http_retry.BEST_EFFORT_TIMEOUT)]
    assert http_retry._budget.get() is None  # restored for the rest of the call


# --------------------------------------------------------------------------- #
# Rich text, features, solution processes, analytics message
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("given, expected", [
    ("Enter <Company Code> and save", "Enter <Company Code> and save"),
    ("<p>Enter &lt;Plant&gt;</p>", "Enter <Plant>"),
    ("<p>Press <b>Save</b></p><ul><li>A</li><li>B</li></ul>", "Press Save\n- A\n- B"),
    ("Line 1<br/>Line 2", "Line 1\nLine 2"),
])
def test_rich_text_keeps_placeholders(given, expected):
    assert client._rich_text_to_plain(given) == expected


@pytest.mark.parametrize("resource, fn, kw", [
    ("features", "get_features", {"project_id": "p1"}),
    ("feature_status", "get_feature_status", {}),
    ("feature_priorities", "get_feature_priorities", {}),
])
def test_features_without_scope_answer_structured(calm, resource, fn, kw):
    with patch(f"src.calm.client.{fn}", side_effect=RuntimeError("CALM API error: HTTP 403 Forbidden")):
        out = calm(Ctx(), resource=resource, operation="list", **kw)
    assert out["status"] == "unavailable" and "calm-api.features.read" in out["message"]


def test_features_server_error_still_raises(calm):
    with patch("src.calm.client.get_features", side_effect=RuntimeError("CALM API error: HTTP 500")):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            calm(Ctx(), resource="features", operation="list", project_id="p1")


def test_analytics_features_message_names_the_scope(calm):
    with patch("src.calm.client.get_analytics", side_effect=RuntimeError("CALM API error: HTTP 403")):
        out = calm(Ctx(), resource="analytics", operation="list", data={"provider": "DP_FEATURES"})
    assert "DP_FEATURES calm-api.features.read" in out["message"]
    assert "DP_TASKS and DP_PROJECTS work with the standard" in out["message"]


def test_solution_process_carries_its_business_process_id():
    raw = [{"id": "sp1", "name": "Sell", "businessProcess": {"id": "bp9", "uri": "/x"}},
           {"id": "sp2", "name": "Orphan", "businessProcess": None}]
    with patch("src.calm.client._get_all", return_value=raw):
        rows = client.get_solution_processes("tok", BASE)
    assert [r["Business Process ID"] for r in rows] == ["bp9", None]


def test_test_case_rows_carry_last_changed():
    row = client._format_test_case({"uuid": "u1", "title": "T", "priorityCode": 30, "modifiedAt": "2026-10-20T08:00:00Z"})
    assert row["Last Changed"] == "2026-10-20T08:00:00Z"
    assert list(row)[:-1] == ["ID", "Display ID", "Project ID", "Scope ID", "Solution Process ID",
                              "Title", "Prepared", "Priority", "Tags"]  # existing fields unchanged, in order
