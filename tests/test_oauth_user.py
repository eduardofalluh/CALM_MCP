"""OAuth (a person's own SAP sign-in) next to the service-key connection.

With OAuth the person's token goes to CALM, so CALM records that person (history,
comment author, creator) — even when a service key is also configured. A service
key alone, or an Authorization header that isn't a person's SAP token, works as
before. On a service-key connection CALM shows "API", so a comment names the
person using the agent itself. Tokens here are fake; names are made up.
"""
import base64
import json
from types import SimpleNamespace

import pytest

from src.calm.dependencies import get_calm_headers, signed_in_person
from src.calm.tools.unified import _added_by


def _jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


PERSON = _jwt({"grant_type": "authorization_code", "user_name": "jane.doe@example.com",
               "given_name": "Jane", "family_name": "Doe", "email": "jane.doe@example.com",
               "scope": ["x.calm-api.tasks.read"]})
SERVICE = _jwt({"grant_type": "client_credentials", "client_id": "sb-calm", "scope": []})


def _ctx(headers: dict):
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers=headers)))


@pytest.fixture(autouse=True)
def _tenant(monkeypatch):
    monkeypatch.setenv("CALM_BASE_URL", "https://tenant.eu10.alm.cloud.sap")
    monkeypatch.setenv("CALM_AUTH_URL", "https://tenant.authentication.eu10.hana.ondemand.com")
    monkeypatch.delenv("CALM_MULTI_TENANT", raising=False)
    monkeypatch.delenv("CALM_USER_EMAIL", raising=False)


def test_signed_in_person_reads_only_a_persons_sap_token():
    assert signed_in_person(PERSON) == "Jane Doe"
    assert signed_in_person(_jwt({"grant_type": "authorization_code", "user_name": "u1",
                                  "email": "u1@example.com"})) == "u1@example.com"
    assert signed_in_person(SERVICE) is None
    assert signed_in_person(_jwt({"user_name": "no-grant"})) is None  # not an SAP sign-in
    assert signed_in_person("not-a-jwt") is None
    assert signed_in_person(None) is None


def test_persons_token_wins_over_the_server_service_key(monkeypatch):
    monkeypatch.setattr("src.calm.dependencies.get_managed_token", lambda: "service-key-token")
    h = get_calm_headers(_ctx({"Authorization": f"Bearer {PERSON}"}))
    assert h.token == PERSON and h.token_source == "signed-in user (OAuth)" and h.signed_in_user == "Jane Doe"


def test_persons_token_wins_over_header_client_credentials(monkeypatch):
    def no_manager(*_a, **_k):
        raise AssertionError("the service key must not be used when the person signed in")
    monkeypatch.setattr("src.calm.dependencies.get_or_create_token_manager", no_manager)
    h = get_calm_headers(_ctx({"Authorization": f"Bearer {PERSON}", "x-calm-client-id": "id",
                               "x-calm-client-secret": "secret"}))
    assert h.token == PERSON and h.signed_in_user == "Jane Doe"


def test_service_key_connection_is_unchanged(monkeypatch):
    monkeypatch.setattr("src.calm.dependencies.get_managed_token", lambda: "service-key-token")
    for headers in ({}, {"Authorization": f"Bearer {SERVICE}"}, {"Authorization": "Bearer studio-opaque"}):
        h = get_calm_headers(_ctx(headers))
        assert h.token == "service-key-token" and h.token_source == "client_credentials"
        assert h.signed_in_user is None


def test_plain_bearer_without_a_service_key_is_unchanged(monkeypatch):
    monkeypatch.setattr("src.calm.dependencies.get_managed_token", lambda: None)
    h = get_calm_headers(_ctx({"Authorization": "Bearer studio-opaque"}))
    assert h.token == "studio-opaque" and h.token_source == "Authorization header" and h.signed_in_user is None


def test_comment_names_the_person_only_when_calm_cant():
    assert _added_by("Looks good.", None, "jane.doe@example.com") == "Looks good.\n\nAdded by Jane Doe via AI agent"
    assert _added_by("<p>Looks good.</p>", None, "jane.doe@example.com") == \
        "<p>Looks good.</p><p>Added by Jane Doe via AI agent</p>"
    assert _added_by("ok", None, "jdoe@example.com").endswith("Added by jdoe@example.com via AI agent")
    assert _added_by("ok", None, "Jane Doe").endswith("Added by Jane Doe via AI agent")
    assert _added_by("ok", "Jane Doe", "jane.doe@example.com") == "ok"  # OAuth: CALM shows the author
    assert _added_by("ok", None, None) == "ok"  # nobody known: nothing invented
    assert _added_by(None, None, "jane.doe@example.com") is None
    once = _added_by("ok", None, "jane.doe@example.com")
    assert _added_by(once, None, "jane.doe@example.com") == once
    # the agent's own attribution comment already names the person: not named twice
    own = "Task created via Project Agent by Jane Doe."
    assert _added_by(own, None, "jane.doe@example.com") == own


def test_health_says_who_calm_records(monkeypatch):
    from fastmcp import FastMCP
    from src.calm.tools import health
    monkeypatch.setattr("src.calm.dependencies.get_managed_token", lambda: "service-key-token")
    monkeypatch.setattr("src.calm.tools.health.get_managed_token", lambda: "service-key-token")
    mcp = FastMCP("t")
    captured = {}
    orig = mcp.tool
    def grab(*a, **k):
        def deco(fn):
            captured[fn.__name__] = fn
            return orig(*a, **k)(fn)
        return deco
    monkeypatch.setattr(mcp, "tool", grab)
    health.register(mcp)
    out = captured["calm_health"](_ctx({"Authorization": f"Bearer {PERSON}"}))
    assert out["token_source"] == "signed-in user (OAuth)" and out["changes_recorded_as"].startswith("Jane Doe")
    assert PERSON not in json.dumps(out)
    out = captured["calm_health"](_ctx({}))
    assert out["token_source"] == "client_credentials" and "API" in out["changes_recorded_as"]
