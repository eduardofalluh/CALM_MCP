"""Admins add clients (SAP Cloud ALMs) from a chat; the secret only through a terminal command.

The chat gets a one-time command; the command asks for the secret hidden and sends it
to /admin/client-secret, which checks it with the client's SAP login and stores it
encrypted. Only verified admins can do it. Keys are generated here, hosts and people
are made up, SAP's login is faked.
"""
import base64
import inspect
import json
import re
import shlex
import time
import urllib.request
from types import SimpleNamespace

import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp import FastMCP
from starlette.testclient import TestClient

from src.calm import tenant_store, tenants
from src.calm.dependencies import get_calm_headers
from src.calm.tools import admin

HOME_AUTH = "https://home-cloudalm.authentication.eu10.hana.ondemand.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RIGHT = "right-test-value"


def _person(email: str) -> str:
    claims = {"iss": f"{HOME_AUTH}/oauth/token", "exp": int(time.time()) + 600, "grant_type": "authorization_code",
              "user_name": email, "email": email}
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "key-1"})


def _http(email: str | None):
    headers = {"Authorization": f"Bearer {_person(email)}"} if email else {}
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers=headers)))


class _SapLogin:
    """XSUAA for the client: only RIGHT is accepted; its token grants two CALM permissions."""

    def __init__(self, client_id, client_secret=None, auth_url=None, **_):
        self.secret, self.auth_url = client_secret, auth_url

    def get_token(self):
        if self.secret != RIGHT:
            raise RuntimeError("XSUAA token request failed (client_secret): HTTP 401 Unauthorized — Bad credentials")
        enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
        return f"{enc({'alg': 'none'})}.{enc({'scope': ['x!t.calm-api.tasks.read', 'x!t.calm-api.projects.read']})}.s"


@pytest.fixture
def env(monkeypatch, tmp_path):
    import os
    for var in [v for v in os.environ if v.startswith("CALM_TENANT_")] + [
            "CALM_BASE_URL", "CALM_AUTH_URL", "CALM_CLIENT_ID", "CALM_CLIENT_SECRET", "CALM_TOKEN",
            "IDENTITY_ZONE", "REGION_ZONE"]:
        monkeypatch.delenv(var, raising=False)
    store = tmp_path / "volume" / "clients.enc"
    monkeypatch.setenv("CALM_IDENTITY_ZONE", "home-cloudalm")
    monkeypatch.setenv("CALM_REGION_ZONE", "eu10")
    monkeypatch.setenv("CALM_TENANT_STORE", str(store))
    monkeypatch.setenv("CALM_TENANT_STORE_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CALM_ADMINS", "admin@example.com, second.admin@example.com")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://calm-mcp.example.com/mcp")
    monkeypatch.setattr(tenant_store, "_cache", {"key": None, "data": None})
    monkeypatch.setattr(tenants, "_KEYS", {})
    jwk = {**jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True), "kid": "key-1", "alg": "RS256"}
    monkeypatch.setattr(tenants, "_fetch_jwks", lambda base: {"keys": [jwk]})
    monkeypatch.setattr(admin, "TokenManager", _SapLogin)
    monkeypatch.setattr("src.calm.dependencies.get_or_create_token_manager",
                        lambda cid, secret, auth: SimpleNamespace(get_token=lambda: f"{cid}|{secret}|{auth}"))
    mcp = FastMCP("t")
    tools, orig = {}, mcp.tool

    def grab(*a, **k):
        def deco(fn):
            tools[fn.__name__] = fn
            return orig(*a, **k)(fn)
        return deco
    monkeypatch.setattr(mcp, "tool", grab)
    admin.register(mcp)
    with TestClient(mcp.http_app()) as web:
        yield SimpleNamespace(tool=tools["calm_admin_clients"], web=web, store=store)


def _add(env, **kw):
    args = {"name": "Centerra", "identity_zone": "centerra-cloudalm", "region_zone": "us10",
            "client_id": "sb-calm-api!b1|sapcloudalm!b2", "allowed_users": "jane@example.com, @partner.example"}
    return env.tool(_http("admin@example.com"), "add", **{**args, **kw})


def _run_command(env, command: str, typed: str, monkeypatch) -> str:
    """Run the exact command from the chat: the hidden prompt and the HTTPS call are faked."""
    argv = shlex.split(command)
    assert argv[:2] == ["python3", "-c"]
    sent = {}

    def urlopen(req):
        sent["url"] = req.full_url
        r = env.web.post("/admin/client-secret", content=req.data, headers=dict(req.header_items()))
        return SimpleNamespace(read=lambda: r.content)
    monkeypatch.setattr("getpass.getpass", lambda prompt: typed)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    printed = []
    exec(argv[2], {"print": printed.append})  # noqa: S102 — the command under test
    assert sent["url"] == "https://calm-mcp.example.com/admin/client-secret"
    return printed[0]


def test_only_verified_admins_on_the_hosted_mcp(env, monkeypatch):
    for who in ("jane@example.com", None):
        with pytest.raises(ValueError, match="Only the MCP's admins"):
            env.tool(_http(who), "list")
    with pytest.raises(ValueError, match="hosted SAP Cloud ALM MCP"):
        env.tool(SimpleNamespace(request_context=SimpleNamespace(request=None)), "list")
    monkeypatch.delenv("CALM_TENANT_STORE_KEY")
    with pytest.raises(ValueError, match="not set up on this MCP yet: CALM_TENANT_STORE_KEY not set"):
        env.tool(_http("admin@example.com"), "list")


def test_add_answers_with_a_command_and_never_takes_the_secret(env):
    out = _add(env)
    assert out["Client"] == "centerra" and out["Status"] == "waiting for its secret"
    assert "getpass" in out["Command"] and "https://calm-mcp.example.com/admin/client-secret" in out["Command"]
    assert "never into this chat" in out["Next Step"]
    assert not [p for p in inspect.signature(env.tool).parameters if "secret" in p]  # no way to pass one
    raw = env.store.read_bytes()
    assert b"centerra" not in raw and b"example.com" not in raw  # the whole store is encrypted
    for bad, match in (({"identity_zone": "bad zone"}, "identity_zone"), ({"region_zone": ""}, "region_zone"),
                       ({"allowed_users": ""}, "allowed_users"), ({"allowed_users": "jane"}, "not an email")):
        with pytest.raises(ValueError, match=match):
            _add(env, name="other", **bad)


def test_the_secret_from_the_terminal_is_checked_then_stored(env, monkeypatch):
    command = _add(env)["Command"]
    answer = _run_command(env, command, "wrong-test-value", monkeypatch)
    assert answer.startswith("Not saved: SAP's login for centerra-cloudalm (us10) refused") and "Bad credentials" in answer
    answer = _run_command(env, command, RIGHT, monkeypatch)  # a typo can be retried with the same command
    assert answer.startswith("Saved: centerra (centerra-cloudalm, us10). Its key works.")
    assert "It has 2 of the 24 CALM API permissions" in answer and "calm-api.documents.read" in answer
    assert "expired or was already used" in _run_command(env, command, RIGHT, monkeypatch)
    assert RIGHT.encode() not in env.store.read_bytes()
    h = get_calm_headers(_http("jane@example.com"), "centerra")
    assert h.base_url == "https://centerra-cloudalm.us10.alm.cloud.sap"
    assert h.token == (f"sb-calm-api!b1|sapcloudalm!b2|{RIGHT}|"
                       "https://centerra-cloudalm.authentication.us10.hana.ondemand.com/oauth/token")
    with pytest.raises(ValueError, match="not on the list"):
        get_calm_headers(_http("carol@example.com"), "centerra")
    with pytest.raises(ValueError, match="already exists"):
        _add(env)


def test_allow_new_secret_remove_and_list(env, monkeypatch):
    _run_command(env, _add(env)["Command"], RIGHT, monkeypatch)
    admin_ctx = _http("admin@example.com")
    assert env.tool(admin_ctx, "allow", name="centerra", allowed_users=["carol@example.com"])["Allowed Users"] == \
        ["carol@example.com"]
    assert get_calm_headers(_http("carol@example.com"), "centerra").base_url.startswith("https://centerra")
    with pytest.raises(ValueError, match="not on the list"):
        get_calm_headers(_http("jane@example.com"), "centerra")
    out = env.tool(admin_ctx, "new_secret", name="centerra", client_id="sb-new!b3|sapcloudalm!b2")
    assert "keeps working" in out["Status"]
    listed = env.tool(admin_ctx, "list")
    assert listed["Clients"][0]["Name"] == "centerra" and listed["Clients"][0]["Set"].startswith("from a chat")
    assert listed["Waiting For A Secret"][0]["Name"] == "centerra"
    assert get_calm_headers(_http("carol@example.com"), "centerra").token.startswith("sb-calm-api!b1|")  # old one
    _run_command(env, out["Command"], RIGHT, monkeypatch)
    assert get_calm_headers(_http("carol@example.com"), "centerra").token.startswith("sb-new!b3|")
    assert env.tool(admin_ctx, "remove", name="centerra") == {"Client": "centerra", "Removed": True}
    with pytest.raises(ValueError, match='No SAP Cloud ALM called "centerra"'):
        get_calm_headers(_http("carol@example.com"), "centerra")
    with pytest.raises(ValueError, match='No client "centerra" added from a chat'):
        env.tool(admin_ctx, "remove", name="centerra")


def test_a_client_set_on_the_server_is_changed_there(env, monkeypatch):
    monkeypatch.setenv("CALM_TENANT_LUTRON_IDENTITY_ZONE", "lutron-cloudalm")
    with pytest.raises(ValueError, match="set on the server"):
        _add(env, name="lutron")
    assert env.tool(_http("admin@example.com"), "list")["Clients"][0]["Set"].startswith("on the server")


def test_a_command_stops_working_after_10_minutes_or_5_wrong_secrets(env, monkeypatch):
    command = _add(env)["Command"]
    for _ in range(tenant_store.MAX_ATTEMPTS):
        _run_command(env, command, "wrong-test-value", monkeypatch)
    assert "expired or was already used" in _run_command(env, command, RIGHT, monkeypatch)
    command = _add(env)["Command"]
    later = time.time() + tenant_store.CODE_TTL + 1
    monkeypatch.setattr(tenant_store.time, "time", lambda: later)
    assert "expired or was already used" in _run_command(env, command, RIGHT, monkeypatch)
    assert "Not saved: use the exact command" in env.web.post("/admin/client-secret", content=b"nonsense").text


def test_a_store_that_cant_be_read_says_so(env, monkeypatch):
    _add(env)
    monkeypatch.setenv("CALM_TENANT_STORE_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(tenant_store, "_cache", {"key": None, "data": None})
    with pytest.raises(RuntimeError, match="can't be read with CALM_TENANT_STORE_KEY"):
        tenant_store.load()
    monkeypatch.setenv("CALM_TENANT_STORE_KEY", "not-a-key")
    with pytest.raises(RuntimeError, match="CALM_TENANT_STORE_KEY is not a valid key"):
        tenants.configured()


def test_the_command_is_plain_python_with_nothing_the_shell_expands(env):
    command = _add(env)["Command"]
    code = re.search(r"'code': '([A-Za-z0-9_-]+)'", command)
    assert code and code.group(1).encode() not in env.store.read_bytes()  # only its hash, encrypted
    compile(shlex.split(command)[2], "<command>", "exec")
    assert "$" not in command and "!" not in command and "`" not in command
