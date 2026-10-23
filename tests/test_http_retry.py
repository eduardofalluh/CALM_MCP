"""Tests for transient-failure handling and snake_case extra_fields.

Reproduces a production failure seen in an agent trace (2026-10-23): a task
create failed with ``('Connection aborted.', RemoteDisconnected('Remote end
closed connection without response'))`` — the MCP had no retry and surfaced the
raw exception. Same trace: the agent sent ``extra_fields={"scope_id": ...}``,
which CALM does not know (its field is ``scopeId``).

Pins the policy in src/calm/http_retry.py:
- reads (and the token POST) retry dropped connections / timeouts / 502-504 / 429;
- writes never repeat once the request may have reached SAP (duplicate risk),
  only when nothing was sent or on 429;
- failures read as plain English, never a raw exception tuple.
No network and no real sleeps.
"""

from __future__ import annotations

import asyncio
import http.client
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from urllib3.exceptions import MaxRetryError, NewConnectionError, ProtocolError

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client, http_retry, tm_client  # noqa: E402

BASE = "https://x.alm.cloud.sap"


def dropped():
    """Exactly what requests raises for the production failure."""
    return requests.exceptions.ConnectionError(ProtocolError(
        "Connection aborted.", http.client.RemoteDisconnected("Remote end closed connection without response")))


def refused():
    """Connection never established — nothing was sent."""
    return requests.exceptions.ConnectionError(MaxRetryError(
        None, "/x", reason=NewConnectionError(None, "Failed to establish a new connection")))


class Resp:
    def __init__(self, status=200, text='{"value": []}', headers=None):
        self.status_code = status
        self.text = text
        self.reason = "OK" if status < 400 else "Error"
        self.headers = headers or {}

    def json(self):
        import json
        return json.loads(self.text)


class Script:
    """A fake requests function that plays back a sequence of results."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture(autouse=True)
def no_sleep():
    sleeps = []
    with patch.object(http_retry, "_sleep", sleeps.append):
        yield sleeps


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #

def test_read_recovers_from_a_dropped_connection(no_sleep):
    s = Script(dropped(), Resp(text='{"ok": 1}'))
    with patch("src.calm.client.requests.get", s):
        assert client._get(f"{BASE}/api/calm-projects/v1/projects", "tok") == {"ok": 1}
    assert s.calls == 2 and no_sleep == [1.0]


def test_read_gives_up_after_three_attempts_with_a_readable_message(no_sleep):
    s = Script(dropped(), dropped(), dropped())
    with patch("src.calm.client.requests.get", s):
        with pytest.raises(RuntimeError) as err:
            client._get(f"{BASE}/api/calm-tasks/v1/tasks?projectId=p1", "tok")
    msg = str(err.value)
    assert s.calls == 3 and no_sleep == [1.0, 3.0]
    assert "SAP closed the connection without a response" in msg
    assert "tried 3 times" in msg and "nothing was changed" in msg
    assert "RemoteDisconnected(" not in msg and "Connection aborted" not in msg
    assert "projectId" not in msg  # path only, no query string


@pytest.mark.parametrize("status", [502, 503, 504, 429])
def test_read_retries_gateway_errors(status):
    s = Script(Resp(status, "busy"), Resp(text='{"ok": 2}'))
    with patch("src.calm.client.requests.get", s):
        assert client._get(f"{BASE}/api/x", "tok") == {"ok": 2}
    assert s.calls == 2


def test_read_persistent_503_still_reports_the_http_status():
    s = Script(Resp(503, "down"), Resp(503, "down"), Resp(503, "down"))
    with patch("src.calm.client.requests.get", s):
        with pytest.raises(RuntimeError, match="HTTP 503"):
            client._get(f"{BASE}/api/x", "tok")
    assert s.calls == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 412, 500])
def test_read_does_not_retry_definite_errors(status):
    s = Script(Resp(status, "nope"))
    with patch("src.calm.client.requests.get", s):
        with pytest.raises(RuntimeError, match=f"HTTP {status}"):
            client._get(f"{BASE}/api/x", "tok")
    assert s.calls == 1


def test_read_timeout_is_retried():
    s = Script(requests.exceptions.ReadTimeout("timed out"), Resp(text='{"ok": 3}'))
    with patch("src.calm.client.requests.get", s):
        assert client._get(f"{BASE}/api/x", "tok") == {"ok": 3}


def test_retry_after_header_is_honoured_but_capped(no_sleep):
    s = Script(Resp(429, "", {"Retry-After": "2"}), Resp(429, "", {"Retry-After": "600"}), Resp(text="{}"))
    with patch("src.calm.client.requests.get", s):
        client._get(f"{BASE}/api/x", "tok")
    assert no_sleep == [2.0, http_retry.MAX_RETRY_AFTER]


def test_deadline_stops_further_attempts():
    clock = iter([0.0, 0.0, 100.0, 100.0])
    s = Script(dropped(), dropped(), Resp())
    with patch.object(http_retry, "_clock", lambda: next(clock)), \
         patch("src.calm.client.requests.get", s):
        with pytest.raises(RuntimeError, match="tried 2 times"):
            client._get(f"{BASE}/api/x", "tok")
    assert s.calls == 2


def test_etag_read_is_retried():
    s = Script(dropped(), Resp(text='{"id": "x"}', headers={"ETag": 'W/"1"'}))
    with patch("src.calm.client.requests.get", s):
        assert client._get_with_meta(f"{BASE}/api/x/1", "tok") == ({"id": "x"}, 'W/"1"')


# --------------------------------------------------------------------------- #
# Writes — never duplicate
# --------------------------------------------------------------------------- #

def test_create_is_not_repeated_after_a_drop_and_says_how_to_recover(no_sleep):
    """The exact production failure: POST /tasks, connection dropped."""
    s = Script(dropped(), Resp(201, '{"id": "dup"}'))
    with patch("src.calm.client.requests.request", s):
        with pytest.raises(RuntimeError) as err:
            client._write("POST", f"{BASE}/api/calm-tasks/v1/tasks", "tok", {"title": "x"})
    msg = str(err.value)
    assert s.calls == 1 and no_sleep == []  # a second POST could create a duplicate
    assert "may or may not have been applied" in msg and "duplicate" in msg
    assert "POST /api/calm-tasks/v1/tasks" in msg
    assert "RemoteDisconnected(" not in msg


def test_create_is_retried_when_nothing_was_sent():
    s = Script(refused(), Resp(201, '{"id": "t1"}'))
    with patch("src.calm.client.requests.request", s):
        assert client._write("POST", f"{BASE}/api/calm-tasks/v1/tasks", "tok", {"title": "x"}) == {"id": "t1"}
    assert s.calls == 2


def test_create_connect_timeout_is_retried():
    s = Script(requests.exceptions.ConnectTimeout("connect"), Resp(201, '{"id": "t2"}'))
    with patch("src.calm.client.requests.request", s):
        assert client._write("POST", f"{BASE}/api/x", "tok", {})["id"] == "t2"


def test_create_429_is_retried():
    s = Script(Resp(429, ""), Resp(201, '{"id": "t3"}'))
    with patch("src.calm.client.requests.request", s):
        assert client._write("POST", f"{BASE}/api/x", "tok", {})["id"] == "t3"


@pytest.mark.parametrize("status", [502, 503, 504])
def test_create_5xx_is_not_repeated(status):
    s = Script(Resp(status, "gateway"), Resp(201, "{}"))
    with patch("src.calm.client.requests.request", s):
        with pytest.raises(RuntimeError, match=f"HTTP {status}"):
            client._write("POST", f"{BASE}/api/x", "tok", {})
    assert s.calls == 1


def test_create_read_timeout_is_not_repeated():
    s = Script(requests.exceptions.ReadTimeout("slow"), Resp(201, "{}"))
    with patch("src.calm.client.requests.request", s):
        with pytest.raises(RuntimeError, match="may or may not"):
            client._write("POST", f"{BASE}/api/x", "tok", {})
    assert s.calls == 1


@pytest.mark.parametrize("method", ["PATCH"])
def test_update_drop_is_not_repeated(method):
    s = Script(dropped(), Resp(200, "{}"))
    with patch("src.calm.client.requests.request", s):
        with pytest.raises(RuntimeError, match="may or may not"):
            client._write(method, f"{BASE}/api/x/1", "tok", {"a": 1})
    assert s.calls == 1


def test_delete_drop_is_not_repeated():
    s = Script(dropped(), Resp(204, ""))
    with patch("src.calm.client.requests.request", s):
        with pytest.raises(RuntimeError, match="may or may not"):
            client._delete(f"{BASE}/api/x/1", "tok")
    assert s.calls == 1


def test_successful_writes_unchanged():
    s = Script(Resp(201, '{"id": "ok"}'))
    with patch("src.calm.client.requests.request", s):
        assert client._write("POST", f"{BASE}/api/x", "tok", {"t": 1}) == {"id": "ok"}
    s = Script(Resp(204, ""))
    with patch("src.calm.client.requests.request", s):
        assert client._delete(f"{BASE}/api/x/1", "tok") == {}


# --------------------------------------------------------------------------- #
# Token POST and Test Management client
# --------------------------------------------------------------------------- #

def test_token_request_is_retried_after_a_drop():
    from src.calm.token_manager import TokenManager

    s = Script(dropped(), Resp(200, '{"access_token": "abc", "expires_in": 3600}'))
    with patch("src.calm.token_manager.requests.post", s):
        tm = TokenManager("cid", "secret-value", auth_url="https://z.authentication.us10.hana.ondemand.com/oauth/token")
        assert tm.get_token() == "abc"
    assert s.calls == 2


def test_tm_client_read_is_retried():
    s = Script(dropped(), Resp(text='{"value": [{"id": "TC-1"}]}'))
    with patch("src.calm.tm_client.requests.get", s):
        out = tm_client.odata_read("tok", "https://tm.example.com/odata/v4/test-management", "TestCases")
    assert s.calls == 2 and "TC-1" in str(out)


def test_tm_client_write_drop_is_not_repeated():
    s = Script(dropped(), Resp(201, "{}"))
    with patch("src.calm.tm_client.requests.request", s):
        with pytest.raises(RuntimeError, match="may or may not"):
            tm_client.odata_write("tok", "https://tm.example.com/odata/v4/test-management",
                                  "POST", "TestCases", {"title": "x"})
    assert s.calls == 1


# --------------------------------------------------------------------------- #
# snake_case extra_fields
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("given, sent", [
    ({"scope_id": "S1"}, {"scopeId": "S1"}),
    ({"story_points": 5, "custom_field_1": "x"}, {"storyPoints": 5, "customField1": "x"}),
    ({"scopeId": "camel", "scope_id": "snake"}, {"scopeId": "camel"}),
    ({"subStatus": "A", "workstream": "WS1"}, {"subStatus": "A", "workstream": "WS1"}),
])
def test_api_field_names(given, sent):
    assert client._api_field_names(given) == sent


def test_task_create_sends_scope_id_as_scopeId():
    captured = {}

    def fake_write(method, url, token, body, **kw):
        captured.update(body)
        return {"id": "T1", "title": body["title"], "type": body["type"]}

    with patch("src.calm.client._write", fake_write):
        client.create_task("tok", "p1", "Risk A", "Project Task",
                           extra_fields={"scope_id": "0f0e0d0c"}, base_url=BASE)
    assert captured["scopeId"] == "0f0e0d0c" and "scope_id" not in captured


# --------------------------------------------------------------------------- #
# The production trace, end to end through calm_resource
# --------------------------------------------------------------------------- #

class Ctx:
    """No request_context — credentials come from env."""


def test_trace_replay_through_calm_resource(monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", "tok")
    monkeypatch.setenv("CALM_BASE_URL", BASE)
    monkeypatch.setenv("CALM_ENABLE_WRITES", "true")
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("t")
    register(mcp)
    fn = asyncio.run(mcp.get_tool("calm_resource")).fn

    posts = Script(dropped())
    bodies = []

    def request(method, url, **kw):
        bodies.append(kw.get("data"))
        return posts()

    with patch("src.calm.client.requests.request", request), \
         patch("src.calm.tools.unified.resolve_assignee", lambda **kw: "user-uuid"):
        with pytest.raises(RuntimeError) as err:
            fn(Ctx(), resource="tasks", operation="create", project_id="p1", data={
                "title": "RAID risk: configuration may be inconsistent",
                "task_type": "Project Task", "status": "Open",
                "assignee_id": "someone@example.com",
                "description": "<p>RAID Type: Risk</p>",
                "extra_fields": {"scope_id": "0f0e0d0c-0000-4000-8000-000000000001"},
            })
    assert posts.calls == 1, "a create must not be sent twice"
    assert '"scopeId": "0f0e0d0c-0000-4000-8000-000000000001"' in bodies[0]
    assert '"scope_id"' not in bodies[0]
    assert "may or may not have been applied" in str(err.value)


# --------------------------------------------------------------------------- #
# Review round 1 (stx deep review) fixes
# --------------------------------------------------------------------------- #

def tls_error():
    return requests.exceptions.SSLError(
        "HTTPSConnectionPool(host='x', port=443): Max retries exceeded (Caused by SSLError("
        "SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
        "unable to get local issuer certificate (_ssl.c:1006)')))")


def test_tls_failure_is_not_retried_and_names_the_cause(no_sleep):
    s = Script(tls_error(), Resp())
    with patch("src.calm.client.requests.get", s):
        with pytest.raises(RuntimeError) as err:
            client._get(f"{BASE}/api/x", "tok")
    msg = str(err.value)
    assert s.calls == 1 and no_sleep == []
    assert "TLS error" in msg and "unable to get local issuer certificate" in msg
    assert "temporary" not in msg.replace("not a temporary one", "")


@pytest.mark.parametrize("status", [502, 503, 504])
def test_write_gateway_error_warns_it_may_have_been_applied(status):
    s = Script(Resp(status, "gateway"))
    with patch("src.calm.client.requests.request", s):
        with pytest.raises(RuntimeError) as err:
            client._write("POST", f"{BASE}/api/calm-tasks/v1/tasks", "tok", {"title": "x"})
    assert s.calls == 1
    assert f"HTTP {status}" in str(err.value) and "may or may not have been applied" in str(err.value)


@pytest.mark.parametrize("header", ["-5", "nan", "inf", "Wed, 21 Oct 2026 07:28:00 GMT", ""])
def test_bad_retry_after_values_never_crash(header, no_sleep):
    s = Script(Resp(429, "", {"Retry-After": header}), Resp(text='{"ok": 1}'))
    with patch("src.calm.client.requests.get", s):
        assert client._get(f"{BASE}/api/x", "tok") == {"ok": 1}
    assert no_sleep and all(0 <= d <= http_retry.MAX_RETRY_AFTER for d in no_sleep)


def test_deadline_is_enforced_with_slow_attempts():
    """Each attempt burns its full timeout: the call must still end near DEADLINE."""
    now = [0.0]
    timeouts = []

    def slow(*a, timeout=None, **kw):
        timeouts.append(timeout)
        now[0] += timeout  # the attempt uses its whole timeout, then fails
        raise requests.exceptions.ReadTimeout("slow")

    with patch.object(http_retry, "_clock", lambda: now[0]), \
         patch.object(http_retry, "_sleep", lambda d: now.__setitem__(0, now[0] + d)), \
         patch("src.calm.client.requests.get", slow):
        with pytest.raises(RuntimeError, match="tried 2 times"):
            client._get(f"{BASE}/api/x", "tok")
    assert timeouts[0] == client.REQUEST_TIMEOUT
    assert timeouts[1] <= http_retry.DEADLINE - client.REQUEST_TIMEOUT - http_retry.BACKOFF[0]
    assert now[0] <= http_retry.DEADLINE + 1


def test_no_retry_starts_without_enough_time_left():
    now = [0.0]

    def slow(*a, timeout=None, **kw):
        now[0] += 41  # leaves 45 - 41 - 1 = 3s < MIN_ATTEMPT
        raise requests.exceptions.ReadTimeout("slow")

    with patch.object(http_retry, "_clock", lambda: now[0]), \
         patch.object(http_retry, "_sleep", lambda d: None), \
         patch("src.calm.client.requests.get", slow) as _:
        with pytest.raises(RuntimeError, match="tried 1 times"):
            client._get(f"{BASE}/api/x", "tok")


def test_best_effort_is_one_short_attempt(no_sleep):
    seen = []

    def drop(*a, timeout=None, **kw):
        seen.append(timeout)
        raise dropped()

    with patch("src.calm.client.requests.get", drop):
        with http_retry.best_effort():
            with pytest.raises(RuntimeError, match="tried 1 times"):
                client._get(f"{BASE}/api/x", "tok")
        # outside the block the normal policy is back
        with pytest.raises(RuntimeError, match="tried 3 times"):
            client._get(f"{BASE}/api/x", "tok")
    assert seen[0] == http_retry.BEST_EFFORT_TIMEOUT and len(seen) == 4


def test_tm_client_calls_are_bounded_too():
    now = [0.0]

    def slow(*a, timeout=None, **kw):
        now[0] += timeout
        raise requests.exceptions.ReadTimeout("slow")

    with patch.object(http_retry, "_clock", lambda: now[0]), \
         patch.object(http_retry, "_sleep", lambda d: now.__setitem__(0, now[0] + d)), \
         patch("src.calm.tm_client.requests.get", slow):
        with pytest.raises(RuntimeError):
            tm_client.odata_read("tok", "https://tm.example.com/odata/v4/test-management", "TestCases")
    # TM's own 60 s timeout: one attempt, no second one started past the deadline.
    assert now[0] <= max(tm_client.REQUEST_TIMEOUT, http_retry.DEADLINE) + 1
