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
                 "CALM_BASE_URL", "CALM_AUTH_URL", "IDENTITY_ZONE", "REGION_ZONE"):
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
        'Bearer resource_metadata="https://calm-mcp.example.com/.well-known/oauth-protected-resource"'


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
