"""The server must START when credentials are set but no tenant is configured.

With the built-in tenant removed, a deployment that sets CALM_CLIENT_ID /
CALM_CLIENT_SECRET but no IDENTITY_ZONE / REGION_ZONE (or CALM_AUTH_URL)
used to crash at boot inside _maybe_init_token_manager, taking every agent down
— including agents that send their own tenant in x-calm-* headers. These tests
pin the fixed behaviour:

- startup logs the problem and keeps serving (env credential disabled);
- a request relying on the env credential gets the precise "no tenant" error;
- calm_health reports the missing tenant instead of failing;
- with a tenant configured, the env token manager is initialised as before.
No network: no tenant means no token request is ever made.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Empty values (not unset) so a developer .env loaded by server.py can't fill them.
NO_TENANT = {k: "" for k in (
    "IDENTITY_ZONE", "REGION_ZONE", "CALM_IDENTITY_ZONE", "CALM_REGION_ZONE",
    "CALM_BASE_URL", "CALM_AUTH_URL", "CALM_CERT_AUTH_URL", "CALM_TOKEN",
    "CALM_CLIENT_CERT", "CALM_CLIENT_KEY", "CALM_CLIENT_CERT_PEM", "CALM_CLIENT_KEY_PEM",
    "CALM_MULTI_TENANT",
)}
DUMMY_CREDS = {"CALM_CLIENT_ID": "test-client-id", "CALM_CLIENT_SECRET": "test-secret-not-real"}


@pytest.fixture
def no_tenant_env(monkeypatch):
    for k, v in {**NO_TENANT, **DUMMY_CREDS}.items():
        monkeypatch.setenv(k, v)
    import src.calm.token_manager as tm
    monkeypatch.setattr(tm, "_manager", None)  # restored after each test
    yield


def test_startup_does_not_raise_without_tenant(no_tenant_env, caplog):
    import server

    with caplog.at_level("ERROR"):
        assert server._maybe_init_token_manager() is False
    assert "env credential is disabled" in caplog.text
    assert "IDENTITY_ZONE" in caplog.text


def test_startup_initialises_manager_when_tenant_configured(no_tenant_env, monkeypatch):
    import server

    monkeypatch.setenv("IDENTITY_ZONE", "example-tenant")
    monkeypatch.setenv("REGION_ZONE", "us10")
    assert server._maybe_init_token_manager() is True


def test_env_credential_request_names_the_missing_tenant(no_tenant_env):
    from src.calm.config import TenantNotConfiguredError
    from src.calm.dependencies import get_calm_headers

    class Ctx:
        pass

    with pytest.raises(TenantNotConfiguredError, match="No SAP Cloud ALM tenant configured"):
        get_calm_headers(Ctx())


def test_no_credentials_at_all_keeps_the_generic_message(no_tenant_env, monkeypatch):
    from src.calm.dependencies import get_calm_headers

    monkeypatch.setenv("CALM_CLIENT_ID", "")
    monkeypatch.setenv("CALM_CLIENT_SECRET", "")

    class Ctx:
        pass

    with pytest.raises(ValueError, match="Missing CALM token"):
        get_calm_headers(Ctx())


def test_real_server_process_starts_and_answers_without_tenant():
    """Spawn server.py exactly as a deployment would, over stdio."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, **NO_TENANT, **DUMMY_CREDS, "CALM_ENABLE_WRITES": "false",
           "CALM_OUTPUT_FORMAT": "json"}

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["server.py"], env=env, cwd=str(ROOT))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = {t.name for t in (await s.list_tools()).tools}
                health = await s.call_tool("calm_health", {})
                data = await s.call_tool("calm_resource", {"resource": "projects", "operation": "list"})
                return tools, health, data

    tools, health, data = asyncio.run(run())
    assert "calm_resource" in tools and len(tools) == 23
    assert health.is_error is not True
    assert "tenant" in health.content[0].text.lower()
    assert data.is_error is True
    assert "No SAP Cloud ALM tenant configured" in data.content[0].text
