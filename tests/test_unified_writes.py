"""Write-path tests for the unified ``calm_resource`` tool.

These tests are the regression net for the consolidation bug where every
create/update/delete branch called the ``src.calm.client`` functions with the
wrong argument order — passing the ``data`` dict into the ``token`` slot and
shifting every argument, and passing ``base_url`` into the ``if_match``/``force``
slot on deletes.

Every test patches the corresponding ``src.calm.client`` function and asserts it
was invoked with the correct **keyword arguments**, unpacked from ``data``. They
run entirely against mocks — no network, no writes to any tenant.

Run with:  ./venv/bin/python -m pytest tests/test_unified_writes.py -q
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

TOKEN = "test-token-12345"
BASE_URL = "https://test.calm.cloud.sap"


class Ctx:
    """Minimal context: no request_context, so get_calm_headers falls through to env."""


def _fn():
    """Return the underlying calm_resource function from a fresh registration."""
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("test")
    register(mcp)
    tool = asyncio.run(mcp.get_tool("calm_resource"))
    return tool.fn


@pytest.fixture(autouse=True)
def write_env(monkeypatch):
    """Resolve credentials from env and enable writes for every test here."""
    monkeypatch.setenv("CALM_TOKEN", TOKEN)
    monkeypatch.setenv("CALM_BASE_URL", BASE_URL)
    monkeypatch.setenv("CALM_ENABLE_WRITES", "true")
    # Make sure header-based creds don't leak in from a real shell.
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("CALM_USER_EMAIL", raising=False)
    yield


# --------------------------------------------------------------------------- #
# projects
# --------------------------------------------------------------------------- #

def test_project_create():
    fn = _fn()
    with patch("src.calm.client.create_project") as m:
        m.return_value = {"ID": "P1"}
        fn(Ctx(), resource="projects", operation="create",
           data={"name": "New", "program_id": "PG1", "extra_fields": {"x": 1}})
        m.assert_called_once_with(
            token=TOKEN, name="New", program_id="PG1",
            deployment_plan_id=None, extra_fields={"x": 1},
            base_url=BASE_URL, user_email=None,
        )


def test_project_update_passes_if_match():
    fn = _fn()
    with patch("src.calm.client.update_project") as m:
        m.return_value = {"ID": "P1"}
        fn(Ctx(), resource="projects", operation="update", resource_id="P1",
           data={"name": "Renamed", "if_match": "etag-9"})
        m.assert_called_once_with(
            token=TOKEN, project_id="P1", name="Renamed", program_id=None,
            deployment_plan_id=None, if_match="etag-9", extra_fields=None,
            base_url=BASE_URL, user_email=None,
        )


def test_project_create_requires_name():
    fn = _fn()
    with pytest.raises(ValueError, match="name"):
        fn(Ctx(), resource="projects", operation="create", data={})


# --------------------------------------------------------------------------- #
# tasks  (incl. assignee resolution — the "smart" processing that was lost)
# --------------------------------------------------------------------------- #

def test_task_create_resolves_assignee():
    fn = _fn()
    with patch("src.calm.tools.unified.resolve_assignee", return_value="uuid-42") as res, \
         patch("src.calm.client.create_task") as m:
        m.return_value = {"ID": "T1"}
        fn(Ctx(), resource="tasks", operation="create", project_id="P1",
           data={"title": "Do it", "task_type": "User Story", "assignee_id": "jane@x.com"})
        res.assert_called_once_with(
            user_identifier="jane@x.com", project_id="P1", token=TOKEN, base_url=BASE_URL,
        )
        # The resolved UUID (not the raw email) must reach the client.
        _, kwargs = m.call_args
        assert kwargs["assignee_id"] == "uuid-42"
        assert kwargs["title"] == "Do it"
        assert kwargs["task_type"] == "User Story"
        assert kwargs["token"] == TOKEN
        assert kwargs["project_id"] == "P1"


def test_task_create_requires_task_type():
    fn = _fn()
    with pytest.raises(ValueError, match="task_type"):
        fn(Ctx(), resource="tasks", operation="create", project_id="P1",
           data={"title": "No type"})


def test_task_update_resolves_assignee_with_explicit_project():
    fn = _fn()
    with patch("src.calm.tools.unified.resolve_assignee", return_value="uuid-7") as res, \
         patch("src.calm.client.update_task") as m:
        m.return_value = {"ID": "T1"}
        fn(Ctx(), resource="tasks", operation="update", resource_id="T1", project_id="P9",
           data={"assignee_id": "bob@x.com", "status": "In Progress"})
        res.assert_called_once_with(
            user_identifier="bob@x.com", project_id="P9", token=TOKEN, base_url=BASE_URL,
        )
        _, kwargs = m.call_args
        assert kwargs["task_id"] == "T1"
        assert kwargs["assignee_id"] == "uuid-7"


def test_task_delete_positional_token_first():
    fn = _fn()
    with patch("src.calm.client.delete_task") as m:
        m.return_value = {"deleted": True}
        fn(Ctx(), resource="tasks", operation="delete", resource_id="T1")
        m.assert_called_once_with(
            token=TOKEN, task_id="T1", base_url=BASE_URL, user_email=None,
        )


# --------------------------------------------------------------------------- #
# requirements  (task_type pinned + subStatus folding)
# --------------------------------------------------------------------------- #

def test_requirement_create_folds_sub_status():
    fn = _fn()
    with patch("src.calm.client.create_task") as m:
        m.return_value = {"ID": "R1"}
        fn(Ctx(), resource="requirements", operation="create", project_id="P1",
           data={"title": "Req A", "sub_status": "IN_PLANNING"})
        _, kwargs = m.call_args
        assert kwargs["task_type"] == "Requirement"
        assert kwargs["extra_fields"] == {"subStatus": "IN_PLANNING"}
        assert kwargs["title"] == "Req A"


def test_requirement_update_pins_type():
    fn = _fn()
    with patch("src.calm.client.update_task") as m:
        m.return_value = {"ID": "R1"}
        fn(Ctx(), resource="requirements", operation="update", resource_id="R1",
           data={"status": "Done"})
        _, kwargs = m.call_args
        assert kwargs["task_type"] == "Requirement"
        assert kwargs["task_id"] == "R1"


# --------------------------------------------------------------------------- #
# business_processes  (delete if_match — was receiving base_url)
# --------------------------------------------------------------------------- #

def test_business_process_create():
    fn = _fn()
    with patch("src.calm.client.create_business_process") as m:
        m.return_value = {"ID": "BP1"}
        fn(Ctx(), resource="business_processes", operation="create",
           data={"name": "BP", "description": "d"})
        m.assert_called_once_with(
            token=TOKEN, name="BP", description="d", base_url=BASE_URL, user_email=None,
        )


def test_business_process_delete_if_match_not_base_url():
    fn = _fn()
    with patch("src.calm.client.delete_business_process") as m:
        m.return_value = {"deleted": True}
        fn(Ctx(), resource="business_processes", operation="delete",
           resource_id="BP1", data={"if_match": "etag-1"})
        m.assert_called_once_with(
            token=TOKEN, business_process_id="BP1", if_match="etag-1",
            base_url=BASE_URL, user_email=None,
        )


# --------------------------------------------------------------------------- #
# solution_processes
# --------------------------------------------------------------------------- #

def test_solution_process_create_full():
    fn = _fn()
    with patch("src.calm.client.create_solution_process") as m:
        m.return_value = {"ID": "SP1"}
        fn(Ctx(), resource="solution_processes", operation="create",
           data={"name": "SP", "countries": ["DE"], "state": "active",
                 "business_process_id": "BP1", "external_id": "E1"})
        m.assert_called_once_with(
            token=TOKEN, name="SP", description=None, status=None,
            countries=["DE"], state="active", business_process_id="BP1",
            external_id="E1", base_url=BASE_URL, user_email=None,
        )


def test_solution_process_delete_if_match_not_base_url():
    fn = _fn()
    with patch("src.calm.client.delete_solution_process") as m:
        m.return_value = {"deleted": True}
        fn(Ctx(), resource="solution_processes", operation="delete",
           resource_id="SP1", data={"if_match": "etag-2"})
        m.assert_called_once_with(
            token=TOKEN, solution_process_id="SP1", if_match="etag-2",
            base_url=BASE_URL, user_email=None,
        )


# --------------------------------------------------------------------------- #
# timeboxes
# --------------------------------------------------------------------------- #

def test_timebox_create():
    fn = _fn()
    with patch("src.calm.client.create_timebox") as m:
        m.return_value = {"ID": "TB1"}
        fn(Ctx(), resource="timeboxes", operation="create", project_id="P1",
           data={"name": "Sprint 1", "timebox_type": "sprint",
                 "start_date": "2026-01-01", "end_date": "2026-01-14"})
        m.assert_called_once_with(
            token=TOKEN, project_id="P1", name="Sprint 1", timebox_type="sprint",
            start_date="2026-01-01", end_date="2026-01-14", closed=None,
            extra_fields=None, base_url=BASE_URL, user_email=None,
        )


def test_timebox_delete():
    fn = _fn()
    with patch("src.calm.client.delete_timebox") as m:
        m.return_value = {"deleted": True}
        fn(Ctx(), resource="timeboxes", operation="delete", resource_id="TB1")
        m.assert_called_once_with(
            token=TOKEN, timebox_id="TB1", base_url=BASE_URL, user_email=None,
        )


# --------------------------------------------------------------------------- #
# scopes  (delete if_match — was receiving base_url)
# --------------------------------------------------------------------------- #

def test_scope_create_requires_project_and_name():
    fn = _fn()
    with pytest.raises(ValueError, match="project_id"):
        fn(Ctx(), resource="scopes", operation="create", data={"name": "S"})


def test_scope_delete_if_match_not_base_url():
    fn = _fn()
    with patch("src.calm.client.delete_scope") as m:
        m.return_value = {"deleted": True}
        fn(Ctx(), resource="scopes", operation="delete",
           resource_id="SC1", data={"if_match": "etag-3"})
        m.assert_called_once_with(
            token=TOKEN, scope_id="SC1", if_match="etag-3",
            base_url=BASE_URL, user_email=None,
        )


# --------------------------------------------------------------------------- #
# test_cases  (required scope_id; delete force + if_match)
# --------------------------------------------------------------------------- #

def test_test_case_create_requires_scope_id():
    fn = _fn()
    with pytest.raises(ValueError, match="scope_id"):
        fn(Ctx(), resource="test_cases", operation="create", project_id="P1",
           data={"title": "TC"})


def test_test_case_create_full():
    fn = _fn()
    with patch("src.calm.client.create_test_case") as m:
        m.return_value = {"ID": "TC1"}
        fn(Ctx(), resource="test_cases", operation="create", project_id="P1",
           data={"title": "TC", "scope_id": "SC1", "priority": "High", "is_prepared": True})
        _, kwargs = m.call_args
        assert kwargs["title"] == "TC"
        assert kwargs["project_id"] == "P1"
        assert kwargs["scope_id"] == "SC1"
        assert kwargs["priority"] == "High"
        assert kwargs["is_prepared"] is True
        assert kwargs["token"] == TOKEN


def test_test_case_delete_force_and_if_match():
    fn = _fn()
    with patch("src.calm.client.delete_test_case") as m:
        m.return_value = {"deleted": True}
        fn(Ctx(), resource="test_cases", operation="delete", resource_id="TC1",
           data={"force": True, "if_match": "etag-4"})
        m.assert_called_once_with(
            token=TOKEN, test_case_id="TC1", force=True, if_match="etag-4",
            base_url=BASE_URL, user_email=None,
        )


# --------------------------------------------------------------------------- #
# tags  (the user-reported bug: project_id + group + tag)
# --------------------------------------------------------------------------- #

def test_tag_create_returns_unavailable_without_calling_client():
    """SAP's public API exposes no scope for creating tag definitions, so
    create must return a clear 'unavailable' explanation and never attempt the
    doomed write."""
    fn = _fn()
    with patch("src.calm.client.create_tag") as m:
        result = fn(Ctx(), resource="tags", operation="create", project_id="P1",
                    data={"group": "Region", "tag": "EMEA"})
        m.assert_not_called()
        assert result["status"] == "unavailable"
        assert result["supported"] is False
        assert result["resource"] == "tags"
        # Points the user at the supported alternative (task_tags / the UI)
        assert "task_tags" in result["alternative"]


def test_tag_list_returns_unavailable_on_403():
    """When the project tag-definition read 403s (no scope exists), surface the
    platform-limitation explanation rather than the raw error."""
    fn = _fn()
    err = RuntimeError("CALM API error: HTTP 403 Forbidden at .../tags — ...")
    with patch("src.calm.client.get_tags", side_effect=err):
        result = fn(Ctx(), resource="tags", operation="list", project_id="P1")
        assert result["status"] == "unavailable"
        assert result["resource"] == "tags"


def test_tag_list_reraises_non_auth_error():
    """A transient (non-403/401/404) failure is a real error — don't mask it as
    a platform limitation."""
    fn = _fn()
    err = RuntimeError("CALM API error: HTTP 500 Internal Server Error at .../tags")
    with patch("src.calm.client.get_tags", side_effect=err):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            fn(Ctx(), resource="tags", operation="list", project_id="P1")


# --------------------------------------------------------------------------- #
# features / test_plans
# --------------------------------------------------------------------------- #

def test_feature_create():
    fn = _fn()
    with patch("src.calm.client.create_feature") as m:
        m.return_value = {"ID": "F1"}
        fn(Ctx(), resource="features", operation="create", project_id="P1",
           data={"name": "Feat", "external_id": "EX1"})
        m.assert_called_once_with(
            token=TOKEN, project_id="P1", name="Feat", description=None,
            external_id="EX1", extra_fields=None, base_url=BASE_URL, user_email=None,
        )


def test_test_plan_create():
    fn = _fn()
    with patch("src.calm.client.create_test_plan") as m:
        m.return_value = {"ID": "TP1"}
        fn(Ctx(), resource="test_plans", operation="create", project_id="P1",
           data={"name": "Plan"})
        m.assert_called_once_with(
            token=TOKEN, project_id="P1", name="Plan", description=None,
            extra_fields=None, base_url=BASE_URL, user_email=None,
        )


# --------------------------------------------------------------------------- #
# user_email override + write guard
# --------------------------------------------------------------------------- #

def test_user_email_override_reaches_client():
    fn = _fn()
    with patch("src.calm.client.create_business_process") as m:
        m.return_value = {"ID": "BP1"}
        fn(Ctx(), resource="business_processes", operation="create",
           data={"name": "BP"}, user_email="acting@x.com")
        _, kwargs = m.call_args
        assert kwargs["user_email"] == "acting@x.com"


def test_write_guard_blocks_when_disabled(monkeypatch):
    monkeypatch.setenv("CALM_ENABLE_WRITES", "")
    fn = _fn()
    with patch("src.calm.client.create_business_process") as m:
        with pytest.raises(ValueError, match="Write operations are disabled"):
            fn(Ctx(), resource="business_processes", operation="create",
               data={"name": "BP"})
        m.assert_not_called()


# --------------------------------------------------------------------------- #
# sub-entity / relationship resources (parity with the old 75-tool surface)
# --------------------------------------------------------------------------- #

def test_task_relation_create():
    fn = _fn()
    with patch("src.calm.client.create_task_relation") as m:
        m.return_value = {"ok": True}
        fn(Ctx(), resource="task_relations", operation="create", resource_id="T1",
           data={"relation_task_id": "T2", "relation_type": "1"})
        m.assert_called_once_with(
            token=TOKEN, task_id="T1", relation_task_id="T2",
            relation_type="1", base_url=BASE_URL, user_email=None,
        )


def test_task_relation_delete():
    fn = _fn()
    with patch("src.calm.client.delete_task_relation") as m:
        m.return_value = {"deleted": "R1"}
        fn(Ctx(), resource="task_relations", operation="delete", resource_id="R1")
        m.assert_called_once_with(
            token=TOKEN, relation_id="R1", base_url=BASE_URL, user_email=None,
        )


def test_task_comment_create():
    fn = _fn()
    with patch("src.calm.client.create_task_comment") as m:
        m.return_value = {"ok": True}
        fn(Ctx(), resource="task_comments", operation="create", resource_id="T1",
           data={"text": "hello"})
        m.assert_called_once_with(
            token=TOKEN, task_id="T1", text="hello", extra_fields=None,
            base_url=BASE_URL, user_email=None,
        )


def test_task_comment_update():
    fn = _fn()
    with patch("src.calm.client.update_task_comment") as m:
        m.return_value = {"updated": "C1"}
        fn(Ctx(), resource="task_comments", operation="update", resource_id="C1",
           data={"text": "edited"})
        m.assert_called_once_with(
            token=TOKEN, comment_id="C1", text="edited", extra_fields=None,
            base_url=BASE_URL, user_email=None,
        )


def test_task_comment_delete():
    fn = _fn()
    with patch("src.calm.client.delete_task_comment") as m:
        m.return_value = {"deleted": "C1"}
        fn(Ctx(), resource="task_comments", operation="delete", resource_id="C1")
        m.assert_called_once_with(
            token=TOKEN, comment_id="C1", base_url=BASE_URL, user_email=None,
        )


def test_task_tags_set_via_update():
    fn = _fn()
    with patch("src.calm.client.set_task_tags") as m:
        m.return_value = {"ok": True}
        fn(Ctx(), resource="task_tags", operation="update", resource_id="T1",
           data={"tags": ["Phase: Build", "Area: UI"]})
        m.assert_called_once_with(
            token=TOKEN, task_id="T1", tags=["Phase: Build", "Area: UI"],
            base_url=BASE_URL, user_email=None,
        )


def test_task_tags_missing_tags_raises():
    fn = _fn()
    with pytest.raises(ValueError, match="must include 'tags'"):
        fn(Ctx(), resource="task_tags", operation="update", resource_id="T1", data={})


def test_test_action_create():
    fn = _fn()
    with patch("src.calm.client.create_test_action") as m:
        m.return_value = {"ok": True}
        fn(Ctx(), resource="test_actions", operation="create", resource_id="A1",
           data={"title": "Step 1", "expected_result": "pass", "sequence": 1})
        m.assert_called_once_with(
            token=TOKEN, activity_id="A1", title="Step 1", description=None,
            expected_result="pass", sequence=1, is_evidence_required=None,
            base_url=BASE_URL, user_email=None,
        )


def test_test_action_update_passes_if_match():
    fn = _fn()
    with patch("src.calm.client.update_test_action") as m:
        m.return_value = {"updated": "AC1"}
        fn(Ctx(), resource="test_actions", operation="update", resource_id="AC1",
           data={"title": "New", "if_match": "etag-1"})
        m.assert_called_once_with(
            token=TOKEN, action_id="AC1", title="New", description=None,
            expected_result=None, sequence=None, is_evidence_required=None,
            if_match="etag-1", base_url=BASE_URL, user_email=None,
        )


def test_test_action_delete_passes_if_match():
    fn = _fn()
    with patch("src.calm.client.delete_test_action") as m:
        m.return_value = {"deleted": "AC1"}
        fn(Ctx(), resource="test_actions", operation="delete", resource_id="AC1",
           data={"if_match": "etag-9"})
        m.assert_called_once_with(
            token=TOKEN, action_id="AC1", if_match="etag-9",
            base_url=BASE_URL, user_email=None,
        )


def test_test_activity_update():
    fn = _fn()
    with patch("src.calm.client.update_test_activity") as m:
        m.return_value = {"updated": "ACT1"}
        fn(Ctx(), resource="test_activities", operation="update", resource_id="ACT1",
           data={"title": "T", "is_in_scope": True, "if_match": "e"})
        m.assert_called_once_with(
            token=TOKEN, activity_id="ACT1", title="T", sequence=None,
            is_in_scope=True, if_match="e", base_url=BASE_URL, user_email=None,
        )


def test_test_activity_delete():
    fn = _fn()
    with patch("src.calm.client.delete_test_activity") as m:
        m.return_value = {"deleted": "ACT1"}
        fn(Ctx(), resource="test_activities", operation="delete", resource_id="ACT1",
           data={"if_match": "e"})
        m.assert_called_once_with(
            token=TOKEN, activity_id="ACT1", if_match="e",
            base_url=BASE_URL, user_email=None,
        )


def test_scope_assignments_update():
    fn = _fn()
    assignments = [{"scopeId": "S1", "isScoped": True}]
    with patch("src.calm.client.update_scope_assignments") as m:
        m.return_value = {"ok": True}
        fn(Ctx(), resource="scope_assignments", operation="update",
           data={"assignments": assignments})
        m.assert_called_once_with(
            token=TOKEN, assignments=assignments, base_url=BASE_URL, user_email=None,
        )


def test_scenario_versions_assign():
    fn = _fn()
    with patch("src.calm.client.assign_scenario_versions") as m:
        m.return_value = {"ok": True}
        fn(Ctx(), resource="scenario_versions", operation="create", resource_id="S1",
           data={"version_ids": ["v1", "v2"]})
        m.assert_called_once_with(
            token=TOKEN, scope_id="S1", version_ids=["v1", "v2"],
            base_url=BASE_URL, user_email=None,
        )


def test_test_case_link_create():
    fn = _fn()
    with patch("src.calm.client.link_test_case_to_requirement") as m:
        m.return_value = {"ok": True}
        fn(Ctx(), resource="test_case_links", operation="create", resource_id="TC1",
           data={"requirement_id": "3-999", "link_type": "validates"})
        m.assert_called_once_with(
            token=TOKEN, test_case_id="TC1", requirement_id="3-999",
            link_type="validates", base_url=BASE_URL, user_email=None,
        )


def test_test_plan_assignment_create():
    fn = _fn()
    with patch("src.calm.client.assign_test_case_to_plan") as m:
        m.return_value = {"ok": True}
        fn(Ctx(), resource="test_plan_assignments", operation="create", resource_id="TP1",
           data={"test_case_id": "TC1", "tester_email": "qa@x.com"})
        m.assert_called_once_with(
            token=TOKEN, test_plan_id="TP1", test_case_id="TC1",
            tester_email="qa@x.com", extra_fields=None,
            base_url=BASE_URL, user_email=None,
        )


def test_task_tags_valid_tags_pass_validation():
    """Tags that exist in the project's configured list are sent through."""
    fn = _fn()
    configured = [
        {"Group": "Scope", "Tag": "Baseline", "Full Name": "Scope: Baseline"},
        {"Group": "Tshirt size", "Tag": "L", "Full Name": "Tshirt size: L"},
    ]
    with patch("src.calm.client.get_tags", return_value=configured) as mget:
        with patch("src.calm.client.set_task_tags") as mset:
            mset.return_value = {"ok": True}
            fn(Ctx(), resource="task_tags", operation="update", resource_id="T1",
               project_id="P1", data={"tags": ["Scope: Baseline", "Tshirt size: L"]})
            mget.assert_called_once_with("P1", TOKEN, BASE_URL)
            mset.assert_called_once_with(
                token=TOKEN, task_id="T1", tags=["Scope: Baseline", "Tshirt size: L"],
                base_url=BASE_URL, user_email=None,
            )


def test_task_tags_validation_best_effort_on_403():
    """If reading the project tag list 403s (no scope in SAP's API), validation
    is skipped and the assignment still goes through via the Tasks API. This is
    the fix for 'tag assignment sometimes works, sometimes doesn't'."""
    fn = _fn()
    err = RuntimeError("CALM API error: HTTP 403 Forbidden at .../tags — ...")
    with patch("src.calm.client.get_tags", side_effect=err):
        with patch("src.calm.client.set_task_tags") as mset:
            mset.return_value = {"ok": True}
            fn(Ctx(), resource="task_tags", operation="update", resource_id="T1",
               project_id="P1", data={"tags": ["Scope: Baseline"]})
            mset.assert_called_once_with(
                token=TOKEN, task_id="T1", tags=["Scope: Baseline"],
                base_url=BASE_URL, user_email=None,
            )


def test_task_tags_unknown_tag_raises_not_silently_dropped():
    """The whole point: an undefined tag must error, not vanish."""
    fn = _fn()
    configured = [{"Group": "Scope", "Tag": "Baseline", "Full Name": "Scope: Baseline"}]
    with patch("src.calm.client.get_tags", return_value=configured):
        with patch("src.calm.client.set_task_tags") as mset:
            with pytest.raises(ValueError, match="not defined in project P1"):
                fn(Ctx(), resource="task_tags", operation="update", resource_id="T1",
                   project_id="P1", data={"tags": ["Scope: Baseline", "Made Up: Nope"]})
            mset.assert_not_called()  # nothing sent when any tag is invalid


def test_task_tags_validation_ignores_colon_spacing():
    """'Scope:Baseline' must match a configured 'Scope: Baseline'."""
    fn = _fn()
    configured = [{"Group": "Scope", "Tag": "Baseline", "Full Name": "Scope: Baseline"}]
    with patch("src.calm.client.get_tags", return_value=configured):
        with patch("src.calm.client.set_task_tags") as mset:
            mset.return_value = {"ok": True}
            fn(Ctx(), resource="task_tags", operation="update", resource_id="T1",
               project_id="P1", data={"tags": ["Scope:Baseline"]})
            mset.assert_called_once()


def test_task_tags_dict_form_validates():
    """Tags given as {'group','tag'} dicts validate the same way."""
    fn = _fn()
    configured = [{"Group": "Scope", "Tag": "Baseline", "Full Name": "Scope: Baseline"}]
    with patch("src.calm.client.get_tags", return_value=configured):
        with patch("src.calm.client.set_task_tags") as mset:
            mset.return_value = {"ok": True}
            fn(Ctx(), resource="task_tags", operation="update", resource_id="T1",
               project_id="P1", data={"tags": [{"group": "Scope", "tag": "Baseline"}]})
            mset.assert_called_once()


def test_task_tags_no_project_id_skips_validation():
    """Backward compatible: without project_id we can't read the list, so send as-is."""
    fn = _fn()
    with patch("src.calm.client.get_tags") as mget:
        with patch("src.calm.client.set_task_tags") as mset:
            mset.return_value = {"ok": True}
            fn(Ctx(), resource="task_tags", operation="update", resource_id="T1",
               data={"tags": ["Anything: Goes"]})
            mget.assert_not_called()
            mset.assert_called_once()


def test_task_tags_skip_validation_flag():
    """An explicit opt-out bypasses the project-tag check even with project_id."""
    fn = _fn()
    with patch("src.calm.client.get_tags") as mget:
        with patch("src.calm.client.set_task_tags") as mset:
            mset.return_value = {"ok": True}
            fn(Ctx(), resource="task_tags", operation="update", resource_id="T1",
               project_id="P1", data={"tags": ["Made Up: Nope"], "skip_validation": True})
            mget.assert_not_called()
            mset.assert_called_once()


def test_subentity_write_guard_blocks_when_disabled(monkeypatch):
    """The write guard must also cover the new sub-entity branches."""
    monkeypatch.setenv("CALM_ENABLE_WRITES", "")
    fn = _fn()
    with patch("src.calm.client.set_task_tags") as m:
        with pytest.raises(ValueError, match="Write operations are disabled"):
            fn(Ctx(), resource="task_tags", operation="update", resource_id="T1",
               data={"tags": ["a"]})
        m.assert_not_called()


# --------------------------------------------------------------------------- #
# calm_api_read — the read/GET escape hatch (advanced_write.py)
# --------------------------------------------------------------------------- #

def _read_fn():
    """Return the underlying calm_api_read function from a fresh registration."""
    from fastmcp import FastMCP

    from src.calm.tools.advanced_write import register

    mcp = FastMCP("test")
    register(mcp)
    tool = asyncio.run(mcp.get_tool("calm_api_read"))
    return tool.fn


def test_api_read_calls_client_with_path_and_params():
    fn = _read_fn()
    with patch("src.calm.client.api_read") as m:
        m.return_value = [{"id": "P1"}]
        fn("api/calm-projects/v1/projects", Ctx(), params={"$top": 50})
        m.assert_called_once_with(
            token=TOKEN,
            path="api/calm-projects/v1/projects",
            params={"$top": 50},
            base_url=BASE_URL,
        )


def test_api_read_requires_path():
    fn = _read_fn()
    with pytest.raises(ValueError, match="path is required"):
        fn("", Ctx())


def test_api_read_is_not_write_gated(monkeypatch):
    """Reads must work even when writes are disabled — the whole point of the
    escape hatch is that an agent without calm_resource can still read."""
    monkeypatch.setenv("CALM_ENABLE_WRITES", "")
    fn = _read_fn()
    with patch("src.calm.client.api_read") as m:
        m.return_value = {"ok": True}
        result = fn("api/calm-projects/v1/projects", Ctx())
        assert result == {"ok": True}
        m.assert_called_once()


def test_client_api_read_builds_url_and_querystring():
    """client.api_read builds the tenant URL + query string and delegates to _get."""
    import src.calm.client as c
    with patch("src.calm.client._get") as g:
        g.return_value = {"ok": True}
        c.api_read(token=TOKEN, path="api/calm-tasks/v1/tasks/3-1", base_url=BASE_URL)
        called_url = g.call_args.args[0]
        assert called_url == f"{BASE_URL}/api/calm-tasks/v1/tasks/3-1"
        # leading slash on path is tolerated, and params become a query string
        c.api_read(token=TOKEN, path="/api/calm-projects/v1/projects",
                   params={"$top": 5}, base_url=BASE_URL)
        url2 = g.call_args.args[0]
        assert url2 == f"{BASE_URL}/api/calm-projects/v1/projects?%24top=5"


# --------------------------------------------------------------------------- #
# scopes list — project_id filtering (tenant-wide endpoint, filtered in-tool)
# --------------------------------------------------------------------------- #

def test_scopes_list_filters_by_project_id():
    fn = _fn()
    all_scopes = [
        {"ID": "s1", "Project ID": "P1", "Name": "Finance"},
        {"ID": "s2", "Project ID": "P2", "Name": "Logistics"},
        {"ID": "s3", "Project ID": "P1", "Name": "HR"},
    ]
    with patch("src.calm.client.get_scopes", return_value=all_scopes):
        result = fn(Ctx(), resource="scopes", operation="list", project_id="P1")
        assert [s["ID"] for s in result] == ["s1", "s3"]


# --------------------------------------------------------------------------- #
# features — use the dedicated Features service, not the Projects path
# --------------------------------------------------------------------------- #

def test_get_features_uses_features_service_and_filters_by_project():
    """features.read unlocks /api/calm-features/v1/Features — NOT the Projects
    path (which 403s). The client hits the Features service and filters by
    project client-side."""
    import src.calm.client as c
    raw = [
        {"id": "F1", "projectId": "P1", "name": "A"},
        {"id": "F2", "projectId": "P2", "name": "B"},
        {"id": "F3", "projectId": "P1", "name": "C"},
    ]
    with patch("src.calm.client._get", return_value=raw) as g:
        result = c.get_features("P1", TOKEN, BASE_URL)
        called_url = g.call_args.args[0]
        assert called_url == f"{BASE_URL}/api/calm-features/v1/Features"
        assert "/projects/" not in called_url
        assert [f["ID"] for f in result] == ["F1", "F3"]


def test_create_feature_posts_to_features_service_with_project_in_body():
    import src.calm.client as c
    with patch("src.calm.client._write", return_value={"id": "F9"}) as w:
        c.create_feature(token=TOKEN, project_id="P1", name="New", base_url=BASE_URL)
        method, url = w.call_args.args[0], w.call_args.args[1]
        body = w.call_args.args[3]
        assert method == "POST"
        assert url == f"{BASE_URL}/api/calm-features/v1/Features"
        assert body["projectId"] == "P1" and body["name"] == "New"


def test_scopes_list_without_project_id_returns_all():
    fn = _fn()
    all_scopes = [
        {"ID": "s1", "Project ID": "P1"},
        {"ID": "s2", "Project ID": "P2"},
    ]
    with patch("src.calm.client.get_scopes", return_value=all_scopes):
        result = fn(Ctx(), resource="scopes", operation="list")
        assert len(result) == 2


# --------------------------------------------------------------------------- #
# project_users / customization — SAP platform limitations (no public scope)
# --------------------------------------------------------------------------- #

def test_project_users_list_returns_unavailable_on_403():
    fn = _fn()
    err = RuntimeError("CALM API error: HTTP 403 Forbidden at .../members")
    with patch("src.calm.client.get_project_users", side_effect=err):
        result = fn(Ctx(), resource="project_users", operation="list", project_id="P1")
        assert result["status"] == "unavailable"
        assert result["resource"] == "project_users"


def test_project_users_list_succeeds_when_api_allows():
    """If a tenant ever exposes it, the real data still comes through."""
    fn = _fn()
    members = [{"email": "a@x.com"}]
    with patch("src.calm.client.get_project_users", return_value=members):
        result = fn(Ctx(), resource="project_users", operation="list", project_id="P1")
        assert result == members


def test_customization_get_returns_unavailable_on_403():
    fn = _fn()
    err = RuntimeError("CALM API error: HTTP 403 Forbidden at .../customization")
    with patch("src.calm.client.get_project_customization", side_effect=err):
        result = fn(Ctx(), resource="customization", operation="get", project_id="P1")
        assert result["status"] == "unavailable"
        assert result["resource"] == "customization"


def test_customization_get_reraises_non_auth_error():
    fn = _fn()
    err = RuntimeError("CALM API error: HTTP 500 Internal Server Error")
    with patch("src.calm.client.get_project_customization", side_effect=err):
        with pytest.raises(RuntimeError, match="HTTP 500"):
            fn(Ctx(), resource="customization", operation="get", project_id="P1")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
