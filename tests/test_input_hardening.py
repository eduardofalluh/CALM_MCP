"""calm_resource accepts the reasonable input shapes agents actually send.

Three shapes used to fail even though the intent was unambiguous:

- ``data`` sent as JSON text instead of a JSON object;
- a project's NAME in ``project_id`` (or ``data.project_id``) instead of its UUID;
- a task / requirement / test case named by its DISPLAY ID ("3-60729",
  "8-1-1380") on update, delete, comments, relations, tags and links.

Each is now normalised once before dispatch, reusing reads the MCP already
makes. Anything that worked before (UUIDs, other IDs, dict data) is passed
through untouched. Everything runs against mocks — no network.
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
from src.calm.tools import unified  # noqa: E402

BASE = "https://x.alm.cloud.sap"
P_UUID = "5e6f7081-92a3-4b4c-8d5e-6f708192a3b4"
P2_UUID = "7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d"
T_UUID = "6f708192-a3b4-4c5d-9e6f-708192a3b4c5"
R_UUID = "8192a3b4-c5d6-4e7f-8091-a2b3c4d5e6f7"
TC_UUID = "3f2b1c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
PROJECTS = [
    {"ID": P_UUID, "Name": "Delivery Excellence - Sprint Planning"},
    {"ID": P2_UUID, "Name": "Project Agent Report - Test Project"},
    {"ID": "11111111-1111-1111-1111-111111111111", "Name": "Implementation Project"},
]


class Ctx:
    """No request_context — credentials come from env."""


class H:
    token, base_url = "tok", BASE


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


@pytest.fixture
def real_project_lookup(monkeypatch):
    """Undo the suite-wide pass-through (conftest) for these tests."""
    monkeypatch.setattr(unified, "_resolve_project_id", unified.resolve_project_id)


# --------------------------------------------------------------------------- #
# data as JSON text
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("given, expected", [
    ({"title": "A"}, {"title": "A"}),
    ('{"title": "A", "task_type": "Project Task"}', {"title": "A", "task_type": "Project Task"}),
    (None, {}), ("", {}), ("null", {}),
])
def test_parse_data_accepts_objects_and_object_text(given, expected):
    assert unified.parse_data(given) == expected


@pytest.mark.parametrize("given, match", [
    ("{title: A}", "not valid JSON"), ('["a", "b"]', "JSON object"), (42, "JSON object"),
])
def test_parse_data_refuses_non_objects_clearly(given, match):
    with pytest.raises(ValueError, match=match):
        unified.parse_data(given)


def test_create_with_data_as_json_text(calm):
    with patch.object(client, "create_task", return_value={"ID": "new"}) as ct:
        out = calm(Ctx(), resource="tasks", operation="create", project_id=P_UUID,
                   data='{"title": "Configure GL", "task_type": "Project Task"}')
    assert out == {"ID": "new"}
    assert ct.call_args.kwargs["title"] == "Configure GL"
    assert ct.call_args.kwargs["task_type"] == "Project Task"


def test_update_with_empty_json_text_still_says_data_is_required(calm):
    with patch.object(client, "update_task") as ut, pytest.raises(ValueError, match="data is required"):
        calm(Ctx(), resource="tasks", operation="update", resource_id=T_UUID, data="{}")
    ut.assert_not_called()


# --------------------------------------------------------------------------- #
# Project name instead of ID
# --------------------------------------------------------------------------- #

def test_uuid_project_id_is_never_looked_up():
    with patch.object(client, "get_projects") as gp:
        assert unified.resolve_project_id(P_UUID, H()) == P_UUID
    gp.assert_not_called()


@pytest.mark.parametrize("given, expected", [
    ("Delivery Excellence - Sprint Planning", P_UUID),       # exact name
    ("  delivery excellence -  sprint planning ", P_UUID),   # case / spacing
    ("Sprint Planning", P_UUID),                             # unique part of a name
    ("implementation project", "11111111-1111-1111-1111-111111111111"),
])
def test_project_names_resolve_to_ids(given, expected):
    with patch.object(client, "get_projects", return_value=PROJECTS):
        assert unified.resolve_project_id(given, H()) == expected


def test_non_uuid_project_ids_still_match_by_id():
    with patch.object(client, "get_projects", return_value=[{"ID": "P001", "Name": "Test Project A"}]):
        assert unified.resolve_project_id("p001", H()) == "P001"


def test_ambiguous_project_name_lists_the_candidates():
    with patch.object(client, "get_projects", return_value=PROJECTS), pytest.raises(ValueError) as err:
        unified.resolve_project_id("project", H())
    assert "matches 2 projects" in str(err.value) and P2_UUID in str(err.value)


def test_unknown_project_name_lists_real_projects():
    with patch.object(client, "get_projects", return_value=PROJECTS), pytest.raises(ValueError) as err:
        unified.resolve_project_id("Payroll Rollout", H())
    assert "No project" in str(err.value) and "Delivery Excellence - Sprint Planning" in str(err.value)


def test_unreadable_project_list_passes_the_value_through():
    with patch.object(client, "get_projects", side_effect=RuntimeError("HTTP 403")):
        assert unified.resolve_project_id("Sprint Planning", H()) == "Sprint Planning"


def test_calm_resource_resolves_project_names(calm, real_project_lookup):
    with patch.object(client, "get_projects", return_value=PROJECTS), \
         patch.object(client, "get_tasks", return_value=[]) as gt:
        calm(Ctx(), resource="tasks", operation="list", project_id="Sprint Planning")
        calm(Ctx(), resource="requirements", operation="list", project_id="sprint planning")
    assert [c.args[0] for c in gt.call_args_list] == [P_UUID, P_UUID]


def test_project_name_inside_data_is_resolved_too(calm, real_project_lookup):
    with patch.object(client, "get_projects", return_value=PROJECTS), \
         patch.object(client, "get_tasks", return_value=[]) as gt:
        calm(Ctx(), resource="tasks", operation="list", data={"project_id": "Sprint Planning"})
    assert gt.call_args.args[0] == P_UUID


# --------------------------------------------------------------------------- #
# Display IDs on writes
# --------------------------------------------------------------------------- #

def _task(uuid=T_UUID, display="3-60729"):
    return {"ID": uuid, "Display ID": display, "Title": "Cost center reporting", "Tags": []}


@pytest.mark.parametrize("resource, operation, fn, kw", [
    ("tasks", "update", "update_task", {"data": {"title": "New"}}),
    ("tasks", "delete", "delete_task", {}),
    ("requirements", "update", "update_task", {"data": {"title": "New"}}),
    ("requirements", "delete", "delete_task", {}),
])
def test_task_writes_by_display_id(calm, resource, operation, fn, kw):
    with patch.object(client, "get_task", return_value=_task()) as gt, \
         patch.object(client, fn, return_value={"ok": True}) as w:
        calm(Ctx(), resource=resource, operation=operation, project_id=P_UUID, resource_id="3-60729", **kw)
    assert gt.call_args.args[1] == "3-60729" and gt.call_args.kwargs["project_id"] == P_UUID
    assert w.call_args.kwargs["task_id"] == T_UUID


def test_comment_relation_and_tags_by_display_id(calm):
    with patch.object(client, "get_task", side_effect=lambda tok, ident, base, project_id=None:
                      _task(T_UUID if ident == "3-60729" else R_UUID, ident)), \
         patch.object(client, "create_task_comment", return_value={}) as cc, \
         patch.object(client, "create_task_relation", return_value={}) as cr, \
         patch.object(client, "set_task_tags", return_value={}) as st:
        calm(Ctx(), resource="task_comments", operation="create", project_id=P_UUID,
             resource_id="3-60729", data={"content": "Reviewed"})
        calm(Ctx(), resource="task_relations", operation="create", project_id=P_UUID,
             data={"task_id": "3-60729", "relation_task_id": "3-60730", "relation_type": "related"})
        calm(Ctx(), resource="task_tags", operation="update", project_id=P_UUID,
             resource_id="3-60729", data={"tags": ["SIT"], "skip_validation": True})
    assert cc.call_args.kwargs["task_id"] == T_UUID
    assert cr.call_args.kwargs["task_id"] == T_UUID and cr.call_args.kwargs["relation_task_id"] == R_UUID
    assert st.call_args.kwargs["task_id"] == T_UUID


def test_test_case_writes_and_links_by_display_id(calm):
    detail = {"ID": TC_UUID, "Display ID": "8-1-1380"}
    with patch.object(client, "get_test_case", return_value=detail) as gtc, \
         patch.object(client, "get_task", return_value=_task(R_UUID, "3-55")), \
         patch.object(client, "update_test_case", return_value={}) as ut, \
         patch.object(client, "delete_test_case", return_value={}) as dt, \
         patch.object(client, "link_test_case_to_requirement", return_value={}) as lk:
        calm(Ctx(), resource="test_cases", operation="update", resource_id="8-1-1380", data={"title": "T"})
        calm(Ctx(), resource="test_cases", operation="delete", resource_id="8-1-1380")
        calm(Ctx(), resource="test_case_links", operation="create", project_id=P_UUID,
             resource_id="8-1-1380", data={"requirement_id": "3-55"})
    assert gtc.call_args.args[1] == "8-1-1380"
    assert ut.call_args.kwargs["test_case_id"] == TC_UUID and dt.call_args.kwargs["test_case_id"] == TC_UUID
    assert lk.call_args.kwargs["test_case_id"] == TC_UUID and lk.call_args.kwargs["requirement_id"] == R_UUID


def test_display_id_write_without_project_says_what_to_pass(calm):
    with patch.object(client, "update_task") as ut, pytest.raises(ValueError, match="pass project_id"):
        calm(Ctx(), resource="tasks", operation="update", resource_id="3-60729", data={"title": "New"})
    ut.assert_not_called()


def test_secondary_display_ids_without_project_pass_through_as_before(calm):
    with patch.object(client, "get_task") as gt, \
         patch.object(client, "link_test_case_to_requirement", return_value={}) as lk:
        calm(Ctx(), resource="test_case_links", operation="create", resource_id=TC_UUID,
             data={"requirement_id": "3-999"})
    gt.assert_not_called()
    assert lk.call_args.kwargs["requirement_id"] == "3-999"


@pytest.mark.parametrize("ident", [T_UUID, "T1", "task-123"])
def test_other_ids_are_never_looked_up(calm, ident):
    with patch.object(client, "get_task") as gt, patch.object(client, "delete_task", return_value={}) as dl:
        calm(Ctx(), resource="tasks", operation="delete", resource_id=ident)
    gt.assert_not_called()
    assert dl.call_args.kwargs["task_id"] == ident


def test_writes_disabled_refuses_before_any_lookup(calm, monkeypatch):
    monkeypatch.setenv("CALM_ENABLE_WRITES", "false")
    with patch.object(client, "get_task") as gt, pytest.raises(ValueError, match="(?i)write"):
        calm(Ctx(), resource="tasks", operation="delete", project_id=P_UUID, resource_id="3-60729")
    gt.assert_not_called()


def test_display_id_lookup_failure_is_clear_and_writes_nothing(calm):
    with patch.object(client, "get_task", side_effect=ValueError("No task with display ID or external ID '3-1'")), \
         patch.object(client, "delete_task") as dl, pytest.raises(ValueError, match="No task"):
        calm(Ctx(), resource="tasks", operation="delete", project_id=P_UUID, resource_id="3-1")
    dl.assert_not_called()


def test_tool_schema_accepts_data_as_object_or_text():
    from fastmcp import FastMCP

    mcp = FastMCP("t")
    unified.register(mcp)
    tool = asyncio.run(mcp.get_tool("calm_resource"))
    schema = json.dumps(tool.parameters["properties"]["data"])
    assert '"object"' in schema and '"string"' in schema
