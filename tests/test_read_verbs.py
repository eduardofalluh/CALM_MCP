"""Every read verb an agent naturally uses must work — never "use list instead".

Production trace (2026-10-26, project agent): ``calm_resource(resource=
"requirements", operation="get", project_id=..., resource_id="3-60729")`` failed
with "Use operation='list' with project_id to get requirements, then filter by
ID". The agent sometimes recovered by listing and sometimes surfaced a tool
error — the "works sometimes" users reported. The same refusal existed for
projects, business/solution processes, timeboxes, scopes, tags, teams, test
plans, feature value help, analytics, team roles, customization, task tags,
test activities/actions and test case links. Each is now served from the read
the MCP already does. Everything runs against mocks — no network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client  # noqa: E402

BASE = "https://x.alm.cloud.sap"
PROJECT = "5e6f7081-92a3-4b4c-8d5e-6f708192a3b4"
REQ_UUID = "6f708192-a3b4-4c5d-9e6f-708192a3b4c5"


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


def _req(i, display, title, **kw):
    r = {"ID": f"req-{i}", "Display ID": display, "External ID (FRICEF)": None, "Title": title,
         "Type": "Requirement", "Status": "Open"}
    r.update(kw)
    return r


REQS = [_req(1, "3-60728", "Payroll interface"), _req(2, "3-60729", "Cost center reporting",
                                                        **{"External ID (FRICEF)": "FIN-R-12"})]


# --------------------------------------------------------------------------- #
# The traced call
# --------------------------------------------------------------------------- #

def test_requirement_get_by_display_id_the_traced_call(calm):
    with patch.object(client, "get_tasks", return_value=REQS) as gt:
        row = calm(Ctx(), resource="requirements", operation="get", project_id=PROJECT,
                   resource_id="3-60729")
    assert row["ID"] == "req-2" and row["Title"] == "Cost center reporting"
    assert gt.call_args.kwargs["task_type"] == "Requirement"


def test_requirement_get_by_external_id_or_title(calm):
    with patch.object(client, "get_tasks", return_value=REQS):
        assert calm(Ctx(), resource="requirements", operation="get", project_id=PROJECT,
                    resource_id="fin-r-12")["ID"] == "req-2"
        assert calm(Ctx(), resource="requirements", operation="get", project_id=PROJECT,
                    resource_id="payroll  interface")["ID"] == "req-1"


def test_requirement_get_by_uuid_reads_it_directly(calm):
    with patch.object(client, "get_task", return_value=REQS[0]) as g, \
         patch.object(client, "get_tasks") as gt:
        assert calm(Ctx(), resource="requirements", operation="get", resource_id=REQ_UUID) == REQS[0]
    assert g.call_args.args[1] == REQ_UUID
    gt.assert_not_called()


def test_requirement_get_not_found_is_an_answer_not_a_tool_error(calm):
    with patch.object(client, "get_tasks", return_value=REQS):
        out = calm(Ctx(), resource="requirements", operation="get", project_id=PROJECT, resource_id="3-1")
    assert out["status"] == "not_found" and out["found"] is False and out["requested"] == "3-1"
    assert "3-1" in out["message"] and "search" in out["hint"]
    assert "Use operation" not in out["message"]


def test_requirement_get_by_display_id_needs_the_project(calm):
    with pytest.raises(ValueError, match="project_id is required"):
        calm(Ctx(), resource="requirements", operation="get", resource_id="3-60729")


def test_ambiguous_name_asks_for_the_id(calm):
    twins = [_req(1, "3-1", "Same"), _req(2, "3-2", "Same")]
    with patch.object(client, "get_tasks", return_value=twins):
        out = calm(Ctx(), resource="requirements", operation="get", project_id=PROJECT, resource_id="same")
    assert out["status"] == "ambiguous" and [m["ID"] for m in out["matches"]] == ["req-1", "req-2"]
    assert "pass the ID" in out["message"]


# --------------------------------------------------------------------------- #
# get on list-only resources: one row from the same list
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("resource, fn, rows, ident, kw", [
    ("projects", "get_projects", [{"ID": "P1", "Name": "Alpha"}, {"ID": "P2", "Name": "Beta"}], "beta", {}),
    ("business_processes", "get_business_processes", [{"ID": "BP1", "Name": "Order to Cash"}], "BP1", {}),
    ("solution_processes", "get_solution_processes", [{"ID": "SP1", "Name": "SD Sales"}], "sd sales", {}),
    ("timeboxes", "get_timeboxes", [{"ID": "TB1", "Name": "Sprint 4"}], "Sprint 4", {"project_id": "P1"}),
    ("scopes", "get_scopes", [{"ID": "S1", "Name": "Wave 1", "Project ID": "P1"}], "wave 1", {"project_id": "P1"}),
    ("teams", "get_project_teams", [{"ID": "T1", "Name": "Finance"}], "finance", {"project_id": "P1"}),
])
def test_get_on_list_only_resources(calm, resource, fn, rows, ident, kw):
    with patch.object(client, fn, return_value=rows):
        out = calm(Ctx(), resource=resource, operation="get", resource_id=ident, **kw)
    assert out == next(r for r in rows if ident.lower() in (r["ID"].lower(), r["Name"].lower()))


def test_processes_get_searches_both_kinds(calm):
    with patch.object(client, "get_business_processes", return_value=[{"ID": "BP1", "Name": "O2C"}]), \
         patch.object(client, "get_solution_processes", return_value=[{"ID": "SP1", "Name": "SD Sales"}]):
        assert calm(Ctx(), resource="processes", operation="get", resource_id="SP1")["Name"] == "SD Sales"
    with pytest.raises(ValueError, match="business_processes"):
        calm(Ctx(), resource="processes", operation="create", data={"name": "x"})


def test_feature_value_help_get_by_code(calm):
    statuses = [{"Code": "IN_REALIZATION", "Name": "In Realization"}, {"Code": "DONE", "Name": "Done"}]
    with patch.object(client, "get_feature_status", return_value=statuses):
        assert calm(Ctx(), resource="feature_status", operation="get", resource_id="done") == statuses[1]
        assert calm(Ctx(), resource="feature_status", operation="get") == statuses
    with patch.object(client, "get_feature_priorities", return_value=[{"Code": "20", "Name": "High"}]):
        assert calm(Ctx(), resource="feature_priorities", operation="get", resource_id="High")["Code"] == "20"


def test_tags_and_project_users_get_keep_the_unavailable_answer(calm):
    with patch.object(client, "get_tags", side_effect=RuntimeError("HTTP 403 Forbidden")):
        out = calm(Ctx(), resource="tags", operation="get", project_id="P1", resource_id="Scope: Baseline")
    assert out["status"] == "unavailable"
    with patch.object(client, "get_project_users", side_effect=RuntimeError("HTTP 403 Forbidden")):
        out = calm(Ctx(), resource="project_users", operation="get", project_id="P1", resource_id="x@y.com")
    assert out["status"] == "unavailable"
    users = [{"ID": "U1", "Email": "jane@example.com", "Name": "Jane"}]
    with patch.object(client, "get_project_users", return_value=users):
        assert calm(Ctx(), resource="project_users", operation="get", project_id="P1",
                    resource_id="JANE@example.com") == users[0]


# --------------------------------------------------------------------------- #
# The other read verb is the same read
# --------------------------------------------------------------------------- #

def test_customization_list_equals_get(calm):
    with patch.object(client, "get_project_customization", return_value={"Workstreams": ["A"]}):
        assert calm(Ctx(), resource="customization", operation="list", project_id="P1") == {"Workstreams": ["A"]}


def test_analytics_and_team_roles_get_equals_list(calm):
    with patch.object(client, "get_analytics", return_value=[{"statusText": "Open"}]) as ga:
        assert calm(Ctx(), resource="analytics", operation="get", project_id="P1") == [{"statusText": "Open"}]
    assert ga.call_args.kwargs["provider"] == "DP_TASKS"
    with patch.object(client, "get_team_roles", return_value=[{"Role Name": "Consultant"}]):
        assert calm(Ctx(), resource="team_roles", operation="get", resource_id="T1") == [{"Role Name": "Consultant"}]


# --------------------------------------------------------------------------- #
# Sub-entities read through their parent
# --------------------------------------------------------------------------- #

def test_task_tags_read(calm):
    task = {"ID": "t1", "Display ID": "3-5", "Title": "Configure GL", "Tags": ["SIT", "OCM"]}
    with patch.object(client, "get_task", return_value=task):
        out = calm(Ctx(), resource="task_tags", operation="get", project_id="P1", resource_id="3-5")
    assert out == {"Task ID": "t1", "Display ID": "3-5", "Title": "Configure GL", "Tags": ["SIT", "OCM"]}


TEST_CASE = {"ID": "tc1", "Display ID": "8-1-1380", "Title": "Boundary test",
             "Activities": [{"Activity": 1, "Title": "Log on"}],
             "Steps": [{"Step": "1.1", "Action": "Log on"}],
             "Linked Tasks": [{"Task ID": "r1", "Task Display ID": "3-55", "Type": "CALMREQU"}]}


@pytest.mark.parametrize("resource, key", [
    ("test_activities", "Activities"), ("test_actions", "Steps"), ("test_case_links", "Linked Tasks"),
])
def test_test_case_children_read_through_the_test_case(calm, resource, key):
    with patch.object(client, "get_test_case", return_value=TEST_CASE) as g:
        for op in ("get", "list"):
            out = calm(Ctx(), resource=resource, operation=op, resource_id="8-1-1380")
            assert out[key] == TEST_CASE[key] and out["Display ID"] == "8-1-1380"
    assert g.call_args.args[1] == "8-1-1380"


def test_test_case_children_wrong_id_explains_what_to_pass(calm):
    with patch.object(client, "get_test_case", side_effect=ValueError("No test case with display ID 'act-1'.")), \
         pytest.raises(ValueError, match="read through their test case"):
        calm(Ctx(), resource="test_actions", operation="get", resource_id="act-1")


# --------------------------------------------------------------------------- #
# 2026-10-26 trace 2: "3-60729" is a User Story, asked for as a requirement
# --------------------------------------------------------------------------- #

STORY = {"ID": "story-1", "Display ID": "3-70001", "External ID (FRICEF)": None,
         "Title": "As a planner I want...", "Type": "User Story", "Status": "Open"}


def test_requirement_get_returns_the_item_when_it_is_another_type(calm):
    def tasks(project_id, token, base_url, task_type=None, tag=None):
        return REQS if task_type == "Requirement" else REQS + [STORY]
    with patch.object(client, "get_tasks", side_effect=tasks):
        out = calm(Ctx(), resource="requirements", operation="get", project_id=PROJECT,
                   resource_id="3-70001")
    assert out["ID"] == "story-1" and out["Type"] == "User Story"
    assert out["Note"] == "3-70001 is a User Story, not a Requirement."


def test_requirement_get_by_uuid_of_another_type_says_so(calm):
    with patch.object(client, "get_task", return_value=STORY):
        out = calm(Ctx(), resource="requirements", operation="get", resource_id=REQ_UUID)
    assert out["Note"].endswith("is a User Story, not a Requirement.")


def test_real_requirement_has_no_note(calm):
    with patch.object(client, "get_tasks", return_value=REQS):
        out = calm(Ctx(), resource="requirements", operation="get", project_id=PROJECT, resource_id="3-60729")
    assert "Note" not in out


@pytest.mark.parametrize("resource, kw, patch_target, effect", [
    ("tasks", {"resource_id": REQ_UUID}, "_get", RuntimeError("HTTP 404 Not Found")),
    ("tasks", {"resource_id": "3-9", "project_id": PROJECT}, "get_tasks", lambda *a, **k: REQS),
    ("test_cases", {"resource_id": "8-1-9"}, "_get", lambda *a, **k: {"value": []}),
    ("test_cases", {"resource_id": REQ_UUID}, "_get", RuntimeError("HTTP 404 Not Found")),
    ("projects", {"resource_id": "Nope"}, "get_projects", lambda *a, **k: [{"ID": "P1", "Name": "Alpha"}]),
])
def test_every_read_miss_is_an_answer(calm, resource, kw, patch_target, effect):
    side = effect if callable(effect) else None
    with patch.object(client, patch_target, side_effect=side if side else effect):
        out = calm(Ctx(), resource=resource, operation="get", **kw)
    assert out["status"] == "not_found" and out["found"] is False


def test_documents_read_miss_is_an_answer(calm, monkeypatch):
    from src.calm import odata_service
    sets = {"Documents": {"name": "Documents", "type": "Documents", "key": ["uuid"],
                          "props": {"uuid": {"type": "Edm.Guid"}, "displayId": {"type": "Edm.String"},
                                    "projectId": {"type": "Edm.Guid"}}, "navs": {}}}
    monkeypatch.setattr(odata_service, "schema", lambda *a, **k: sets)
    with patch.object(client, "_get_all", return_value=[]):
        out = calm(Ctx(), resource="documents", operation="get", resource_id="7-999")
    assert out["status"] == "not_found"


def test_writes_on_a_missing_item_still_fail(calm, monkeypatch):
    monkeypatch.setenv("CALM_ENABLE_WRITES", "true")
    with patch.object(client, "get_tasks", return_value=REQS), patch.object(client, "update_task") as ut, \
         pytest.raises(client.NotFound):
        calm(Ctx(), resource="requirements", operation="update", project_id=PROJECT,
             resource_id="3-404", data={"title": "x"})
    ut.assert_not_called()


def test_not_found_is_still_a_value_error_for_existing_callers():
    assert issubclass(client.NotFound, ValueError) and issubclass(client.Ambiguous, ValueError)
