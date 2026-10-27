"""Regression tests for round 2: a customer write/duplicate-check trace and the
second stx review of 0de94f9.

Production trace (2026-10-23), project agent asked to create CALM tasks for the
non-duplicates of a 13-item RAID list:

- the duplicate check called tasks list with data={"search": ..., "top": 20};
  neither key existed, both were silently ignored, and each of the 6 parallel
  calls returned the whole project (2,088 tasks, ~1.1M chars) -> the model's
  context overflowed. Now: unknown keys are refused, search/top work.
- a task update (dueDate) got "SAP closed the connection without a response".
  The request is byte-identical to the one that has worked since August, so the
  drop is SAP-side; the MCP now reads the task back and resends safely instead
  of leaving "may or may not have been applied" to the agent.

Review round 2: TLS handshake drops are transient again (certificate / mTLS /
protocol failures stay permanent); a real sprint with no tasks is not a typo; a
failed name lookup can't masquerade as "no tasks"; "(unresolved: id)" works as a
filter; placeholders such as "<Table Name>" survive rich-text cleanup; the
server's TM credential never goes to a caller-chosen host; the entity-set cache
is bounded and doesn't pin a "no plans" answer.
Everything runs against mocks — no network, no real sleeps.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import ssl
import sys
from pathlib import Path
from unittest.mock import patch

import re

import pytest
import requests
from urllib3.exceptions import ProtocolError

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client, http_retry  # noqa: E402

BASE = "https://x.alm.cloud.sap"
TASK_URL = f"{BASE}/api/calm-tasks/v1/tasks/t-1"


class Ctx:
    """No request_context — credentials come from env."""


@pytest.fixture(autouse=True)
def no_sleep():
    sleeps = []
    with patch.object(http_retry, "_sleep", sleeps.append):
        yield sleeps


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


def dropped():
    return requests.exceptions.ConnectionError(ProtocolError(
        "Connection aborted.", http.client.RemoteDisconnected("Remote end closed connection without response")))


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self.text = "" if body is None else json.dumps(body)
        self.reason = "OK" if status < 400 else "Error"
        self.headers = headers or {}

    def json(self):
        return json.loads(self.text)


class Script:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _row(i, title, **kw):
    r = {"ID": f"id-{i}", "Display ID": f"3-{i}", "External ID (FRICEF)": None, "Title": title,
         "Type": "Project Task", "Status": "Open", "Timebox": None, "Timebox ID": None,
         "Responsible Team": None, "Responsible Team ID": None, "Effort": None}
    r.update(kw)
    return r


# --------------------------------------------------------------------------- #
# tasks list options: refuse unknown keys, support search / top
# --------------------------------------------------------------------------- #

def test_unknown_data_key_is_refused_before_any_read(calm):
    with patch("src.calm.client.get_tasks") as gt:
        msg = _refused(calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                            data={"status": "Open"}))
    gt.assert_not_called()
    assert "'status'" in msg and "search" in msg and "top" in msg and "summarize_by" in msg


def test_none_values_and_top_level_args_in_data_are_accepted(calm):
    rows = [_row(1, "A")]
    with patch("src.calm.client.get_tasks", return_value=rows) as gt:
        out = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                   data={"tag": None, "project_id": "p1", "task_type": "Project Task"})
    assert out == rows
    assert gt.call_args.kwargs["task_type"] == "Project Task"


def test_project_id_only_in_data_works(calm):
    with patch("src.calm.client.get_tasks", return_value=[]) as gt:
        calm(Ctx(), resource="tasks", operation="list", data={"project_id": "p9"})
    assert gt.call_args.args[0] == "p9"


def test_conflicting_project_id_in_data_is_refused(calm):
    _refused(calm(Ctx(), resource="tasks", operation="list", project_id="p1", data={"project_id": "p2"}),
             "differs")


@pytest.mark.parametrize("top", [0, -1, "x", True, 2.5, [3]])
def test_bad_top_is_refused(calm, top):
    with patch("src.calm.client.get_tasks") as gt:
        _refused(calm(Ctx(), resource="tasks", operation="list", project_id="p1", data={"top": top}), "top")
    gt.assert_not_called()


@pytest.mark.parametrize("search", ["", "   ", True, ["a"]])
def test_bad_search_is_refused(calm, search):
    _refused(calm(Ctx(), resource="tasks", operation="list", project_id="p1", data={"search": search}),
             "search")


def test_top_with_summarize_by_is_refused(calm):
    _refused(calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                  data={"summarize_by": ["Status"], "top": 5}), "top does not apply")


def test_top_limits_rows_and_says_how_many_exist(calm):
    rows = [_row(i, f"T{i}") for i in range(10)]
    with patch("src.calm.client.get_tasks", return_value=rows):
        out = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                   data={"limit": "3", "fields": ["Title"]})
    assert out["Total Matching"] == 10 and out["Returned"] == 3
    assert out["Tasks"] == [{"ID": "id-0", "Title": "T0"}, {"ID": "id-1", "Title": "T1"},
                            {"ID": "id-2", "Title": "T2"}]
    assert "first 3 of 10" in out["Note"]


def test_plain_list_unchanged_without_new_options(calm):
    rows = [_row(1, "A"), _row(2, "B")]
    with patch("src.calm.client.get_tasks", return_value=rows):
        assert calm(Ctx(), resource="tasks", operation="list", project_id="p1") == rows


def test_alias_and_name_disagreeing_is_refused(calm):
    _refused(calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                  data={"search": "a", "query": "b"}), "alias")


# --------------------------------------------------------------------------- #
# search_tasks
# --------------------------------------------------------------------------- #

RAID_TITLES = [
    "Confirm whether the standard report can replace the legacy XYZ1/XYZ2 lookup",
    "Standard report to replace legacy XYZ1 / XYZ2 lookups",       # reworded duplicate
    "Decide whether plan-versus-actual reporting includes cost-center detail",
    "Inconsistent rate and surcharge configuration",
    "Configure GL accounts",
    "Unit test GL posting",
]


def _raid_rows():
    return [_row(i, t) for i, t in enumerate(RAID_TITLES)]


def test_search_phrase_ignores_case_and_punctuation():
    hits = client.search_tasks(_raid_rows(), "xyz1/xyz2 LOOKUP")
    assert hits[0]["Title"] == RAID_TITLES[0]


def test_search_finds_reworded_duplicates_best_first():
    hits = client.search_tasks(_raid_rows(), RAID_TITLES[0])
    titles = [h["Title"] for h in hits]
    assert titles[0] == RAID_TITLES[0]          # exact phrase first
    assert RAID_TITLES[1] in titles             # the reworded one still found
    assert "Configure GL accounts" not in titles


def test_search_exact_ids():
    rows = _raid_rows()
    rows[4]["External ID (FRICEF)"] = "FIN-007"
    assert [h["ID"] for h in client.search_tasks(rows, "fin-007")] == ["id-4"]
    assert [h["ID"] for h in client.search_tasks(rows, "3-5")] == ["id-5"]


def test_search_no_match_and_stopwords_only():
    assert client.search_tasks(_raid_rows(), "payroll interface") == []
    # A search of only common words still works (falls back to all its words).
    assert client.search_tasks([_row(1, "To be or not to be")], "to be") != []


def test_search_short_word_needs_a_whole_word():
    rows = [_row(1, "Position overview"), _row(2, "SIT preparation")]
    assert [h["ID"] for h in client.search_tasks(rows, "SIT")] == ["id-2"]


def test_search_through_calm_resource_shape_and_no_match_note(calm):
    with patch("src.calm.client.get_tasks", return_value=_raid_rows()):
        hit = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                   data={"search": "XYZ1/XYZ2 lookup", "top": 20, "fields": ["Title", "Status"]})
        miss = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                    data={"search": "payroll interface"})
    assert hit["Search"] == "XYZ1/XYZ2 lookup" and hit["Total Matching"] == 2
    assert set(hit["Tasks"][0]) == {"ID", "Title", "Status"}
    assert miss["Total Matching"] == 0 and miss["Tasks"] == []
    assert "No task in this project matches" in miss["Note"]


def test_search_defaults_to_25_rows():
    rows = [_row(i, f"Data migration load {i}") for i in range(60)]
    from src.calm.tools import unified
    assert unified.TASK_SEARCH_DEFAULT_TOP == 25
    hits = client.search_tasks(rows, "data migration load")
    assert len(hits) == 60  # the cap is applied by the tool, see below


def test_the_traced_duplicate_check_now_fits(calm):
    """6 parallel duplicate checks over a 2,088-task project used to return the
    whole project each (~1.1M chars); now each answer is a few rows."""
    rows = [_row(i, f"Generic project task number {i} for finance workstream") for i in range(2088)]
    rows[1500] = _row(1500, RAID_TITLES[0])
    with patch("src.calm.client.get_tasks", return_value=rows):
        for title in RAID_TITLES[:4] + ["Decide reporting for cost centers", "Surcharge config"]:
            out = calm(Ctx(), resource="tasks", operation="list",
                       project_id="11111111-1111-1111-1111-111111111111",
                       data={"search": title, "top": 20})
            assert len(json.dumps(out)) < 20_000, title
            assert out["Returned"] <= 20
    assert out["Total Matching"] <= 25


def test_search_combines_with_summarize_by(calm):
    with patch("src.calm.client.get_tasks", return_value=_raid_rows()):
        out = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                   data={"search": "GL", "summarize_by": ["Status"]})
    assert out["Total Tasks"] == 2 and out["Search"] == "GL"


# --------------------------------------------------------------------------- #
# Filters: empty sprint vs typo, failed name lookup, "(unresolved: id)"
# --------------------------------------------------------------------------- #

SPRINTS = [{"ID": "tb1", "Name": "Sprint 1"}, {"ID": "tb5", "Name": "Sprint 5"}]


def test_existing_sprint_with_no_tasks_is_an_empty_answer_not_an_error(calm):
    rows = [_row(1, "A", Timebox="Sprint 1", **{"Timebox ID": "tb1"})]
    with patch("src.calm.client.get_tasks", return_value=rows), \
         patch("src.calm.client.get_timeboxes", return_value=SPRINTS):
        out = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                   data={"timebox": "Sprint 5"})
    assert out["Total Matching"] == 0 and out["Tasks"] == []
    assert out["Filter Values With No Tasks"]["timebox"]["exist but have no tasks"] == ["Sprint 5"]


def test_typo_still_errors_with_project_names(calm):
    rows = [_row(1, "A", Timebox="Sprint 1", **{"Timebox ID": "tb1"})]
    with patch("src.calm.client.get_tasks", return_value=rows), \
         patch("src.calm.client.get_timeboxes", return_value=SPRINTS):
        msg = _refused(calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                            data={"timebox": "Sprnt 5"}))
    assert "Sprnt 5" in msg and "Sprint 5" in msg


def test_catalog_failure_keeps_the_old_report(calm):
    rows = [_row(1, "A", Timebox="Sprint 1", **{"Timebox ID": "tb1"})]
    with patch("src.calm.client.get_tasks", return_value=rows), \
         patch("src.calm.client.get_timeboxes", side_effect=RuntimeError("HTTP 403")):
        msg = _refused(calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                            data={"timebox": "Sprint 5"}))
    assert "values present: ['Sprint 1']" in msg


def test_failed_name_lookup_is_not_reported_as_no_tasks(calm):
    rows = [_row(1, "A", Timebox=None, **{"Timebox ID": "tb1"})]   # name lookup failed
    with patch("src.calm.client.get_tasks", return_value=rows), \
         patch("src.calm.client.get_timeboxes") as gb:
        msg = _refused(calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                            data={"timebox": "Sprint 1", "summarize_by": ["Timebox"]}))
    assert "could not be looked up" in msg and "tb1" in msg
    gb.assert_not_called()


def test_unresolved_label_works_as_a_filter():
    rows = [_row(1, "A", Timebox=None, **{"Timebox ID": "tb1"}), _row(2, "B", Timebox="Sprint 2",
                                                                       **{"Timebox ID": "tb2"})]
    assert [r["ID"] for r in client.filter_tasks(rows, timebox="(unresolved: tb1)")] == ["id-1"]
    assert client.unresolved_filters(rows, timebox="(unresolved: tb1)") == {}


def test_team_filter_classified_against_project_teams(calm):
    rows = [_row(1, "A", **{"Responsible Team": "Finance", "Responsible Team ID": "tf"})]
    teams = [{"ID": "tf", "Name": "Finance"}, {"ID": "to", "Name": "OTC"}]
    with patch("src.calm.client.get_tasks", return_value=rows), \
         patch("src.calm.client.get_project_teams", return_value=teams):
        out = calm(Ctx(), resource="tasks", operation="list", project_id="p1",
                   data={"team": ["Finance", "OTC", "Basis"]})
    entry = out["Filter Values With No Tasks"]["team"]
    assert entry["exist but have no tasks"] == ["OTC"]
    assert entry["not found in the project"] == ["Basis"]
    assert [r["ID"] for r in out["Tasks"]] == ["id-1"]


# --------------------------------------------------------------------------- #
# http_retry: WriteUnconfirmed and TLS classification
# --------------------------------------------------------------------------- #

def _send(script, method="GET", repeatable=True):
    return http_retry.send(script, method, f"{BASE}/api/x?projectId=p", repeatable=repeatable, timeout=30)


def test_dropped_write_raises_write_unconfirmed_with_unchanged_message():
    with pytest.raises(http_retry.WriteUnconfirmed) as err:
        _send(Script(dropped()), "PATCH", repeatable=False)
    assert "may or may not have been applied" in str(err.value)
    assert err.value.reason == "SAP closed the connection without a response"
    assert isinstance(err.value, RuntimeError)


def test_gateway_error_on_write_raises_write_unconfirmed():
    with pytest.raises(http_retry.WriteUnconfirmed) as err:
        _send(Script(Resp(502)), "POST", repeatable=False)
    assert "HTTP 502" in err.value.reason


def _ssl(text):
    return requests.exceptions.SSLError(ssl.SSLError(1, text))


def test_tls_handshake_cut_off_is_retried_on_reads():
    script = Script(_ssl("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"),
                    Resp(200, {"value": []}))
    assert _send(script).status_code == 200 and len(script.calls) == 2


def test_tls_handshake_cut_off_on_a_write_is_unconfirmed():
    with pytest.raises(http_retry.WriteUnconfirmed):
        _send(Script(_ssl("EOF occurred in violation of protocol (_ssl.c:1006)")), "POST", repeatable=False)


@pytest.mark.parametrize("text, code", [
    ("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate",
     "certificate verify failed"),
    ("[SSL: TLSV13_ALERT_CERTIFICATE_REQUIRED] tlsv13 alert certificate required", "TLSV13_ALERT_CERTIFICATE_REQUIRED"),
    ("[SSL: WRONG_VERSION_NUMBER] wrong version number", "WRONG_VERSION_NUMBER"),
])
def test_tls_configuration_failures_are_permanent_and_named(text, code):
    script = Script(_ssl(text))
    with pytest.raises(RuntimeError) as err:
        _send(script)
    assert len(script.calls) == 1
    assert code in str(err.value) and "configuration problem" in str(err.value)
    assert "projectId" not in str(err.value)  # never the query string


# --------------------------------------------------------------------------- #
# Task update: read back, resend once (idempotent)
# --------------------------------------------------------------------------- #

STORED = {"id": "t-1", "title": "Configure GL", "type": "CALMTASK", "dueDate": "2026-11-07",
          "status": "CIPTKOPEN"}


def _update(**kw):
    return client.update_task("tok", "t-1", base_url=BASE, **kw)


def test_update_dropped_but_applied_is_a_success_without_resend():
    write = Script(dropped())
    with patch.object(client.requests, "request", write), \
         patch.object(client, "_get_with_meta", return_value=(STORED, None)):
        out = _update(due_date="2026-11-07")
    assert len(write.calls) == 1
    assert out["DueDate"] == "2026-11-07" and "update was applied" in out["Note"]


def test_update_dropped_and_missing_is_resent_once():
    write = Script(dropped(), Resp(200, dict(STORED, dueDate="2026-11-07")))
    old = dict(STORED, dueDate="2026-10-01")
    with patch.object(client.requests, "request", write), \
         patch.object(client, "_get_with_meta", return_value=(old, None)):
        out = _update(due_date="2026-11-07")
    assert len(write.calls) == 2
    assert write.calls[0][1]["data"] == write.calls[1][1]["data"] == json.dumps({"dueDate": "2026-11-07"})
    assert out["DueDate"] == "2026-11-07" and "sent again and succeeded" in out["Note"]


def test_update_dropped_twice_and_missing_says_not_applied_and_safe():
    write = Script(dropped(), dropped())
    old = dict(STORED, dueDate="2026-10-01")
    with patch.object(client.requests, "request", write), \
         patch.object(client, "_get_with_meta", return_value=(old, None)), \
         pytest.raises(RuntimeError) as err:
        _update(due_date="2026-11-07")
    msg = str(err.value)
    assert "both attempts" in msg and "NOT applied" in msg and "Retrying is safe" in msg
    assert "may or may not" not in msg


def test_update_resent_even_when_read_back_fails():
    write = Script(dropped(), Resp(204))
    with patch.object(client.requests, "request", write), \
         patch.object(client, "_get_with_meta", side_effect=RuntimeError("HTTP 500")):
        out = _update(due_date="2026-11-07")
    assert len(write.calls) == 2 and out["updated"] == "t-1" and "Note" in out


def test_update_slow_first_attempt_is_sent_again():
    # SAP held it 40s before dropping (slow tenants: 18-31s). An update only
    # sets values, so sending it again is safe even if the first still lands.
    clock = iter([0.0, 40.0, 40.0, 40.0])
    write = Script(dropped(), Resp(200, dict(STORED, dueDate="2026-11-07")))
    old = dict(STORED, dueDate="2026-10-01")
    with patch.object(client.requests, "request", write), \
         patch.object(http_retry, "_clock", lambda: next(clock, 40.0)), \
         patch.object(client, "_get_with_meta", return_value=(old, None)):
        out = _update(due_date="2026-11-07")
    assert len(write.calls) == 2 and "sent again" in out["Note"]


def test_update_dropped_twice_is_reported_honestly():
    clock = iter([0.0, 40.0, 40.0, 40.0])
    write = Script(dropped(), dropped())
    old = dict(STORED, dueDate="2026-10-01")
    with patch.object(client.requests, "request", write), \
         patch.object(http_retry, "_clock", lambda: next(clock, 40.0)), \
         patch.object(client, "_get_with_meta", return_value=(old, None)), \
         pytest.raises(RuntimeError) as err:
        _update(due_date="2026-11-07")
    msg = str(err.value)
    assert len(write.calls) == 2 and "both attempts" in msg and "Retrying is safe" in msg


def test_update_second_attempt_rejected_but_first_landed():
    write = Script(dropped(), Resp(400, {"message": "status transition not allowed"}))
    reads = iter([(dict(STORED, status="CIPTKOPEN"), None), (dict(STORED, status="CIPTKCLOSE"), None)])
    with patch.object(client.requests, "request", write), \
         patch.object(client, "_get_with_meta", side_effect=lambda *a: next(reads)):
        out = _update(status="CIPTKCLOSE")
    assert "update was applied" in out["Note"]


def test_update_unconfirmable_field_difference_is_not_called_missing():
    write = Script(dropped(), dropped())
    stored = dict(STORED, description="<p>New text</p>")
    with patch.object(client.requests, "request", write), \
         patch.object(client, "_get_with_meta", return_value=(stored, None)), \
         pytest.raises(RuntimeError) as err:
        _update(description="New text")
    assert "could not be read back to confirm" in str(err.value)


# --------------------------------------------------------------------------- #
# Task create: find it in the project, resend only when proven absent
# --------------------------------------------------------------------------- #

NOW = 1_800_000_000.0  # time.time() at the first attempt


def _iso(epoch):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.123456700Z")


def _task(i, title="RAID: legacy lookup", created=NOW + 1, **kw):
    t = {"id": f"new-{i}", "title": title, "type": "CALMTASK", "createdTimestamp": _iso(created)}
    t.update(kw)
    return t


def _create(listings, writes):
    lists = iter(listings)

    def get_all(url, token):
        out = next(lists)
        if isinstance(out, Exception):
            raise out
        assert "projectId=p1" in url and "type=CALMTASK" in url
        return out

    with patch.object(client.requests, "request", writes), \
         patch.object(client, "_get_all", side_effect=get_all), \
         patch.object(client.time, "time", return_value=NOW):
        return client.create_task("tok", "p1", "RAID: legacy lookup", "Project Task", base_url=BASE)


def test_create_dropped_but_created_returns_the_task_without_resend():
    writes = Script(dropped())
    out = _create([[_task(1), _task(2, title="Other")]], writes)
    assert len(writes.calls) == 1 and out["ID"] == "new-1" and "was created" in out["Note"]


def test_create_dropped_and_absent_is_sent_once_more():
    writes = Script(dropped(), Resp(201, _task(9)))
    old_same_title = _task(0, created=NOW - 3600)   # an hour old: not this create
    out = _create([[old_same_title]], writes)
    assert len(writes.calls) == 2 and out["ID"] == "new-9"
    assert "created once" in out["Note"]


def test_create_dropped_twice_and_absent_is_definite():
    writes = Script(dropped(), dropped())
    with pytest.raises(RuntimeError) as err:
        _create([[], []], writes)
    msg = str(err.value)
    assert "both attempts" in msg and "NOT created" in msg and "may or may not" not in msg


def test_create_dropped_twice_second_landed():
    writes = Script(dropped(), dropped())
    out = _create([[], [_task(3)]], writes)
    assert out["ID"] == "new-3"


def test_create_two_recent_matches_is_flagged_not_guessed():
    writes = Script(dropped())
    with pytest.raises(RuntimeError) as err:
        _create([[_task(1), _task(2)]], writes)
    assert "new-1" in str(err.value) and "new-2" in str(err.value) and len(writes.calls) == 1


def test_create_unreadable_project_keeps_the_unconfirmed_error():
    writes = Script(dropped())
    with pytest.raises(http_retry.WriteUnconfirmed):
        _create([RuntimeError("HTTP 503")], writes)
    assert len(writes.calls) == 1


def test_create_unparseable_timestamp_on_same_title_is_not_resent():
    writes = Script(dropped())
    with pytest.raises(http_retry.WriteUnconfirmed):
        _create([[_task(1, createdTimestamp="yesterday")]], writes)
    assert len(writes.calls) == 1


def test_create_partial_listing_is_inconclusive_and_raises_no_alert():
    writes = Script(dropped())
    sink, token = client.install_truncation_sink()
    try:
        def truncated(url, tok):
            client._record_truncation(url, 10, "max-rows")
            return []
        with patch.object(client.requests, "request", writes), \
             patch.object(client, "_get_all", side_effect=truncated), \
             patch.object(client.time, "time", return_value=NOW), \
             pytest.raises(http_retry.WriteUnconfirmed):
            client.create_task("tok", "p1", "RAID: legacy lookup", "Project Task", base_url=BASE)
    finally:
        client.reset_truncation_sink(token)
    assert sink == [] and len(writes.calls) == 1


def test_create_slow_first_attempt_is_not_resent():
    clock = iter([0.0, 40.0])
    writes = Script(dropped())
    with patch.object(http_retry, "_clock", lambda: next(clock, 40.0)), pytest.raises(RuntimeError) as err:
        _create([[]], writes)
    # Production: a create dropped after 18s. It may still land, so it must
    # not be re-sent nor called "not created".
    msg = str(err.value)
    assert len(writes.calls) == 1 and "may still be finishing" in msg
    assert "Do NOT create it again yet" in msg and "NOT created" not in msg


def test_create_slow_drop_waits_longer_before_looking(no_sleep):
    clock = iter([0.0, 0.0, 18.0])
    writes = Script(dropped())
    with patch.object(http_retry, "_clock", lambda: next(clock, 18.0)), pytest.raises(RuntimeError):
        _create([[]], writes)
    assert no_sleep == [client.SLOW_WRITE_SETTLE]


def test_create_slow_drop_that_landed_is_found():
    clock = iter([0.0, 0.0, 18.0])
    writes = Script(dropped())
    with patch.object(http_retry, "_clock", lambda: next(clock, 18.0)):
        out = _create([[_task(1)]], writes)
    assert out["ID"] == "new-1" and len(writes.calls) == 1


def test_create_second_attempt_slow_drop_is_not_called_not_created():
    times = iter([0.0, 0.0, 1.0, 1.0, 1.0, 30.0])
    writes = Script(dropped(), dropped())
    with patch.object(http_retry, "_clock", lambda: next(times, 30.0)), pytest.raises(RuntimeError) as err:
        _create([[], []], writes)
    assert len(writes.calls) == 2 and "may still be finishing" in str(err.value)


def test_subtask_matches_only_under_its_parent():
    writes = Script(dropped(), Resp(201, _task(7, parentId="par-1")))
    lists = iter([[_task(1, parentId="par-OTHER")]])
    with patch.object(client.requests, "request", writes), \
         patch.object(client, "_get_all", side_effect=lambda *a: next(lists)), \
         patch.object(client.time, "time", return_value=NOW):
        out = client.create_task("tok", "p1", "RAID: legacy lookup", "Project Task",
                                 parent_id="par-1", base_url=BASE)
    assert out["ID"] == "new-7" and len(writes.calls) == 2


def test_timestamps_parse_with_nanoseconds_and_offsets():
    assert client._ts_epoch("2026-04-22T12:18:26.311368800Z") == client._ts_epoch("2026-04-22T14:18:26+02:00")
    assert client._ts_epoch("not a date") is None and client._ts_epoch(None) is None


# --------------------------------------------------------------------------- #
# Rich text, TM credential host, entity-set cache
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("given, expected", [
    ("Enter <Code> for <Table Name>", "Enter <Code> for <Table Name>"),
    ("Ask <HR Manager> to approve", "Ask <HR Manager> to approve"),
    ("Log on to <S/4HANA system>", "Log on to <S/4HANA system>"),
    ("Post <Line Item> 1", "Post <Line Item> 1"),
    ('<p><span style="color:red">Save</span> <a href="https://x">link</a></p>', "Save link"),
    ("<p>A</p><hr/><p>B</p>", "A\nB"),
    ("<table><tr><td colspan=2>X</td></tr></table>", "X"),
])
def test_rich_text_placeholders_survive_round_2(given, expected):
    assert client._rich_text_to_plain(given) == expected


class TMCtx:
    def __init__(self, headers):
        class R:
            pass
        req = R()
        req.headers = headers
        rc = R()
        rc.request = req
        self.request_context = rc


@pytest.fixture
def tm_env(monkeypatch):
    monkeypatch.setenv("TM_BASE_URL", "https://own-tm.example.com/")
    monkeypatch.setenv("TM_TOKEN", "server-tm-token")
    for k in ("TM_CLIENT_ID", "TM_CLIENT_SECRET", "TM_TOKEN_URL"):
        monkeypatch.delenv(k, raising=False)


def test_server_tm_credential_never_goes_to_a_caller_host(tm_env):
    from src.calm.tm_dependencies import get_tm_headers
    with pytest.raises(ValueError, match="other than the server's own"):
        get_tm_headers(TMCtx({"x-tm-base-url": "https://attacker.example.com"}))


def test_server_tm_credential_still_used_for_its_own_host(tm_env):
    from src.calm.tm_dependencies import get_tm_headers
    assert get_tm_headers(TMCtx({})).token == "server-tm-token"
    same = get_tm_headers(TMCtx({"x-tm-base-url": "https://own-tm.example.com"}))
    assert same.token == "server-tm-token"


def test_entity_set_cache_is_bounded():
    client._TM_ENTITY_SETS.clear()
    try:
        with patch.object(client, "_get", return_value={"value": [{"url": "TestPlans"}]}):
            for i in range(client._TM_ENTITY_SETS_MAX + 20):
                client._tm_entity_sets(f"https://t{i}.example.com", "tok")
        assert len(client._TM_ENTITY_SETS) == client._TM_ENTITY_SETS_MAX
        assert "https://t0.example.com" not in client._TM_ENTITY_SETS
    finally:
        client._TM_ENTITY_SETS.clear()


def test_no_plan_set_answer_is_rechecked_next_call():
    client._TM_ENTITY_SETS.clear()
    services = iter([{"value": [{"url": "ManualTestCases"}]},
                     {"value": [{"url": "ManualTestCases"}, {"url": "TestPlans"}]}])
    try:
        with patch.object(client, "_get", side_effect=lambda *a: next(services)), \
             patch.object(client, "_get_all", return_value=[{"uuid": "p", "title": "Plan"}]):
            first = client.get_test_plans("tok", base_url=BASE)
            second = client.get_test_plans("tok", base_url=BASE)
        assert first["status"] == "unavailable"
        assert second == [{"ID": "p", "Title": "Plan"}]
    finally:
        client._TM_ENTITY_SETS.clear()


# --------------------------------------------------------------------------- #
# tasks get — the agent's read-back after a dropped update (trace: 5x "Use
# operation='list'") now works
# --------------------------------------------------------------------------- #

TASK_UUID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def test_get_task_by_uuid_resolves_names():
    raw = {"id": TASK_UUID, "projectId": "p1", "title": "Configure GL", "type": "CALMTASK",
           "responsibleTeamId": "tf", "timeboxId": "tb1"}
    with patch.object(client, "_get", return_value=raw) as g, \
         patch.object(client, "get_project_teams", return_value=[{"ID": "tf", "Name": "Finance"}]), \
         patch.object(client, "get_timeboxes", return_value=[{"ID": "tb1", "Name": "Sprint 1"}]):
        row = client.get_task("tok", TASK_UUID, BASE)
    assert g.call_args.args[0] == f"{BASE}/api/calm-tasks/v1/tasks/{TASK_UUID}"
    assert row["ID"] == TASK_UUID and row["Responsible Team"] == "Finance" and row["Timebox"] == "Sprint 1"
    assert list(row) == list(client.TASK_FIELDS)


def test_get_task_by_display_id_needs_and_uses_the_project():
    rows = [_row(1, "A"), _row(2, "B", **{"External ID (FRICEF)": "FIN-1"})]
    with pytest.raises(ValueError, match="pass project_id"):
        client.get_task("tok", "3-2", BASE)
    with patch.object(client, "get_tasks", return_value=rows):
        assert client.get_task("tok", "3-2", BASE, project_id="p1")["ID"] == "id-2"
        assert client.get_task("tok", "fin-1", BASE, project_id="p1")["ID"] == "id-2"
        with pytest.raises(ValueError, match="No task"):
            client.get_task("tok", "3-99", BASE, project_id="p1")


def test_get_task_ambiguous_display_id_lists_candidates():
    rows = [_row(1, "A", **{"Display ID": "X-1"}), _row(2, "B", **{"External ID (FRICEF)": "X-1"})]
    with patch.object(client, "get_tasks", return_value=rows), pytest.raises(ValueError) as err:
        client.get_task("tok", "X-1", BASE, project_id="p1")
    assert "id-1" in str(err.value) and "id-2" in str(err.value)


def test_tasks_get_through_calm_resource(calm):
    raw = {"id": TASK_UUID, "projectId": "11111111-1111-1111-1111-111111111111",
           "title": "Configure GL", "type": "CALMTASK"}
    with patch.object(client, "_get", return_value=raw):
        row = calm(Ctx(), resource="tasks", operation="get",
                   project_id="11111111-1111-1111-1111-111111111111", resource_id=TASK_UUID)
    assert row["ID"] == TASK_UUID and row["Title"] == "Configure GL"
    _refused(calm(Ctx(), resource="tasks", operation="get", project_id="p1"), "resource_id is required")


def _refused(out, match=""):
    """A read the MCP can't run as asked: an answer saying why, not a tool error."""
    assert isinstance(out, dict) and out.get("status") == "invalid_request", out
    assert re.search(match, out["message"]), out["message"]
    return out["message"]
