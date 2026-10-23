"""Tenant resolution: there is no built-in tenant.

With no env vars and no x-calm-* headers the server must refuse with a clear
configuration error instead of silently answering for a default tenant. The env
and header paths, and the fail-closed credential errors, must keep working as
before. All zones here are obviously fake.

Run with:  ./venv/bin/python -m pytest tests/test_tenant_config.py -q
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import config  # noqa: E402
from src.calm.config import TenantNotConfiguredError  # noqa: E402
from src.calm.dependencies import get_calm_headers  # noqa: E402

_TENANT_VARS = (
    "CALM_IDENTITY_ZONE", "IDENTITY_ZONE", "CALM_REGION_ZONE", "REGION_ZONE",
    "CALM_BASE_URL", "CALM_AUTH_URL", "CALM_CERT_AUTH_URL",
)
_CRED_VARS = ("CALM_TOKEN", "CALM_CLIENT_ID", "CALM_CLIENT_SECRET", "CALM_MULTI_TENANT")


@pytest.fixture(autouse=True)
def no_tenant_env(monkeypatch):
    for name in _TENANT_VARS + _CRED_VARS:
        monkeypatch.delenv(name, raising=False)
    # No startup token manager from another test leaking into the env path.
    monkeypatch.setattr("src.calm.dependencies.get_managed_token", lambda: None)


def _ctx(headers: dict | None = None):
    if headers is None:
        return SimpleNamespace()  # no request_context — stdio
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers=headers)))


class TestUnconfigured:
    @pytest.mark.parametrize("fn", [
        config.get_identity_zone, config.get_region_zone, config.get_base_url,
        config.get_auth_url, config.get_auth_base_url, config.get_cert_auth_url,
        config.build_base_url, config.build_auth_url,
    ])
    def test_url_helpers_raise(self, fn):
        with pytest.raises(TenantNotConfiguredError) as exc:
            fn()
        msg = str(exc.value)
        for name in ("IDENTITY_ZONE", "REGION_ZONE", "CALM_BASE_URL", "CALM_AUTH_URL",
                     "x-calm-identity-zone", "x-calm-region-zone"):
            assert name in msg

    def test_is_a_value_error(self):
        # Tools surface ValueError as a normal tool error.
        assert issubclass(TenantNotConfiguredError, ValueError)

    def test_tool_call_with_token_but_no_tenant_raises(self, monkeypatch):
        monkeypatch.setenv("CALM_TOKEN", "fake-token")
        with pytest.raises(TenantNotConfiguredError):
            get_calm_headers(_ctx())

    def test_half_configured_zone_still_raises(self, monkeypatch):
        monkeypatch.setenv("IDENTITY_ZONE", "fake-tenant")
        with pytest.raises(TenantNotConfiguredError):
            config.get_base_url()


class TestEnvPath:
    def test_zones_build_urls(self, monkeypatch):
        monkeypatch.setenv("IDENTITY_ZONE", "fake-tenant")
        monkeypatch.setenv("REGION_ZONE", "xx10")
        assert config.get_base_url() == "https://fake-tenant.xx10.alm.cloud.sap"
        assert config.get_auth_url() == "https://fake-tenant.authentication.xx10.hana.ondemand.com/oauth/token"

    def test_calm_prefixed_zone_wins(self, monkeypatch):
        monkeypatch.setenv("IDENTITY_ZONE", "fake-plain")
        monkeypatch.setenv("CALM_IDENTITY_ZONE", "fake-prefixed")
        monkeypatch.setenv("REGION_ZONE", "xx10")
        assert config.get_base_url() == "https://fake-prefixed.xx10.alm.cloud.sap"

    def test_explicit_urls_need_no_zones(self, monkeypatch):
        monkeypatch.setenv("CALM_BASE_URL", "https://fake.example.test")
        monkeypatch.setenv("CALM_AUTH_URL", "https://fake-auth.example.test/oauth/token")
        assert config.get_base_url() == "https://fake.example.test"
        assert config.get_auth_url() == "https://fake-auth.example.test/oauth/token"

    def test_get_calm_headers_uses_env_tenant(self, monkeypatch):
        monkeypatch.setenv("IDENTITY_ZONE", "fake-tenant")
        monkeypatch.setenv("REGION_ZONE", "xx10")
        monkeypatch.setenv("CALM_TOKEN", "fake-token")
        h = get_calm_headers(_ctx())
        assert h.base_url == "https://fake-tenant.xx10.alm.cloud.sap"
        assert h.token_source == "CALM_TOKEN env var"


class TestHeaderPath:
    def test_zone_headers_with_client_creds(self):
        mgr = MagicMock()
        mgr.get_token.return_value = "fake-header-token"
        headers = {
            "x-calm-identity-zone": "fake-tenant", "x-calm-region-zone": "xx10",
            "x-calm-client-id": "fake-id", "x-calm-client-secret": "fake-secret",
        }
        with patch("src.calm.dependencies.get_or_create_token_manager", return_value=mgr) as gm:
            h = get_calm_headers(_ctx(headers))
        assert h.base_url == "https://fake-tenant.xx10.alm.cloud.sap"
        assert h.token_source == "client_credentials (header)"
        gm.assert_called_once_with(
            "fake-id", "fake-secret",
            "https://fake-tenant.authentication.xx10.hana.ondemand.com/oauth/token",
        )

    def test_header_creds_without_any_tenant_raise(self):
        headers = {"x-calm-client-id": "fake-id", "x-calm-client-secret": "fake-secret"}
        with patch("src.calm.dependencies.get_or_create_token_manager") as gm:
            with pytest.raises(TenantNotConfiguredError):
                get_calm_headers(_ctx(headers))
        gm.assert_not_called()  # no token request to a guessed tenant


class TestFailClosedPriorityUnchanged:
    def test_multi_tenant_error_wins_over_missing_tenant(self, monkeypatch):
        monkeypatch.setenv("CALM_MULTI_TENANT", "true")
        with pytest.raises(ValueError, match="CALM_MULTI_TENANT is enabled") as exc:
            get_calm_headers(_ctx({}))
        assert not isinstance(exc.value, TenantNotConfiguredError)

    def test_incomplete_header_creds_error_wins(self):
        with pytest.raises(ValueError, match="Incomplete per-tenant credentials"):
            get_calm_headers(_ctx({"x-calm-client-id": "fake-id"}))

    def test_missing_token_error_unchanged(self):
        with pytest.raises(ValueError, match="Missing CALM token"):
            get_calm_headers(_ctx())


class TestHealthUnconfigured:
    def _health(self):
        from fastmcp import FastMCP

        from src.calm.tools.health import register

        mcp = FastMCP("test")
        register(mcp)
        return asyncio.run(mcp.get_tool("calm_health")).fn

    def test_reports_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr("src.calm.tools.health.get_managed_token", lambda: None)
        out = self._health()(_ctx())
        assert out["server"] == "sap-cloud-alm"
        assert out["base_url"].startswith("(not configured)")
        assert out["auth_url"].startswith("(not configured)")
        assert "IDENTITY_ZONE" in out["base_url"]
        assert out["headers_received"]["x-calm-base-url"] == "(not set)"

    def test_reports_header_tenant(self, monkeypatch):
        monkeypatch.setattr("src.calm.tools.health.get_managed_token", lambda: None)
        out = self._health()(_ctx({"x-calm-identity-zone": "fake-tenant", "x-calm-region-zone": "xx10"}))
        assert out["base_url"] == "https://fake-tenant.xx10.alm.cloud.sap"
        assert out["auth_url"] == "https://fake-tenant.authentication.xx10.hana.ondemand.com/oauth/token"

    def test_reports_base_url_header(self, monkeypatch):
        monkeypatch.setattr("src.calm.tools.health.get_managed_token", lambda: None)
        out = self._health()(_ctx({"x-calm-base-url": "https://fake.example.test"}))
        assert out["base_url"] == "https://fake.example.test"
        assert out["headers_received"]["x-calm-base-url"] == "https://fake.example.test"
