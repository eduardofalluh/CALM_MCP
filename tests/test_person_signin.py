"""A client where each person signs in with its own SAP login (ALLOWED_USERS=signin): no list.

The chat gets a link made for that person; it opens the client's SAP sign-in; the client's SAP
decides. Signed in with a SAP Cloud ALM API permission: kept (encrypted), renewed, used so CALM
records the person. Refused, or no permission: access not granted, nothing kept. Keys are
generated here, hosts and people are made up, the client's SAP login is faked.
"""
import base64
import hashlib
import json
import logging
import re
import time
from html import unescape
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp import FastMCP
from starlette.testclient import TestClient

from src.calm import person_signin, tenant_store, tenants
from src.calm.dependencies import SignInNeeded, TenantChoiceNeeded, get_calm_headers, tenant_names

SIGNIN = "https://syntax-dev.authentication.us10.hana.ondemand.com"
NHL_AUTH = "https://nhl-cloudalm.authentication.us10.hana.ondemand.com/oauth/token"
XSAPP = "calm-mcp-claude!t123"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
MCP = "https://calm-mcp.example.com"


def _person(email: str):
    claims = {"iss": f"{SIGNIN}/oauth/token", "aud": [XSAPP], "exp": int(time.time()) + 600, "user_id": f"id-{email}",
              "grant_type": "authorization_code", "user_name": email, "email": email, "scope": [f"{XSAPP}.Claude"]}
    token = jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k1"})
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(
        headers={"Authorization": f"Bearer {token}"})))


def _nhl_token(email="jane@nhl.example", scope=("x!t.calm-api.projects.read",), grant="authorization_code"):
    claims = {"iss": NHL_AUTH, "grant_type": grant, "user_name": email, "email": email, "given_name": "Jane",
              "family_name": "Doe", "scope": list(scope), "n": time.time()}
    return jwt.encode(claims, "test-only-signing-value-of-32-bytes", algorithm="HS256")


class _NhlLogin:
    """The client's SAP login: answers code and refresh requests with what the test sets."""

    def __init__(self):
        self.calls, self.answer, self.fails = [], {}, False

    def __call__(self, tenant, form):
        self.calls.append((tenant.name, tenant.client_id, dict(form)))
        if self.fails:
            raise RuntimeError("HTTP 401: invalid_grant")
        return self.answer


@pytest.fixture
def env(monkeypatch):
    import os
    for var in [v for v in os.environ if v.startswith("CALM_TENANT_")] + [
            "CALM_BASE_URL", "CALM_AUTH_URL", "CALM_CLIENT_ID", "CALM_CLIENT_SECRET", "CALM_TOKEN",
            "CALM_MULTI_TENANT", "IDENTITY_ZONE", "REGION_ZONE", "CALM_IDENTITY_ZONE", "CALM_REGION_ZONE"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("VCAP_SERVICES", json.dumps({"xsuaa": [{"name": "claude-auth", "credentials": {
        "url": SIGNIN, "xsappname": XSAPP, "clientid": "sb-" + XSAPP}}]}))
    monkeypatch.setenv("CALM_SIGNIN_INSTANCE", "claude-auth")
    monkeypatch.setenv("CALM_DEFAULT_TENANT_NAME", "syntax")
    monkeypatch.setenv("MCP_PUBLIC_URL", f"{MCP}/mcp")
    for name, zone, users in (("SYNTAX", "home-cloudalm", "@example.com"), ("NHL", "nhl-cloudalm", "signin")):
        for key, value in {"IDENTITY_ZONE": zone, "REGION_ZONE": "us10", "CLIENT_ID": f"{name.lower()}-id",
                           "CLIENT_SECRET": f"{name.lower()}-test-value", "ALLOWED_USERS": users}.items():
            monkeypatch.setenv(f"CALM_TENANT_{name}_{key}", value)
    monkeypatch.setattr(tenants, "_KEYS", {})
    jwk = {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "k1"}
    monkeypatch.setattr(tenants, "_fetch_jwks", lambda base: {"keys": [jwk]})
    monkeypatch.setattr("src.calm.dependencies.get_or_create_token_manager",
                        lambda cid, secret, auth: SimpleNamespace(get_token=lambda: f"{cid}-token"))
    monkeypatch.setattr(person_signin, "_MEMORY", {})
    monkeypatch.setattr(tenant_store, "_cache", {"key": None, "data": None})
    login = _NhlLogin()
    monkeypatch.setattr(person_signin, "_token_request", login)
    mcp = FastMCP("t")
    person_signin.register(mcp)
    with TestClient(mcp.http_app(), base_url=MCP) as web:
        yield SimpleNamespace(web=web, login=login)


def _link(ctx) -> str:
    with pytest.raises(SignInNeeded) as asked:
        get_calm_headers(ctx, "nhl")
    answer = asked.value.answer
    assert isinstance(asked.value, TenantChoiceNeeded)  # every tool already answers a read / fails a write with it
    assert answer["status"] == "sign_in_needed" and answer["Tenant"] == "nhl"
    assert answer["Sign In Link"] in str(asked.value)  # a write's error carries the link too
    assert answer["Sign In Link"].startswith(f"{MCP}/signin/start/")
    return answer["Sign In Link"]


def _sign_in(env, ctx, **callback) -> tuple[int, str, dict]:
    """Follow the link like a browser: its page, then SAP's return to the callback."""
    page = env.web.get(_link(ctx).removeprefix(MCP))
    assert page.status_code == 200 and page.headers["referrer-policy"] == "no-referrer"
    authorize = unescape(re.search(r'href="([^"]+)"', page.text).group(1))
    query = {k: v[0] for k, v in parse_qs(urlparse(authorize).query).items()}
    assert authorize.startswith(NHL_AUTH.removesuffix("/token") + "/authorize?")
    assert query["client_id"] == "nhl-id" and query["redirect_uri"] == f"{MCP}/signin/callback"
    assert query["code_challenge_method"] == "S256" and query["response_type"] == "code"
    back = env.web.get("/signin/callback", params={"state": query["state"], **({"code": "abc"} | callback)})
    return back.status_code, back.text, query


def test_a_person_signs_in_with_the_clients_own_sap_and_calm_records_them(env, caplog):
    caplog.set_level(logging.INFO, logger="calm-mcp.audit")
    jane, dan = _person("jane@example.com"), _person("dan@elsewhere.example")
    assert tenant_names(jane) == ["nhl", "syntax"] and tenant_names(dan) == ["nhl"]  # no list: anyone may try
    token = _nhl_token()
    env.login.answer = {"access_token": token, "refresh_token": "r1", "expires_in": 3600}
    status, page, query = _sign_in(env, jane)
    assert status == 200 and "signed in as jane@nhl.example" in page
    name, client_id, form = env.login.calls[0]
    assert (name, client_id, form["grant_type"], form["code"]) == ("nhl", "nhl-id", "authorization_code", "abc")
    assert form["redirect_uri"] == f"{MCP}/signin/callback"
    digest = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).decode().rstrip("=")
    assert digest == query["code_challenge"]  # PKCE: only this sign-in can use SAP's code
    h = get_calm_headers(jane, "nhl")
    assert h.token == token and h.base_url == "https://nhl-cloudalm.us10.alm.cloud.sap"
    assert h.token_source == "signed-in user (OAuth), tenant nhl" and h.signed_in_user == "Jane Doe"
    assert get_calm_headers(jane, "syntax").token == "syntax-id-token"  # list clients unchanged
    assert any("tool=signin outcome=signed in" in r.getMessage() and "jane@example.com" in r.getMessage()
               for r in caplog.records)
    assert not any(token in r.getMessage() for r in caplog.records)


def test_the_link_is_for_the_person_who_asked_and_only_for_10_minutes(env, monkeypatch):
    env.login.answer = {"access_token": _nhl_token(), "refresh_token": "r1", "expires_in": 3600}
    jane, bob = _person("jane@example.com"), _person("bob@example.com")
    link = _link(jane)
    assert "jane@example.com" in env.web.get(link.removeprefix(MCP)).text  # says whose connector it signs in
    _sign_in(env, jane)
    _link(bob)  # jane's sign-in is hers only
    assert env.web.get(link.removeprefix(MCP)[:-8] + "AAAAAAA=").status_code == 400  # tampered
    assert env.web.get("/signin/callback", params={"state": "forged", "code": "x"}).status_code == 400
    monkeypatch.setattr(person_signin, "LINK_TTL", -1)
    assert "doesn't work any more" in unescape(env.web.get(_link(bob).removeprefix(MCP)).text)


def test_no_access_at_the_client_means_access_not_granted_and_nothing_kept(env):
    jane = _person("jane@example.com")
    status, page, _ = _sign_in(env, jane, error="access_denied", error_description="User is not authorized")
    assert status == 403 and "Access not granted" in page and "User is not authorized" in page
    assert env.login.calls == []
    env.login.answer = {"access_token": _nhl_token(scope=("openid", "uaa.user")), "expires_in": 3600}
    status, page, _ = _sign_in(env, jane)
    assert status == 403 and "no SAP Cloud ALM API permission" in page
    env.login.answer = {"access_token": _nhl_token(grant="client_credentials"), "expires_in": 3600}
    assert _sign_in(env, jane)[0] == 403  # a key's token is not this person
    env.login.fails = True
    assert _sign_in(env, jane)[0] == 502
    _link(jane)  # nothing was kept: still asked to sign in


def test_a_sign_in_is_renewed_then_asked_for_again_when_sap_stops(env):
    jane = _person("jane@example.com")
    env.login.answer = {"access_token": _nhl_token(), "refresh_token": "r1", "expires_in": 30}  # runs out at once
    _sign_in(env, jane)
    renewed = _nhl_token()
    env.login.answer = {"access_token": renewed, "expires_in": 3600}
    assert get_calm_headers(jane, "nhl").token == renewed
    assert env.login.calls[-1][2] == {"grant_type": "refresh_token", "refresh_token": "r1"}
    assert get_calm_headers(jane, "nhl").token == renewed  # kept, not renewed on every call
    (record,) = person_signin._MEMORY.values()
    assert record["refresh"] == "r1"  # SAP sent no new one: the old one is kept
    record["expires"] = 0
    env.login.fails = True
    _link(jane)  # SAP refused to renew: sign in again
    assert person_signin._MEMORY == {}


def test_a_sign_in_made_for_another_address_is_never_used(env, monkeypatch):
    jane = _person("jane@example.com")
    env.login.answer = {"access_token": _nhl_token(), "refresh_token": "r1", "expires_in": 3600}
    _sign_in(env, jane)
    monkeypatch.setenv("CALM_TENANT_NHL_IDENTITY_ZONE", "nhl-new-cloudalm")
    _link(jane)


def test_kept_encrypted_in_the_client_store_shared_by_every_copy(env, monkeypatch, tmp_path):
    monkeypatch.setenv("CALM_TENANT_STORE", str(tmp_path / "clients.enc"))
    monkeypatch.setenv("CALM_TENANT_STORE_KEY", Fernet.generate_key().decode())
    jane = _person("jane@example.com")
    token = _nhl_token()
    env.login.answer = {"access_token": token, "refresh_token": "r1-renewal-value", "expires_in": 3600}
    link = _link(jane)
    monkeypatch.setattr(person_signin, "_PROCESS_KEY", Fernet.generate_key())  # another copy of the MCP
    assert env.web.get(link.removeprefix(MCP)).status_code == 200
    _sign_in(env, jane)
    raw = (tmp_path / "clients.enc").read_bytes()
    assert token.encode() not in raw and b"r1-renewal-value" not in raw and b"jane" not in raw
    assert person_signin._MEMORY == {}
    monkeypatch.setattr(tenant_store, "_cache", {"key": None, "data": None})  # a restart
    assert get_calm_headers(jane, "nhl").token == token
    tenant_store.remove("nhl")
    _link(jane)


def test_a_local_mcp_opens_it_with_its_key_and_health_gives_the_link(env, monkeypatch):
    local = SimpleNamespace(request_context=SimpleNamespace(request=None))
    assert get_calm_headers(local, "nhl").token == "nhl-id-token"  # the user's own machine and configuration
    from src.calm.tools import health
    mcp, captured = FastMCP("t"), {}
    orig = mcp.tool

    def grab(*a, **k):
        def deco(fn):
            captured[fn.__name__] = fn
            return orig(*a, **k)(fn)
        return deco
    monkeypatch.setattr(mcp, "tool", grab)
    health.register(mcp)
    out = captured["calm_health"](_person("jane@example.com"), "nhl")
    assert out["status"] == "sign_in_needed" and out["Sign In Link"].startswith(f"{MCP}/signin/start/")


def test_admins_can_choose_signin():
    from src.calm.tools.admin import _people
    assert _people("SignIn") == ["signin"]
    with pytest.raises(ValueError, match="signin"):
        _people("signin, jane@example.com")  # one or the other
