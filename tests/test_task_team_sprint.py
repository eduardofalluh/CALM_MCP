"""Tests that formatted CALM tasks expose the responsible team and the sprint.

Every task in the Tasks API carries ``responsibleTeamId`` and ``timeboxId``
(verified live: all 301 tasks of a sprint-planning project had both keys), but
``_format_task`` dropped them, so an agent asked for "task counts and effort per
sprint and per team" had nothing to group by. These tests pin:

- the four new fields, appended AFTER every existing field (order unchanged);
- get_tasks resolving team / sprint names in one lookup each, only when needed;
- a failed name lookup degrading to IDs only, never failing the task read.
"""

from unittest.mock import patch

from src.calm import client

BASE = "https://x.alm.cloud.sap"
EXISTING_KEYS = [
    "ID", "Display ID", "External ID (FRICEF)", "Title", "Type", "Status",
    "Parent ID", "StartDate", "DueDate", "AssigneeName", "AssigneeID",
    "ApprovalState", "Obsolete", "Effort", "Tags",
]
NEW_KEYS = ["Responsible Team ID", "Responsible Team", "Timebox ID", "Timebox"]

TEAMS = [{"ID": "team-fin", "Name": "Consulting - Finance"}, {"ID": "team-otc", "Name": "Consulting - OTC"}]
SPRINTS = [{"ID": "tb-1", "Name": "Sprint 1"}, {"ID": "tb-2", "Name": "Sprint 2"}]


def _raw(**over):
    base = {
        "id": "t1", "displayId": "3-1", "title": "Configure GL", "type": "CALMTASK",
        "status": "CIPTKOPEN", "effort": 8.0, "tags": [],
        "responsibleTeamId": "team-fin", "timeboxId": "tb-1",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# _format_task
# --------------------------------------------------------------------------- #

LATER_KEYS = ["Priority", "Scope ID", "Scope", "Workstream", "Assigned Role", "Created", "Last Changed"]


def test_existing_fields_unchanged_and_new_fields_appended():
    out = client._format_task(_raw())
    # The original fields stay first and in order; additions only ever append.
    assert list(out) == EXISTING_KEYS + NEW_KEYS + LATER_KEYS


def test_ids_always_surfaced_names_none_without_maps():
    out = client._format_task(_raw())
    assert out["Responsible Team ID"] == "team-fin"
    assert out["Timebox ID"] == "tb-1"
    assert out["Responsible Team"] is None and out["Timebox"] is None


def test_names_resolved_from_maps():
    out = client._format_task(_raw(), {"team-fin": "Consulting - Finance"}, {"tb-1": "Sprint 1"})
    assert out["Responsible Team"] == "Consulting - Finance"
    assert out["Timebox"] == "Sprint 1"


def test_unassigned_and_unknown_ids():
    out = client._format_task(_raw(responsibleTeamId=None, timeboxId="tb-unknown"),
                              {"team-fin": "x"}, {"tb-1": "Sprint 1"})
    assert out["Responsible Team ID"] is None and out["Responsible Team"] is None
    assert out["Timebox ID"] == "tb-unknown" and out["Timebox"] is None


def test_raw_without_the_keys_still_formats():
    raw = _raw()
    del raw["responsibleTeamId"], raw["timeboxId"]
    out = client._format_task(raw)
    assert out["Responsible Team ID"] is None and out["Timebox ID"] is None


# --------------------------------------------------------------------------- #
# get_tasks name resolution
# --------------------------------------------------------------------------- #

def _run(tasks, teams=TEAMS, sprints=SPRINTS, **kw):
    with patch("src.calm.client._get_all", return_value=tasks) as ga, \
         patch("src.calm.client.get_project_teams", side_effect=teams if callable(teams) else lambda *a: teams) as gt, \
         patch("src.calm.client.get_timeboxes", side_effect=sprints if callable(sprints) else lambda *a: sprints) as gb:
        rows = client.get_tasks("p1", "tok", BASE, **kw)
    return rows, ga, gt, gb


def test_get_tasks_resolves_team_and_sprint_names():
    rows, _, gt, gb = _run([
        _raw(),
        _raw(id="t2", responsibleTeamId="team-otc", timeboxId="tb-2", effort=16.0),
        _raw(id="t3", responsibleTeamId=None, timeboxId=None, effort=None),
    ])
    assert [(r["Responsible Team"], r["Timebox"]) for r in rows] == [
        ("Consulting - Finance", "Sprint 1"), ("Consulting - OTC", "Sprint 2"), (None, None),
    ]
    gt.assert_called_once_with("p1", "tok", BASE)
    gb.assert_called_once_with("p1", "tok", BASE)


def test_no_extra_requests_when_no_task_has_team_or_sprint():
    rows, ga, gt, gb = _run([_raw(responsibleTeamId=None, timeboxId=None)])
    assert ga.call_count == 1
    gt.assert_not_called()
    gb.assert_not_called()
    assert rows[0]["Responsible Team"] is None


def test_lookup_failure_keeps_ids_and_never_fails_the_read():
    def boom(*a):
        raise RuntimeError("HTTP 403 Forbidden")

    rows, *_ = _run([_raw()], teams=boom, sprints=boom)
    assert rows[0]["Responsible Team ID"] == "team-fin" and rows[0]["Responsible Team"] is None
    assert rows[0]["Timebox ID"] == "tb-1" and rows[0]["Timebox"] is None
    assert rows[0]["Title"] == "Configure GL"


def test_type_filter_still_applies_and_names_still_resolve():
    rows, ga, *_ = _run([_raw(), _raw(id="s1", type="CALMST")], task_type="Project Task")
    assert [r["ID"] for r in rows] == ["t1"]
    assert "type=CALMTASK" in ga.call_args.args[0]
    assert rows[0]["Timebox"] == "Sprint 1"


def test_per_team_per_sprint_grouping_is_possible_from_rows():
    """The question that failed: counts + effort per sprint and team."""
    rows, *_ = _run([
        _raw(id="a", effort=8.0),
        _raw(id="b", effort=4.0),
        _raw(id="c", responsibleTeamId="team-otc", timeboxId="tb-2", effort=16.0),
    ])
    grid = {}
    for r in rows:
        k = (r["Responsible Team"], r["Timebox"])
        n, e = grid.get(k, (0, 0.0))
        grid[k] = (n + 1, e + (r["Effort"] or 0))
    assert grid == {("Consulting - Finance", "Sprint 1"): (2, 12.0),
                    ("Consulting - OTC", "Sprint 2"): (1, 16.0)}
