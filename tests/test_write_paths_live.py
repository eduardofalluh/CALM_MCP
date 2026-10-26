"""Write paths fixed after running every tool live (2026-10-26).

Each was only mock-tested before and SAP answered 400 when actually called:

- timeboxes create: SAP requires "type" (0 milestone, 1 phase, 2 sprint);
- solution_processes create: SAP requires the business process;
- test steps (in a test case create, or added later): SAP requires a non-empty
  description, expectedResult, isEvidenceRequired, sequence — and parent_ID
  when a step is added on its own;
- test_case_links create: CALM links a test case to a requirement as a task
  assignment (taskId + parentTestCase_ID), not a reference;
- test case force delete: the action lives in the ExternalTestCaseServiceAPI
  namespace;
- calm_api_read: a non-JSON answer ($metadata XML) is returned as text;
- task_tags update: CALM silently drops an undefined tag — now reported.

The request bodies asserted here are the ones verified live. No network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client  # noqa: E402
from src.calm.tools import unified  # noqa: E402

BASE = "https://x.alm.cloud.sap"
P_UUID = "5e6f7081-92a3-4b4c-8d5e-6f708192a3b4"
TC_UUID = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
ACT_UUID = "0b9bd0e8-d926-4385-b292-2e42c4f12bdd"
REQ_UUID = "8192a3b4-c5d6-4e7f-8091-a2b3c4d5e6f7"


class Ctx:
    """No request_context — credentials come from env."""


@pytest.fixture
def calm(monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", "tok")
    monkeypatch.setenv("CALM_BASE_URL", BASE)
    monkeypatch.setenv("CALM_ENABLE_WRITES", "true")
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    from fastmcp import FastMCP

    mcp = FastMCP("t")
    unified.register(mcp)
    return asyncio.run(mcp.get_tool("calm_resource")).fn


def _echo(method, url, token, body, **kw):
    return {"id": "new-id", "uuid": "new-id", **body}


# --------------------------------------------------------------------------- #
# Timeboxes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("given, code", [(None, 2), ("Sprint", 2), ("sprints", 2), ("Phase", 1),
                                         ("milestone", 0), (1, 1), ("0", 0)])
def test_timebox_create_always_sends_a_type(given, code):
    with patch.object(client, "_write", side_effect=_echo) as w:
        client.create_timebox("tok", P_UUID, name="Sprint 9", timebox_type=given,
                              start_date="2026-11-02T00:00:00Z", end_date="13 November 2026", base_url=BASE)
    body = w.call_args.args[3]
    assert body["type"] == code and body["startDate"] == "2026-11-02" and body["endDate"] == "2026-11-13"


def test_unknown_timebox_type_is_refused():
    with patch.object(client, "_write") as w, pytest.raises(ValueError, match="sprint, phase or milestone"):
        client.create_timebox("tok", P_UUID, name="X", timebox_type="Quarter", base_url=BASE)
    w.assert_not_called()


def test_timebox_type_can_be_given_as_type(calm):
    with patch.object(client, "create_timebox", return_value={"id": "tb"}) as m:
        calm(Ctx(), resource="timeboxes", operation="create", project_id=P_UUID,
             data={"name": "Explore", "type": "phase"})
    assert m.call_args.kwargs["timebox_type"] == "phase"


# --------------------------------------------------------------------------- #
# Solution processes
# --------------------------------------------------------------------------- #

def test_solution_process_without_its_business_process_is_refused_before_writing():
    with patch.object(client, "_write") as w, pytest.raises(ValueError, match="business_process_id is required"):
        client.create_solution_process("tok", "SP", base_url=BASE)
    w.assert_not_called()


def test_solution_process_takes_its_business_process_by_name(calm):
    bps = [{"ID": "bp-1", "Name": "Order to Cash"}, {"ID": "bp-2", "Name": "Procure to Pay"}]
    with patch.object(client, "get_business_processes", return_value=bps), \
         patch.object(client, "_write", side_effect=_echo) as w:
        calm(Ctx(), resource="solution_processes", operation="create",
             data={"name": "SD Sales", "business_process": "order to cash"})
    assert w.call_args.args[3]["businessProcess"] == {"id": "bp-1"}


# --------------------------------------------------------------------------- #
# Test steps
# --------------------------------------------------------------------------- #

def test_test_case_steps_are_completed_as_sap_requires():
    with patch.object(client, "_write", side_effect=_echo) as w:
        client.create_test_case("tok", "TC", project_id=P_UUID, scope_id="sc", base_url=BASE, activities=[
            {"title": "Log in", "steps": [
                {"title": "Open the app", "expected_result": "Login page shows"},
                {"step": "Enter user", "instructions": "Type the test user", "isEvidenceRequired": True}]},
            {"title": "Log out"}])
    acts = w.call_args.args[3]["toActivities"]
    assert [a["sequence"] for a in acts] == [1, 2]
    s1, s2 = acts[0]["toActions"]
    assert s1 == {"title": "Open the app", "description": "Open the app", "expectedResult": "Login page shows",
                  "isEvidenceRequired": False, "sequence": 1}
    assert s2 == {"title": "Enter user", "description": "Type the test user", "expectedResult": "",
                  "isEvidenceRequired": True, "sequence": 2}
    assert "toActions" not in acts[1]


def test_a_step_without_a_title_is_refused():
    with patch.object(client, "_write") as w, pytest.raises(ValueError, match="needs a title"):
        client.create_test_case("tok", "TC", scope_id="sc", base_url=BASE,
                                activities=[{"title": "A", "toActions": [{"description": "x"}]}])
    w.assert_not_called()


def test_a_step_added_on_its_own_names_its_activity_and_goes_last():
    existing = {"value": [{"sequence": 1}, {"sequence": 3}]}
    with patch.object(client, "_get", return_value=existing) as g, \
         patch.object(client, "_write", side_effect=_echo) as w:
        client.create_test_action("tok", ACT_UUID, "Check totals", base_url=BASE)
    assert g.call_args.args[0] == f"{BASE}/api/calm-testmanagement/v1/Activities/{ACT_UUID}/toActions?$select=sequence"
    assert w.call_args.args[1] == f"{BASE}/api/calm-testmanagement/v1/Activities/{ACT_UUID}/toActions"
    assert w.call_args.args[3] == {"title": "Check totals", "description": "Check totals", "expectedResult": "",
                                   "isEvidenceRequired": False, "sequence": 4, "parent_ID": ACT_UUID}


def test_test_action_create_takes_camel_case_fields(calm):
    with patch.object(client, "create_test_action", return_value={"uuid": "a"}) as m:
        calm(Ctx(), resource="test_actions", operation="create", resource_id=ACT_UUID,
             data={"title": "S", "expectedResult": "OK", "instructions": "Do", "isEvidenceRequired": True})
    kw = m.call_args.kwargs
    assert kw["expected_result"] == "OK" and kw["description"] == "Do" and kw["is_evidence_required"] is True


# --------------------------------------------------------------------------- #
# Test case -> requirement link; force delete
# --------------------------------------------------------------------------- #

def test_link_is_a_task_assignment_on_the_test_case():
    stored = {"uuid": "ta", "parentTestCase_ID": TC_UUID, "taskId": REQ_UUID, "taskDisplayId": "3-61798",
              "type": "CALMREQU"}
    with patch.object(client, "_write", return_value=stored) as w:
        out = client.link_test_case_to_requirement("tok", TC_UUID, REQ_UUID, base_url=BASE)
    assert w.call_args.args[:2] == ("POST", f"{BASE}/api/calm-testmanagement/v1/ManualTestCases/{TC_UUID}/toTaskAssignments")
    assert w.call_args.args[3] == {"taskId": REQ_UUID, "parentTestCase_ID": TC_UUID}
    assert out == {"Test Case ID": TC_UUID, "Task ID": REQ_UUID, "Task Display ID": "3-61798",
                   "Type": "CALMREQU", "Linked": True}


def test_force_delete_calls_the_services_own_action():
    with patch.object(client, "_write", return_value={}) as w:
        assert client.delete_test_case("tok", TC_UUID, force=True, base_url=BASE) == {"deleted": TC_UUID, "force": True}
    assert w.call_args.args[1] == (f"{BASE}/api/calm-testmanagement/v1/ManualTestCases/{TC_UUID}/"
                                   "api.v1.ExternalTestCaseServiceAPI.forceDeletionIncludingTestRunsAndResults")


# --------------------------------------------------------------------------- #
# calm_api_read on a non-JSON answer
# --------------------------------------------------------------------------- #

def test_api_read_returns_xml_as_text():
    resp = MagicMock(status_code=200, text="<edmx:Edmx/>")
    resp.json.side_effect = ValueError("Expecting value")
    with patch.object(client.http_retry, "send", return_value=resp):
        assert client.api_read("tok", "/api/calm-testmanagement/v1/$metadata", base_url=BASE) == "<edmx:Edmx/>"


def test_other_reads_still_refuse_a_non_json_answer():
    resp = MagicMock(status_code=200, text="<html/>")
    resp.json.side_effect = ValueError("Expecting value")
    with patch.object(client.http_retry, "send", return_value=resp), pytest.raises(ValueError):
        client._get(f"{BASE}/api/calm-tasks/v1/tasks", "tok")


# --------------------------------------------------------------------------- #
# Tags CALM drops
# --------------------------------------------------------------------------- #

def test_a_tag_calm_dropped_is_reported(calm):
    task = {"ID": REQ_UUID, "Display ID": "3-1", "Tags": ["Scope: Baseline"]}
    with patch.object(client, "get_tags", side_effect=RuntimeError("HTTP 403")), \
         patch.object(client, "set_task_tags", return_value={"ok": True}), \
         patch.object(client, "get_task", return_value=task):
        out = calm(Ctx(), resource="task_tags", operation="update", project_id=P_UUID, resource_id=REQ_UUID,
                   data={"tags": ["Scope:Baseline", "Tshirt size: XXL"]})
    assert out["Tags"] == ["Scope: Baseline"] and out["ok"] is True
    assert "Tshirt size: XXL" in out["Not Written"]["tags"] and "Scope:Baseline" not in out["Not Written"]["tags"]


def test_tags_that_stuck_are_just_returned(calm):
    with patch.object(client, "set_task_tags", return_value={"ok": True}), \
         patch.object(client, "get_task", return_value={"ID": REQ_UUID, "Display ID": "3-1", "Tags": ["Scope: Baseline"]}):
        out = calm(Ctx(), resource="task_tags", operation="update", resource_id=REQ_UUID,
                   data={"tags": ["Scope: Baseline"]})
    assert out["Tags"] == ["Scope: Baseline"] and "Not Written" not in out
