"""tasks list filters: counts computed by the server from every task, with a
check that nothing was dropped.

Production (2026-11-02, Project Agent - Lutron): asked for one person's overdue
tasks, the agent pulled the whole task list, counted it itself from a trimmed
copy and said 12; CALM showed 25 (4 Blocked, 21 In Progress). The tasks list now
filters by person, status, priority, overdue and due dates server-side and
answers with the exact count plus a Check. "Overdue" is CALM's own rule: due
before today and not Done / Not Relevant (matched CALM analytics' overdue flag
on all 26,511 tasks of the test tenant).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client  # noqa: E402

TODAY = date(2026, 11, 2)
PAST, LATER = "2026-10-01", "2026-12-01"


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


def _row(i, status="Open", due=None, name=None, uid=None, **kw):
    r = {"ID": f"id-{i}", "Display ID": f"3-{i}", "Title": f"Task {i}", "Type": "Project Task",
         "Status": status, "DueDate": due, "AssigneeName": name, "AssigneeID": uid,
         "Priority": "Medium", "Scope": None, "Scope ID": None, "Tags": [], "Effort": None,
         "Timebox": None, "Timebox ID": None, "Responsible Team": None, "Responsible Team ID": None}
    r.update(kw)
    return r


def _project():
    """Person A: 4 Blocked + 21 In Progress overdue, plus tasks that are not."""
    rows = [_row(i, "Blocked", PAST, "Person Alpha", "u-a") for i in range(4)]
    rows += [_row(10 + i, "In Progress", PAST, "Person Alpha", "u-a") for i in range(21)]
    rows += [_row(40, "Done", PAST, "Person Alpha", "u-a"),               # finished: not overdue
             _row(41, "Not Relevant", PAST, "Person Alpha", "u-a"),
             _row(42, "Open", TODAY.isoformat(), "Person Alpha", "u-a"),  # due today: not yet
             _row(43, "Open", None, "Person Alpha", "u-a"),               # no due date
             _row(44, "Open", LATER, "Person Alpha", "u-a"),
             _row(50, "Open", PAST, "Person Beta", "u-b"),
             _row(51, "Blocked", PAST, None, None)]
    return rows


def _list(calm, rows, task_type=None, **data):
    with patch("src.calm.client.get_tasks", return_value=rows) as gt, \
            patch("src.calm.tools.unified.datetime") as dt:
        dt.now.return_value.date.return_value = TODAY
        out = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                   task_type=task_type, data=data)
    return out, gt


def test_overdue_count_for_one_person_is_exact(calm):
    out, _ = _list(calm, _project(), assignee="Person Alpha", overdue=True,
                   summarize_by=["AssigneeName", "Status"])
    assert out["Total Tasks"] == 25
    assert {(g["Status"], g["Tasks"]) for g in out["Groups"]} == {("Blocked", 4), ("In Progress", 21)}
    assert out["Filters"] == {"AssigneeName": "Person Alpha", "overdue": True, "as_of": "2026-11-02"}
    check = out["Check"]
    assert check["Tasks Read"] == 32 and check["Matched"] == 25 and check["Groups Add Up"] is True
    assert check["Tasks Without Due Date"] == 1


@pytest.mark.parametrize("who", ["Person Alpha", "alpha", "ALPHA PERSON", "person.alpha@example.com", "u-a"])
def test_person_matched_by_name_words_or_email_or_id(calm, who):
    out, _ = _list(calm, _project(), assignee=who, overdue=True)
    assert out["Total Matching"] == 25 and out["Check"]["Not Returned"] == 0


def test_name_matching_two_people_is_ambiguous_not_added_together(calm):
    out, _ = _list(calm, _project(), assignee="Person", overdue=True)
    assert out["status"] == "ambiguous" and set(out["matches"]) == {"Person Alpha", "Person Beta"}


def test_task_with_missing_name_kept_through_the_persons_id(calm):
    rows = _project() + [_row(60, "Blocked", PAST, None, "u-a")]
    out, _ = _list(calm, rows, assignee="Person Alpha", overdue=True, summarize_by="AssigneeName")
    assert out["Total Tasks"] == 26


def test_unknown_person_says_so_with_the_names_present(calm):
    out, _ = _list(calm, _project(), assignee="Persn Alpa", overdue=True, summarize_by="Status")
    assert out["Total Tasks"] == 0
    report = out["Filter Values With No Tasks"]["AssigneeName"]
    assert report["no tasks for"] == ["Persn Alpa"] and "Person Alpha" in report["values present"]
    out, _ = _list(calm, _project(), assignee="Persn Alpa", overdue=True)
    assert out["status"] == "invalid_request" and "Person Alpha" in out["message"]


def test_overdue_rule_matches_calm(calm):
    out, _ = _list(calm, _project(), overdue=True, fields=["Display ID"])
    ids = {r["Display ID"] for r in out["Tasks"]}
    assert len(ids) == 27 and not ids & {"3-40", "3-41", "3-42", "3-43", "3-44"}
    out, _ = _list(calm, _project(), overdue=False, summarize_by="Status")
    assert out["Total Tasks"] == 5


def test_as_of_sets_the_day(calm):
    out, _ = _list(calm, _project(), assignee="Person Alpha", overdue=True,
                   as_of=(TODAY + timedelta(days=1)).isoformat(), summarize_by="Status")
    assert out["Total Tasks"] == 26  # the task due today is overdue tomorrow
    out, _ = _list(calm, _project(), as_of="2026-11-03")
    assert out["status"] == "invalid_request" and "overdue" in out["message"]


def test_status_priority_and_generic_filter(calm):
    rows = _project() + [_row(70, "Done", LATER, "Person Beta", "u-b", Priority="High", Scope="FICO")]
    out, _ = _list(calm, rows, status=["closed"], summarize_by="Status")
    assert out["Total Tasks"] == 2  # "closed" is Done; Not Relevant is not
    out, _ = _list(calm, rows, status=["Blocked", "In Progress"], summarize_by="Status")
    assert out["Total Tasks"] == 26
    out, _ = _list(calm, rows, priority="20", summarize_by="Priority")
    assert out["Total Tasks"] == 1
    out, _ = _list(calm, rows, filter={"scope": "fico", "Assignee": "beta"}, summarize_by="Scope")
    assert out["Total Tasks"] == 1
    out, _ = _list(calm, rows, filter={"assignee": None}, summarize_by="AssigneeName")
    assert out["Total Tasks"] == 1
    out, _ = _list(calm, rows, filter={"Colour": "red"})
    assert out["status"] == "invalid_request" and "AssigneeName" in out["message"]


def test_due_date_bounds(calm):
    out, _ = _list(calm, _project(), due_from="2026-11-02", due_to="2026-12-01", summarize_by="Status")
    assert out["Total Tasks"] == 2 and out["Check"]["Tasks Without Due Date"] == 1
    out, _ = _list(calm, _project(), due_before="2026-11-02", summarize_by="Status")
    assert out["Total Tasks"] == 29
    out, _ = _list(calm, _project(), due_after="31/31/2026")
    assert out["status"] == "invalid_request"


def test_duplicate_rows_are_counted_once(calm):
    rows = _project()
    out, _ = _list(calm, rows + rows[:3], assignee="Person Alpha", overdue=True, summarize_by="Status")
    assert out["Total Tasks"] == 25 and out["Check"]["Duplicate Rows Removed"] == 3


def test_requirements_list_takes_the_same_filters(calm):
    rows = [_row(1, "Open", PAST, "Person Alpha", "u-a", Type="Requirement")]
    out, gt = _list(calm, rows, overdue=True, summarize_by="Status")
    with patch("src.calm.client.get_tasks", return_value=rows) as gt, \
            patch("src.calm.tools.unified.datetime") as dt:
        dt.now.return_value.date.return_value = TODAY
        out = calm(Ctx(), resource="requirements", operation="list", project_id="p1",
                   data={"overdue": True, "summarize_by": "Status"})
    assert gt.call_args.kwargs["task_type"] == "Requirement" and out["Total Tasks"] == 1


def test_plain_list_is_unchanged(calm):
    rows = _project()
    out, _ = _list(calm, rows)
    assert out == rows


def test_where_tasks_report_lists_tags_present():
    rows = [_row(1, Tags=["SIT"]), _row(2, Tags=["UAT", "SIT - FI"])]
    kept, report = client.where_tasks(rows, {"Tags": ["SIT", "OCM"]})
    assert [r["ID"] for r in kept] == ["id-1"]
    assert report["Tags"] == {"no tasks for": ["OCM"], "values present": ["SIT", "SIT - FI", "UAT"]}


# --------------------------------------------------------------------------- #
# Lutron 2026-11-03: a person with 5 "overdue" tasks had none in CALM. CALM never
# counts obsolete tasks (hidden; its analytics skips every one), and a status
# code missing from the map (CIPTKREV, "In Review") showed as a raw code.
# --------------------------------------------------------------------------- #

def test_an_obsolete_task_is_never_overdue_and_the_check_says_so(calm):
    rows = [_row(1, "Open", PAST, "Person Gamma", "u-g", Obsolete=True),
            _row(2, "Open", PAST, "Person Gamma", "u-g", Obsolete=True),
            _row(3, "Open", PAST, "Person Gamma", "u-g", Obsolete=False)]
    out, _ = _list(calm, rows, assignee="Person Gamma", overdue=True, summarize_by="Status")
    assert out["Total Tasks"] == 1 and out["Check"]["Obsolete Not Counted"] == 2
    assert out["Check"]["By Type"] == {"Project Task": 1}


def test_status_codes_get_labels_and_review_counts_as_open_work(calm):
    from src.calm import client
    assert client.status_label("CIPTKREV") == "In Review"
    assert client.status_label("CIPUSREV") == "In Review"   # a code SAP may add: labelled by its ending
    assert client.status_label("CIPXYDONE") == "Done"
    assert client.status_label("ZCUSTOM") == "ZCUSTOM"
    row = client._format_task({"id": "t", "status": "CIPTKREV", "subStatus": "TO_BE_APPROVED"})
    assert row["Status"] == "In Review" and row["Sub-status"] == "TO_BE_APPROVED"
    rows = [_row(1, "In Review", PAST, "Person Alpha", "u-a"), _row(2, "Done", PAST, "Person Alpha", "u-a")]
    out, _ = _list(calm, rows, overdue=True, status="review", summarize_by="Status")
    assert out["Total Tasks"] == 1 and out["Groups"][0]["Status"] == "In Review"
    assert client.resolve_status_code("In Review", "CALMTASK") == "CIPTKREV"


def test_quality_gates_and_checklist_items_are_not_overdue_unless_asked_for(calm):
    rows = [_row(1, "Open", PAST, "Person Gamma", "u-g", Type="Checklist Item"),
            _row(2, "Open", PAST, "Person Gamma", "u-g", Type="Quality Gate"),
            _row(3, "Open", PAST, "Person Gamma", "u-g")]
    out, _ = _list(calm, rows, assignee="Person Gamma", overdue=True, summarize_by="Type")
    assert out["Total Tasks"] == 1 and out["Check"]["Quality Gates / Checklist Items Not Counted"] == 2
    out, _ = _list(calm, rows[1:2], task_type="Quality Gate", overdue=True, summarize_by="Type")
    assert out["Total Tasks"] == 1 and "Quality Gates / Checklist Items Not Counted" not in out["Check"]
