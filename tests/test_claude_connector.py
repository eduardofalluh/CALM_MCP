"""Claude (claude.ai / Cowork) as a connector: sign-in discovery on the HTTP server.

Claude only starts a sign-in when the MCP answers 401 with where to read the
metadata, and it needs ``resource`` to be exactly the MCP address. SAP's login
service registers no clients, so the metadata names this server as the
authorization server and points at the tenant's SAP login endpoints. A request
that carries any credential, or a server with its own key, is never asked to
sign in. Hosts below are made up.
"""
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.calm.oauth import OAuthMiddleware

MCP = "https://calm-mcp.example.com/mcp"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CALM_IDENTITY_ZONE", "acme-cloudalm")
    monkeypatch.setenv("CALM_REGION_ZONE", "eu10")
    for name in ("CALM_CLIENT_ID", "CALM_CLIENT_SECRET", "CALM_TOKEN", "CALM_MULTI_TENANT", "MCP_PUBLIC_URL",
                 "CALM_BASE_URL", "CALM_AUTH_URL", "IDENTITY_ZONE", "REGION_ZONE", "CALM_SIGNIN_INSTANCE",
                 "VCAP_SERVICES", "VCAP_APPLICATION"):
        monkeypatch.delenv(name, raising=False)

    async def mcp_endpoint(request):
        return PlainTextResponse("reached the MCP")

    app = Starlette(routes=[Route("/mcp", mcp_endpoint, methods=["GET", "POST"])])
    app.add_middleware(OAuthMiddleware)
    return TestClient(app, base_url="https://calm-mcp.example.com")


def test_no_credential_is_asked_to_sign_in(client):
    r = client.post("/mcp", json={})
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == \
        'Bearer resource_metadata="https://calm-mcp.example.com/.well-known/oauth-protected-resource/mcp"'


def test_metadata_names_the_mcp_address_and_the_sap_login(client):
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == MCP and prm["authorization_servers"] == ["https://calm-mcp.example.com"]
    assert "scopes_supported" not in prm  # "openid" alone would strip the CALM permissions
    assert client.get("/.well-known/oauth-protected-resource/mcp").json() == prm
    for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
        asm = client.get(path).json()
        assert asm["issuer"] == "https://calm-mcp.example.com"
        sap = "https://acme-cloudalm.authentication.eu10.hana.ondemand.com"
        assert asm["authorization_endpoint"] == f"{sap}/oauth/authorize"
        assert asm["token_endpoint"] == f"{sap}/oauth/token"
        assert "none" not in asm["token_endpoint_auth_methods_supported"]  # SAP needs the client secret
        assert "registration_endpoint" not in asm


def test_any_credential_reaches_the_mcp(client, monkeypatch):
    assert client.post("/mcp", headers={"Authorization": "Bearer person"}).text == "reached the MCP"
    assert client.post("/mcp", headers={"x-calm-client-id": "id", "x-calm-client-secret": "s"}).status_code == 200
    monkeypatch.setenv("CALM_CLIENT_ID", "id")
    monkeypatch.setenv("CALM_CLIENT_SECRET", "s")
    assert client.post("/mcp").status_code == 200  # the server's own key: GenAI Studio as before
    monkeypatch.setenv("CALM_MULTI_TENANT", "true")
    assert client.post("/mcp").status_code == 401  # a shared pod never uses its own key


def test_public_address_from_env_or_proxy_headers(client, monkeypatch):
    prm = client.get("/.well-known/oauth-protected-resource",
                     headers={"x-forwarded-host": "calm.syntax.example", "x-forwarded-proto": "https"}).json()
    assert prm["resource"] == "https://calm.syntax.example/mcp"
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://gw.example.com/calm/mcp/")
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == "https://gw.example.com/calm/mcp"
    assert prm["authorization_servers"] == ["https://gw.example.com/calm"]


def test_no_tenant_metadata_says_so(client, monkeypatch):
    monkeypatch.delenv("CALM_IDENTITY_ZONE")
    monkeypatch.delenv("CALM_REGION_ZONE")
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 503 and r.json()["error"] == "tenant_not_configured"


# --- On SAP BTP: the connector's own sign-in (an XSUAA instance bound to the app) ---------------
import json  # noqa: E402
import time  # noqa: E402

import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from src.calm import tenants  # noqa: E402

SIGNIN = "https://syntax-dev.authentication.us10.hana.ondemand.com"
XSAPP, CLIENT = "calm-mcp-claude!t123", "sb-calm-mcp-claude!t123"
SIGNIN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def connector_token(email="jane@example.com", scope=(f"{XSAPP}.Claude", "openid"), key=None, **extra):
    claims = {"iss": f"{SIGNIN}/oauth/token", "aud": [XSAPP, CLIENT, "openid"], "exp": int(time.time()) + 600,
              "grant_type": "authorization_code", "user_name": email, "email": email, "scope": list(scope),
              **extra}
    return jwt.encode(claims, key or SIGNIN_KEY, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture
def btp(client, monkeypatch):
    services = {"xsuaa": [{"name": "calm-mcp-claude-auth",
                           "credentials": {"url": SIGNIN, "xsappname": XSAPP, "clientid": CLIENT}}]}
    monkeypatch.setenv("VCAP_SERVICES", json.dumps(services))
    monkeypatch.setenv("CALM_SIGNIN_INSTANCE", "calm-mcp-claude-auth")
    monkeypatch.setenv("VCAP_APPLICATION", json.dumps({"application_uris": ["syntax-calm-mcp.cfapps.us10.example"]}))
    monkeypatch.setattr(tenants, "_KEYS", {})
    jwk = {**jwt.algorithms.RSAAlgorithm.to_jwk(SIGNIN_KEY.public_key(), as_dict=True), "kid": "k1"}
    monkeypatch.setattr(tenants, "_fetch_jwks", lambda base: {"keys": [jwk]} if base == SIGNIN else {"keys": []})
    return client


BTP_MCP = "https://syntax-calm-mcp.cfapps.us10.example/mcp"


def test_btp_metadata_sends_claude_to_the_connectors_own_sign_in(btp):
    prm = btp.get("/.well-known/oauth-protected-resource/mcp").json()
    assert prm["resource"] == BTP_MCP  # the app's one Cloud Foundry route, not the Host header
    assert prm["authorization_servers"] == [f"{SIGNIN}/oauth/token"] and prm["scopes_supported"] == [f"{XSAPP}.Claude"]
    assert btp.get("/.well-known/oauth-authorization-server").status_code == 404  # Claude reads XSUAA's own


def test_btp_only_a_valid_connector_sign_in_with_the_role_gets_in(btp, monkeypatch):
    r = btp.post("/mcp", json={})
    assert r.status_code == 401 and r.headers["www-authenticate"] == (
        'Bearer resource_metadata="https://syntax-calm-mcp.cfapps.us10.example/.well-known/oauth-protected-resource'
        f'/mcp", scope="{XSAPP}.Claude"')
    assert btp.post("/mcp", headers={"Authorization": f"Bearer {connector_token()}"}).text == "reached the MCP"
    r = btp.post("/mcp", headers={"Authorization": f"Bearer {connector_token(scope=('openid',))}"})
    assert r.status_code == 403 and 'error="insufficient_scope"' in r.headers["www-authenticate"]
    forged = connector_token(key=rsa.generate_private_key(public_exponent=65537, key_size=2048))
    for bad in (connector_token(exp=int(time.time()) - 3600), forged, connector_token(aud=["someone-else"]),
                connector_token(grant_type="client_credentials"), "not-a-jwt"):
        r = btp.post("/mcp", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]  # Claude signs in again
    monkeypatch.setenv("CALM_CLIENT_ID", "id")
    monkeypatch.setenv("CALM_CLIENT_SECRET", "s")
    assert btp.post("/mcp", headers={"x-calm-client-id": "id", "x-calm-client-secret": "s"}).status_code == 401


def test_btp_a_misbound_sign_in_is_refused_not_guessed(btp, monkeypatch):
    monkeypatch.setenv("CALM_SIGNIN_INSTANCE", "another-name")
    with pytest.raises(RuntimeError, match="not bound to this app"):
        tenants.signin()
    twice = {"xsuaa": [{"name": "x", "credentials": {"url": SIGNIN, "xsappname": "a", "clientid": "b"}}] * 2}
    monkeypatch.setenv("VCAP_SERVICES", json.dumps(twice))
    monkeypatch.setenv("CALM_SIGNIN_INSTANCE", "x")
    with pytest.raises(RuntimeError, match="bound more than once"):
        tenants.signin()
    monkeypatch.setenv("VCAP_SERVICES", json.dumps({"objectstore": [{"name": "x", "credentials": {}}]}))
    with pytest.raises(RuntimeError, match="is it an XSUAA instance"):
        tenants.signin()
