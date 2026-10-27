"""calm_resource takes the field names and values agents actually send.

A live replay of realistic agent calls (the call shapes Studio agents and the
calm-mcp-assistant skill use) against the 1520f0d server gave 17 tool errors in
28 calls, plus three silent losses:

- task types / statuses in everyday words ("Task", "Subtask", "Closed") refused;
- the task_type ARGUMENT, a project_id inside data, data.name for a title ignored;
- priority labels and external_id silently dropped on requirement create, and
  priority_id "High" / a datetime due date sent raw (SAP answers 400);
- a requirement update on a user story sent type=Requirement (SAP answers 400);
- a comment sent as data.content posted EMPTY (SAP stores only "text");
- reads with a missing / invalid input, or SAP answering 404, were tool errors.

Writes still refuse what can't be done — before anything is written.
Everything here runs against mocks — no network.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client  # noqa: E402
from src.calm.config import TenantNotConfiguredError  # noqa: E402
from src.calm.tools import unified  # noqa: E402

BASE = "https://x.alm.cloud.sap"
P_UUID = "5e6f7081-92a3-4b4c-8d5e-6f708192a3b4"
T_UUID = "6f708192-a3b4-4c5d-9e6f-708192a3b4c5"
TB_UUID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


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
    """client._write that answers like SAP: the stored item, with an id."""
    return {"id": T_UUID, **body}


# --------------------------------------------------------------------------- #
# Values: types, statuses, priorities, dates in the words agents use
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("given, code", [
    ("Task", "CALMTASK"), ("tasks", "CALMTASK"), ("Project Task", "CALMTASK"), ("PROJECT_TASK", "CALMTASK"),
    ("Subtask", "CALMST"), ("sub-task", "CALMST"), ("Sub tasks", "CALMST"),
    ("story", "CALMUS"), ("User Story", "CALMUS"), ("user_stories", "CALMUS"), ("UserStory", "CALMUS"),
    ("req", "CALMREQU"), ("Requirements", "CALMREQU"), ("bug", "CALMDEF"), ("Defects", "CALMDEF"),
    ("calmus", "CALMUS"), ("Quality Gate", "CALMQGATE"), ("risk", "CALMRISK"),
])
def test_task_types_in_everyday_words(given, code):
    assert client.resolve_task_type_code(given) == code


def test_unknown_task_type_still_lists_the_real_ones():
    with pytest.raises(ValueError, match="Unknown task type 'Epic'.*User Story"):
        client.resolve_task_type_code("Epic")


@pytest.mark.parametrize("given, type_code, code", [
    ("Closed", "CALMTASK", "CIPTKCLOSE"), ("completed", "CALMUS", "CIPUSCLOSE"),
    ("To Do", "CALMREQU", "CIPREQUOPEN"), ("WIP", "CALMTASK", "CIPTKINP"),
    ("in-progress", "CALMUS", "CIPUSINP"), ("n/a", "CALMTASK", "CIPTKNO"),
    ("ciptkopen", "CALMTASK", "CIPTKOPEN"), ("Done", "CALMDEF", "CIPDFCTDONE"),
])
def test_statuses_in_everyday_words(given, type_code, code):
    assert client.resolve_status_code(given, type_code) == code


@pytest.mark.parametrize("given, type_code", [("Paused", "CALMTASK"), ("Not Relevant", "CALMDEF")])
def test_a_status_the_type_does_not_have_is_refused_with_the_allowed_ones(given, type_code):
    with pytest.raises(ValueError, match="Allowed labels"):
        client.resolve_status_code(given, type_code)


@pytest.mark.parametrize("given, code", [
    ("High", 20), ("very high", 10), ("Critical", 10), ("Medium", 30), ("normal", 30), ("Low", 40),
    (20, 20), ("20", 20), (20.0, 20), (50, 50),
])
def test_priorities_as_labels_or_codes(given, code):
    assert client.resolve_priority(given) == code


@pytest.mark.parametrize("given", ["Urgent", True, "", "P1"])
def test_unknown_priority_is_refused(given):
    with pytest.raises(ValueError, match="Very High, High, Medium or Low"):
        client.resolve_priority(given)


@pytest.mark.parametrize("given, iso", [
    ("2026-12-31", "2026-12-31"), ("2026-12-31T00:00:00Z", "2026-12-31"),
    ("2026-12-31T18:30:00+02:00", "2026-12-31"), ("2026/1/5", "2026-01-05"),
    ("31 December 2026", "2026-12-31"), ("Dec 31, 2026", "2026-12-31"), ("  2026-12-31 ", "2026-12-31"),
])
def test_dates_become_what_the_tasks_api_takes(given, iso):
    assert client.api_date(given, "due_date") == iso


@pytest.mark.parametrize("given", ["12/11/2026", "2026-02-30", "next friday", "31.12.26"])
def test_ambiguous_or_invalid_dates_are_refused_not_guessed(given):
    with pytest.raises(ValueError, match="due_date must be a date like 2026-12-31"):
        client.api_date(given, "due_date")


@pytest.mark.parametrize("given", [None, ""])
def test_empty_dates_pass_through(given):
    assert client.api_date(given, "due_date") == given


def test_create_task_sends_codes_and_plain_dates():
    with patch.object(client, "_write", side_effect=_echo) as w:
        row = client.create_task("tok", P_UUID, "T", "Task", status="Closed", priority_id="High",
                                 due_date="2026-12-31T00:00:00Z", start_date="Dec 1, 2026", base_url=BASE)
    body = w.call_args.args[3]
    assert body["type"] == "CALMTASK" and body["status"] == "CIPTKCLOSE" and body["priorityId"] == 20
    assert body["dueDate"] == "2026-12-31" and body["startDate"] == "2026-12-01"
    assert row["Priority"] == "High" and row["Status"] == "Done"


# --------------------------------------------------------------------------- #
# Fields: placement and names
# --------------------------------------------------------------------------- #

def test_tasks_create_takes_the_task_type_argument(calm):
    with patch.object(client, "create_task", return_value={"ID": "t"}) as m:
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID, task_type="Project Task",
             data={"title": "A"})
    assert m.call_args.kwargs["task_type"] == "Project Task"


def test_data_task_type_wins_over_the_argument(calm):
    with patch.object(client, "create_task", return_value={"ID": "t"}) as m:
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID, task_type="Project Task",
             data={"title": "A", "type": "User Story"})
    assert m.call_args.kwargs["task_type"] == "User Story"


def test_tasks_create_without_any_type_says_how_to_give_it(calm):
    with patch.object(client, "create_task") as m, pytest.raises(ValueError, match="task_type argument"):
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID, data={"title": "A"})
    m.assert_not_called()


@pytest.mark.parametrize("resource", ["tasks", "requirements"])
def test_project_id_inside_data_is_used(calm, resource):
    with patch.object(client, "create_task", return_value={"ID": "t"}) as m:
        calm(Ctx(), resource=resource, operation="create",
             data={"project_id": P_UUID, "title": "A", "task_type": "Project Task"})
    assert m.call_args.kwargs["project_id"] == P_UUID


def test_name_is_taken_as_the_title(calm):
    with patch.object(client, "create_task", return_value={"ID": "t"}) as m:
        calm(Ctx(), resource="requirements", operation="create", project_id=P_UUID, data={"name": "Req A"})
    assert m.call_args.kwargs["title"] == "Req A"


def test_title_is_taken_as_the_name_for_named_items(calm):
    with patch.object(client, "create_business_process", return_value={"ID": "bp"}) as m:
        calm(Ctx(), resource="business_processes", operation="create", data={"title": "Order to Cash"})
    assert m.call_args.kwargs["name"] == "Order to Cash"


def test_requirement_create_writes_priority_external_id_and_due_date(calm):
    with patch.object(client, "create_task", return_value={"ID": "r"}) as m:
        calm(Ctx(), resource="requirements", operation="create", project_id=P_UUID,
             data={"title": "A", "priority": "High", "externalId": "FTS-001", "dueDate": "2026-12-31"})
    kw = m.call_args.kwargs
    assert kw["priority_id"] == "High" and kw["external_id"] == "FTS-001"
    assert kw["due_date"] == "2026-12-31" and kw["task_type"] == "Requirement"


def test_a_field_given_twice_with_different_values_is_refused(calm):
    with patch.object(client, "create_task") as m, pytest.raises(ValueError, match="priority_id twice"):
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
             data={"title": "A", "task_type": "Task", "priority": "High", "priority_id": 30})
    m.assert_not_called()


def test_documented_api_fields_at_the_top_level_go_to_extra_fields(calm):
    with patch.object(client, "create_task", return_value={"ID": "t"}) as m:
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
             data={"title": "A", "task_type": "Task", "storyPoints": 5, "custom_field3": "x",
                   "sub_status": "In Specification"})
    assert m.call_args.kwargs["extra_fields"] == {"storyPoints": 5, "customField3": "x",
                                                  "subStatus": "In Specification"}


def test_fields_that_cannot_be_written_are_reported_not_dropped(calm):
    with patch.object(client, "create_task", return_value={"ID": "t", "Title": "A"}) as m:
        out = calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
                   data={"title": "A", "task_type": "Task", "colour": "red", "tags": ["Scope: Baseline"]})
    m.assert_called_once()  # the item is still written with what can be
    assert out["ID"] == "t" and set(out["Not Written"]) == {"colour", "tags"}
    assert "task_tags" in out["Not Written"]["tags"] and "extra_fields" in out["Not Written"]["colour"]


def test_an_update_with_nothing_writable_is_refused_before_writing(calm):
    with patch.object(client, "update_task") as m, pytest.raises(ValueError, match="Nothing to update.*colour"):
        calm(Ctx(), resource="tasks", operation="update", resource_id=T_UUID, data={"colour": "red"})
    m.assert_not_called()


def test_the_item_id_inside_data_is_used(calm):
    with patch.object(client, "update_task", return_value={"ID": T_UUID}) as m:
        calm(Ctx(), resource="tasks", operation="update", data={"id": T_UUID, "title": "B"})
    assert m.call_args.kwargs["task_id"] == T_UUID and m.call_args.kwargs["title"] == "B"


# --------------------------------------------------------------------------- #
# Sprint / team / scope by name
# --------------------------------------------------------------------------- #

SPRINTS = [{"ID": TB_UUID, "Name": "Explore"}, {"ID": "tb-2", "Name": "Realize"}]
TEAMS = [{"ID": "team-1", "Name": "Record-to-Report (R2R)"}]
SCOPES = [{"ID": "scope-1", "Name": "Finance Processes", "Project ID": P_UUID},
          {"ID": "scope-9", "Name": "Finance Processes", "Project ID": "other"}]


def test_sprint_team_and_scope_names_become_their_ids(calm):
    with patch.object(client, "get_timeboxes", return_value=SPRINTS), \
         patch.object(client, "get_project_teams", return_value=TEAMS), \
         patch.object(client, "get_scopes", return_value=SCOPES), \
         patch.object(client, "create_task", return_value={"ID": "r"}) as m:
        calm(Ctx(), resource="requirements", operation="create", project_id=P_UUID,
             data={"title": "A", "sprint": "explore", "responsible_team": "Record-to-Report (R2R)",
                   "scope": "Finance Processes"})
    assert m.call_args.kwargs["extra_fields"] == {"timeboxId": TB_UUID, "responsibleTeamId": "team-1",
                                                  "scopeId": "scope-1"}


def test_an_unknown_sprint_never_blocks_the_write_and_is_reported(calm):
    with patch.object(client, "get_timeboxes", return_value=SPRINTS), \
         patch.object(client, "create_task", return_value={"ID": "t"}) as m:
        out = calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
                   data={"title": "A", "task_type": "Task", "timebox": "Sprint 9"})
    assert m.call_args.kwargs["extra_fields"] is None  # saved without a sprint
    assert re.search(r"No sprint \(timebox\) named 'Sprint 9'.*Explore", out["Not Written"]["timebox"])


def test_a_sprint_id_is_used_without_a_lookup(calm):
    with patch.object(client, "get_timeboxes") as tb, \
         patch.object(client, "create_task", return_value={"ID": "t"}) as m:
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
             data={"title": "A", "task_type": "Task", "timeboxId": TB_UUID})
    tb.assert_not_called()
    assert m.call_args.kwargs["extra_fields"] == {"timeboxId": TB_UUID}


def test_an_update_looks_up_names_in_the_items_own_project(calm):
    with patch.object(client, "_get", return_value={"id": T_UUID, "projectId": P_UUID}), \
         patch.object(client, "get_timeboxes", return_value=SPRINTS) as tb, \
         patch.object(client, "update_task", return_value={"ID": T_UUID}) as m:
        calm(Ctx(), resource="tasks", operation="update", resource_id=T_UUID, data={"sprint": "Realize"})
    tb.assert_called_once_with(P_UUID, "tok", BASE)
    assert m.call_args.kwargs["extra_fields"] == {"timeboxId": "tb-2"}


# --------------------------------------------------------------------------- #
# Requirement update on another type; assignees; comments
# --------------------------------------------------------------------------- #

def test_requirement_update_on_a_user_story_keeps_it_a_user_story():
    # The 2026-10-26 live case: SAP answered 400 because type=Requirement was sent.
    with patch.object(client, "_get_with_meta", return_value=({"type": "CALMUS"}, None)), \
         patch.object(client, "_write", side_effect=_echo) as w:
        client.update_task("tok", T_UUID, status="In Progress", base_url=BASE)
    body = w.call_args.args[3]
    assert "type" not in body and body["status"] == "CIPUSINP"


def test_placeholder_assignee_is_left_out_on_create(calm):
    with patch.object(unified, "resolve_assignee") as r, \
         patch.object(client, "create_task", return_value={"ID": "t"}) as m:
        calm(Ctx(), resource="requirements", operation="create", project_id=P_UUID,
             data={"title": "A", "responsible": "Unassigned"})
    r.assert_not_called()
    assert m.call_args.kwargs["assignee_id"] is None


def test_unassigned_on_update_clears_the_responsible(calm):
    # Live: PATCH assigneeId null clears it in CALM.
    with patch.object(unified, "resolve_assignee") as r, \
         patch.object(client, "update_task", return_value={"ID": T_UUID}) as m:
        calm(Ctx(), resource="tasks", operation="update", project_id=P_UUID, resource_id=T_UUID,
             data={"assignee": "Unassigned"})
    r.assert_not_called()
    assert m.call_args.kwargs["assignee_id"] is None
    assert m.call_args.kwargs["extra_fields"] == {"assigneeId": None}


def test_requirement_assignee_is_resolved_like_a_tasks(calm):
    with patch.object(unified, "resolve_assignee", return_value="user-uuid") as r, \
         patch.object(client, "create_task", return_value={"ID": "t"}) as m:
        calm(Ctx(), resource="requirements", operation="create", project_id=P_UUID,
             data={"title": "A", "assignee": "jane.doe@example.com"})
    r.assert_called_once_with(user_identifier="jane.doe@example.com", project_id=P_UUID,
                              token="tok", base_url=BASE)
    assert m.call_args.kwargs["assignee_id"] == "user-uuid"


@pytest.mark.parametrize("key", ["text", "content", "comment", "body", "message", "note"])
def test_a_comments_words_are_sent_as_text_whatever_the_key(calm, key):
    with patch.object(client, "create_task_comment", return_value={"id": "c"}) as m:
        calm(Ctx(), resource="task_comments", operation="create", resource_id=T_UUID,
             data={key: "Created via Project Agent by A. Person."})
    assert m.call_args.kwargs["text"] == "Created via Project Agent by A. Person."


def test_an_empty_comment_is_not_posted(calm):
    with patch.object(client, "create_task_comment") as m, pytest.raises(ValueError, match="nothing was posted"):
        calm(Ctx(), resource="task_comments", operation="create", resource_id=T_UUID, data={"txt": "x"})
    m.assert_not_called()


# --------------------------------------------------------------------------- #
# Reads answer; real faults and writes still fail
# --------------------------------------------------------------------------- #

def test_a_read_missing_an_input_answers_what_is_missing(calm):
    out = calm(Ctx(), resource="requirements", operation="list")
    assert out["status"] == "invalid_request" and "project_id is required" in out["message"]


@pytest.mark.parametrize("code, status", [(404, "not_found"), (400, "invalid_request"),
                                          (403, "unavailable")])
def test_sap_refusing_a_read_is_an_answer(calm, code, status):
    err = RuntimeError(f"CALM API error: HTTP {code} X at {BASE}/api/calm-projects/v1/teams/x/roles")
    with patch.object(client, "get_team_roles", side_effect=err):
        out = calm(Ctx(), resource="team_roles", operation="list", resource_id="x")
    assert out["status"] == status


@pytest.mark.parametrize("exc", [RuntimeError("CALM API error: HTTP 503 Service Unavailable"),
                                 RuntimeError("Read timed out"),
                                 TenantNotConfiguredError("No SAP Cloud ALM tenant configured")])
def test_real_faults_on_a_read_still_fail(calm, exc):
    with patch.object(client, "get_team_roles", side_effect=exc), pytest.raises(type(exc)):
        calm(Ctx(), resource="team_roles", operation="list", resource_id="x")


def test_a_write_with_a_bad_input_still_fails(calm):
    with pytest.raises(ValueError, match="project_id is required"):
        calm(Ctx(), resource="requirements", operation="create", data={"title": "A"})


# --------------------------------------------------------------------------- #
# Linking under a parent: a sub-task takes a parent ID; anything else (a user
# story under a requirement) is a relation on the parent, as CALM itself does.
# --------------------------------------------------------------------------- #

PARENT = {"ID": T_UUID, "Display ID": "3-61724", "Type": "Requirement"}
STORY_UUID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def test_a_user_story_is_linked_under_its_requirement_by_a_relation(calm):
    with patch.object(client, "get_task", return_value=PARENT), \
         patch.object(client, "create_task", return_value={"ID": STORY_UUID, "Type": "User Story"}) as m, \
         patch.object(client, "_get", return_value=[]) as rels, \
         patch.object(client, "create_task_relation", return_value={"ok": True}) as link:
        out = calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
                   data={"title": "Story", "task_type": "User Story", "parent_id": "3-61724"})
    assert m.call_args.kwargs["parent_id"] is None  # SAP ignores a story's parentId
    assert rels.call_args.args[0] == f"{BASE}/api/calm-tasks/v1/tasks/{T_UUID}/relations"
    link.assert_called_once_with("tok", T_UUID, STORY_UUID, "0", base_url=BASE, user_email=None)
    assert out["Linked Under"] == T_UUID and "Not Written" not in out


def test_an_existing_link_is_not_made_twice(calm):
    with patch.object(client, "create_task", return_value={"ID": STORY_UUID}), \
         patch.object(client, "_get", return_value=[{"type": "0", "relationTaskId": STORY_UUID}]), \
         patch.object(client, "create_task_relation") as link:
        out = calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
                   data={"title": "Story", "task_type": "User Story", "parent_id": T_UUID})
    link.assert_not_called()
    assert out["Linked Under"] == T_UUID


def test_a_sub_task_takes_its_parent_id(calm):
    with patch.object(client, "create_task", return_value={"ID": STORY_UUID}) as m, \
         patch.object(client, "create_task_relation") as link:
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
             data={"title": "Sub", "task_type": "Subtask", "parent_id": T_UUID})
    assert m.call_args.kwargs["parent_id"] == T_UUID
    link.assert_not_called()


def test_a_link_that_fails_is_reported_and_the_saved_item_returned(calm):
    with patch.object(client, "create_task", return_value={"ID": STORY_UUID}) as m, \
         patch.object(client, "_get", return_value=[]), \
         patch.object(client, "create_task_relation", side_effect=RuntimeError("HTTP 400 Bad Request")):
        out = calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
                   data={"title": "Story", "task_type": "User Story", "parent_id": T_UUID})
    m.assert_called_once()  # never re-created
    assert out["ID"] == STORY_UUID and "task_relations" in out["Not Written"]["parent_id"]


@pytest.mark.parametrize("stored_type, as_relation", [("CALMST", False), ("CALMUS", True)])
def test_an_update_links_by_the_items_own_type(calm, stored_type, as_relation):
    def fake_get(url, token):
        return [] if url.endswith("/relations") else {"id": STORY_UUID, "type": stored_type, "projectId": P_UUID}
    with patch.object(client, "_get", side_effect=fake_get), \
         patch.object(client, "update_task", return_value={"ID": STORY_UUID}) as m, \
         patch.object(client, "create_task_relation", return_value={}) as link:
        calm(Ctx(), resource="tasks", operation="update", resource_id=STORY_UUID, data={"parent_id": T_UUID})
    assert link.called is as_relation
    assert (m.call_args.kwargs["extra_fields"] or {}).get("parentId") == (None if as_relation else T_UUID)


# --------------------------------------------------------------------------- #
# A Responsible CALM won't accept never blocks the write
# --------------------------------------------------------------------------- #

REFUSED = RuntimeError('CALM API error: HTTP 400 Bad Request at x — response: {"message":"Invalid processor ID for the task."}')


def test_a_responsible_calm_refuses_is_left_off_and_reported(calm):
    calls = []

    def create(**kw):
        calls.append(kw["assignee_id"])
        if kw["assignee_id"]:
            raise REFUSED
        return {"ID": "r1", "Title": "A"}
    with patch.object(unified, "resolve_assignee", side_effect=lambda **kw: kw["user_identifier"]), \
         patch.object(client, "create_task", side_effect=create):
        out = calm(Ctx(), resource="requirements", operation="create", project_id=P_UUID,
                   data={"title": "A", "responsible": "someone.else@example.com"})
    assert calls == ["someone.else@example.com", None]  # SAP refused the first: nothing was created
    assert out["ID"] == "r1" and "someone.else@example.com" in out["Not Written"]["assignee"]
    assert "members of this project" in out["Not Written"]["assignee"]


def test_an_update_that_only_sets_a_refused_responsible_changes_nothing(calm):
    with patch.object(unified, "resolve_assignee", side_effect=lambda **kw: kw["user_identifier"]), \
         patch.object(client, "update_task", side_effect=[REFUSED, ValueError("No fields to update — x")]), \
         pytest.raises(ValueError, match="nothing was changed"):
        calm(Ctx(), resource="tasks", operation="update", project_id=P_UUID, resource_id=T_UUID,
             data={"assignee": "someone.else@example.com"})


@pytest.mark.parametrize("exc", [RuntimeError("CALM API error: HTTP 500 Internal Server Error"),
                                 RuntimeError("CALM API error: HTTP 400 Bad Request — title too long")])
def test_other_write_failures_are_not_retried(calm, exc):
    with patch.object(unified, "resolve_assignee", side_effect=lambda **kw: kw["user_identifier"]), \
         patch.object(client, "create_task", side_effect=exc) as m, pytest.raises(RuntimeError):
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
             data={"title": "A", "task_type": "Task", "assignee": "someone.else@example.com"})
    assert m.call_count == 1


# --------------------------------------------------------------------------- #
# Approval state
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("given, code", [
    ("No Approval Required", "NO_APPR_REQ"), ("ready for approval", "READY_4_APPR"),
    ("READY_FOR_APPROVAL", "READY_4_APPR"), ("Approved", "APPROVED"), ("no_appr_req", "NO_APPR_REQ"),
])
def test_approval_states_by_name_or_code(given, code):
    assert client.resolve_approval_state(given) == code


def test_an_approval_state_calm_does_not_have_never_blocks_the_write(calm):
    # The 2026-10-26 17:00 Studio trace: "Pending Customer Confirmation" made the
    # create fail and the agent reported "not saved". Now: saved, and reported.
    with patch.object(client, "_write", side_effect=_echo) as w:
        out = calm(Ctx(), resource="requirements", operation="create", project_id=P_UUID,
                   data={"title": "A", "priority": "Medium", "approval_status": "Pending Customer Confirmation"})
    body = w.call_args.args[3]
    assert "approvalState" not in body and body["priorityId"] == 30
    assert "CALM has: Approved, Rejected, Ready for Approval, No Approval Required" in out["Not Written"]["approval_state"]


@pytest.mark.parametrize("field, value, why", [
    ("status", "Pending", "Allowed labels"), ("priority", "Urgent", "Very High, High, Medium or Low"),
    ("due_date", "12/11/2026", "date like 2026-12-31"), ("parent_id", "3-99999999", "not linked"),
])
def test_a_value_calm_cant_take_is_reported_and_the_item_still_saved(calm, field, value, why):
    with patch.object(client, "get_task", side_effect=client.NotFound("No task with display ID '3-99999999'")), \
         patch.object(client, "create_task", return_value={"ID": "t", "Title": "A"}) as m:
        out = calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
                   data={"title": "A", "task_type": "Task", field: value})
    m.assert_called_once()
    key = {"priority": "priority_id"}.get(field, field)
    assert m.call_args.kwargs.get(key) is None and why in out["Not Written"][key]


def test_an_update_whose_only_value_cant_be_written_changes_nothing(calm):
    with patch.object(client, "update_task") as m, pytest.raises(ValueError, match="Nothing was changed.*priority_id"):
        calm(Ctx(), resource="tasks", operation="update", resource_id=T_UUID, data={"priority": "Urgent"})
    m.assert_not_called()


def test_a_bad_task_type_on_create_is_still_refused(calm):
    # Nothing can be created without a type, so this one does block.
    with patch.object(client, "create_task") as m, pytest.raises(ValueError, match="Unknown task type 'Epic'"):
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID, data={"title": "A", "task_type": "Epic"})
    m.assert_not_called()


def test_approval_state_is_written_as_its_code(calm):
    with patch.object(client, "_write", side_effect=_echo) as w:
        calm(Ctx(), resource="requirements", operation="create", project_id=P_UUID,
             data={"title": "A", "approval_state": "No Approval Required"})
    assert w.call_args.args[3]["approvalState"] == "NO_APPR_REQ"


# --------------------------------------------------------------------------- #
# Finding the person: never a guess
# --------------------------------------------------------------------------- #

from src.calm.tools import user_resolver  # noqa: E402

PEOPLE = [  # task rows: who is assigned in the project
    {"AssigneeID": "u-jane", "AssigneeName": "Jane Doe"},
    {"AssigneeID": "u-john", "AssigneeName": "John Doe"},
    {"AssigneeID": "u-ana", "AssigneeName": "Ana María López"},
    {"AssigneeID": "u-ghost", "AssigneeName": None},  # a former member: no name
]


@pytest.mark.parametrize("given, found", [
    ("Jane Doe", "u-jane"), ("jane doe", "u-jane"), ("jane.doe@example.com", "u-jane"),
    ("Jane Doe <jane.doe@example.com>", "u-jane"), ("Jane", "u-jane"), ("López", "u-ana"),
    ("ana maría lópez", "u-ana"),
    ("Doe", "Doe"),                                      # two people: not guessed
    ("someone.else@example.com", "someone.else@example.com"),  # nobody: unchanged
    ("Ed", "Ed"),
])
def test_a_person_is_found_only_when_exactly_one_matches(given, found):
    with patch.object(client, "get_tasks", return_value=PEOPLE), \
         patch.object(client, "get_project_users", side_effect=RuntimeError("HTTP 403")):
        assert user_resolver.resolve_assignee(given, P_UUID, "tok", BASE) == found


def test_a_user_id_is_used_as_given():
    with patch.object(client, "get_tasks") as g:
        assert user_resolver.resolve_assignee(T_UUID, P_UUID, "tok", BASE) == T_UUID
    g.assert_not_called()


# --------------------------------------------------------------------------- #
# Dates SAP didn't keep (live: a user story's sprint + due date in one write
# loses the due date — SAP re-derives it from the sprint)
# --------------------------------------------------------------------------- #

def test_a_date_sap_did_not_keep_is_sent_again_on_its_own(calm):
    with patch.object(client, "get_timeboxes", return_value=SPRINTS), \
         patch.object(client, "update_task", side_effect=[
             {"ID": T_UUID, "DueDate": None, "Timebox ID": "tb-2"},
             {"ID": T_UUID, "DueDate": "2026-12-31", "Timebox ID": "tb-2"}]) as m:
        out = calm(Ctx(), resource="tasks", operation="update", project_id=P_UUID, resource_id=T_UUID,
                   data={"due_date": "2026-12-31T00:00:00Z", "sprint": "Realize"})
    assert m.call_count == 2
    assert m.call_args_list[1].kwargs == {"base_url": BASE, "user_email": None, "due_date": "2026-12-31"}
    assert out["DueDate"] == "2026-12-31" and "Not Written" not in out


def test_a_date_sap_still_does_not_keep_is_reported(calm):
    with patch.object(client, "create_task", return_value={"ID": T_UUID, "DueDate": None}), \
         patch.object(client, "update_task", return_value={"ID": T_UUID, "DueDate": None}) as m:
        out = calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
                   data={"title": "A", "task_type": "User Story", "due_date": "2026-12-31"})
    m.assert_called_once()
    assert "did not keep this date" in out["Not Written"]["due_date"]


def test_kept_dates_cost_no_extra_write(calm):
    with patch.object(client, "create_task", return_value={"ID": T_UUID, "DueDate": "2026-12-31"}), \
         patch.object(client, "update_task") as m:
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
             data={"title": "A", "task_type": "Task", "due_date": "2026-12-31"})
    m.assert_not_called()


def test_a_sub_task_without_its_parent_is_refused_before_writing(calm):
    # Live 2026-10-27: SAP answers 400 "Invalid parent task id".
    with patch.object(client, "create_task") as m, pytest.raises(ValueError, match="sub-task needs its parent"):
        calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID, data={"title": "A", "task_type": "Subtask"})
    m.assert_not_called()
