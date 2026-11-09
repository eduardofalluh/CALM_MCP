from __future__ import annotations

import base64
import json
import os
import re

from fastmcp import Context, FastMCP

from src.calm.config import (
    TenantNotConfiguredError,
    build_auth_url,
    build_base_url,
    get_auth_url,
    get_base_url,
)
from src.calm.dependencies import get_calm_headers, writes_enabled
from src.calm.tm_dependencies import tm_configured, tm_writes_enabled
from src.calm.token_manager import get_managed_token


# The service key permissions in the Syntax setup guide, and what each one
# opens in this MCP — so "does this client's key have everything?" is answered
# per connection, from the key's own token.
DOCUMENTED_SCOPES = {
    "calm-api.projects.read": "list and read projects",
    "calm-api.projects.write": "create / update projects",
    "calm-api.tasks.read": "tasks, requirements, user stories, risks, defects and every count over them",
    "calm-api.tasks.write": "create / update tasks and requirements, their comments and links",
    "calm-api.documents.read": "read documents",
    "calm-api.documents.write": "load functional specs / documents into CALM",
    "calm-api.documents.delete": "delete documents",
    "calm-api.features.read": "read features",
    "calm-api.features.write": "create / update features",
    "calm-api.testcases.read": "read test cases and their steps",
    "calm-api.testcases.write": "create / update test cases",
    "calm-api.testcases.delete": "delete test cases",
    "calm-api.testcases.force-delete": "delete test cases that already have test runs",
    "calm-api.testplans.read": "SAP's own Test Plans API (not offered on tenants yet; test plans are read from analytics)",
    "calm-api.tests.read": "test execution results and test plans (from analytics)",
    "calm-api.analytics.read": "analytics: status breakdowns, test execution and test plans",
    "calm-api.analytics.providers.read": "the list of analytics data sources",
    "calm-api.processmanagement.read": "scopes and their solution processes",
    "calm-api.processmanagement.write": "change scopes",
    "calm-api.processmanagement.delete": "delete scope items",
    "calm-api.processauthoring.read": "business and solution processes",
    "calm-api.processauthoring.write": "create / update processes",
    "calm-api.processauthoring.delete": "delete processes",
    "calm-api.demo-tasks.read": "SAP's demo analytics data (not used by the MCP)",
}
_SCOPE = re.compile(r"(calm-api\.[a-z0-9.\-]+)$")


def _permissions(ctx: Context) -> dict:
    """The CALM API permissions this connection's key grants (names from its
    token, never the token), against the documented set."""
    try:
        token = get_calm_headers(ctx).token or ""
    except Exception as exc:  # noqa: BLE001 — a diagnostic reports, never fails
        return {"status": "unknown", "reason": f"no token for this connection: {str(exc)[:200]}"}
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:  # noqa: BLE001
        return {"status": "unknown", "reason": "the token isn't a JWT, so its permissions can't be read from it"}
    granted = sorted({m.group(1) for s in claims.get("scope", []) if (m := _SCOPE.search(str(s)))})
    missing = {s: f"without it: {what}" for s, what in DOCUMENTED_SCOPES.items() if s not in granted}
    return {"granted": granted, "missing": missing, "has_every_documented_permission": not missing}


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    def calm_health(ctx: Context) -> dict:
        """SAP Cloud ALM (CALM) connection diagnostic. Confirms THIS SAP Cloud ALM
        MCP server is up and reports token status, the resolved tenant OAuth/API
        URLs, and the raw per-tenant header values received (identity zone, region,
        client id). Use this to verify GenAI Studio is injecting the correct SAP
        Cloud ALM credentials for this connection and that the server resolved the
        intended tenant — not another one. Also lists the service key's CALM API
        permissions ("permissions": granted, and each documented one missing with
        what stops working without it) — use it for "does this key have all the
        permissions / why is X unavailable". Fetches this connection's token but
        reads no CALM data; for CALM data use calm_resource.
        """
        token_source = None
        identity_zone = None
        region_zone = None
        client_id_hdr = None
        client_secret_hdr = None
        auth_url_hdr = None
        base_url_hdr = None

        try:
            request = ctx.request_context.request
            if request is not None:
                h = request.headers
                identity_zone = h.get("x-calm-identity-zone") or None
                region_zone = h.get("x-calm-region-zone") or None
                client_id_hdr = h.get("x-calm-client-id")
                client_secret_hdr = h.get("x-calm-client-secret")
                raw_auth = h.get("x-calm-auth-url")
                if raw_auth and raw_auth.strip().startswith("https://"):
                    auth_url_hdr = raw_auth.strip()
                raw_base = h.get("x-calm-base-url")
                if raw_base and raw_base.strip().startswith("https://"):
                    base_url_hdr = raw_base.strip()
        except Exception:
            pass

        # Resolve URLs using same logic as dependencies.py; report a missing
        # tenant instead of raising, since this is the diagnostic tool.
        try:
            if base_url_hdr:
                base_url = base_url_hdr
            elif identity_zone or region_zone:
                base_url = build_base_url(identity_zone, region_zone)
            else:
                base_url = get_base_url()
        except TenantNotConfiguredError as exc:
            base_url = f"(not configured) {exc}"

        try:
            if auth_url_hdr:
                auth_url = auth_url_hdr
            elif identity_zone or region_zone:
                auth_url = build_auth_url(identity_zone, region_zone)
            else:
                auth_url = get_auth_url()
        except TenantNotConfiguredError as exc:
            auth_url = f"(not configured) {exc}"

        # Mirror token resolution order from dependencies.py
        if client_id_hdr and client_secret_hdr:
            token_source = "client_credentials (header)"
        elif get_managed_token():
            token_source = "client_credentials"
        else:
            try:
                request = ctx.request_context.request
                if request is not None and request.headers.get("Authorization"):
                    token_source = "Authorization header"
            except Exception:
                pass

        if not token_source and os.getenv("CALM_TOKEN"):
            token_source = "CALM_TOKEN env var"

        return {
            "server": "sap-cloud-alm",
            "token_configured": token_source is not None,
            "token_source": token_source,
            "client_credentials_enabled": bool(
                (client_id_hdr and client_secret_hdr) or os.getenv("CALM_CLIENT_ID")
            ),
            "server_auth_mode": (
                "x509/mTLS"
                if (os.getenv("CALM_CLIENT_CERT") or os.getenv("CALM_CLIENT_CERT_PEM"))
                else "client_secret" if os.getenv("CALM_CLIENT_SECRET")
                else "header/token"
            ),
            "writes_enabled": writes_enabled(),
            "permissions": _permissions(ctx),
            "auth_url": auth_url,
            "base_url": base_url,
            # Optional BTP Test Management OData connection (tm_* tools).
            "tm_odata": {
                "configured": tm_configured(ctx),
                "tm_writes_enabled": tm_writes_enabled(),
                "base_url": os.getenv("TM_BASE_URL") or "(not set — env or x-tm-base-url header)",
            },
            "headers_received": {
                "x-calm-identity-zone": identity_zone or "(not set)",
                "x-calm-region-zone": region_zone or "(not set)",
                "x-calm-client-id": ("set" if client_id_hdr else "(not set)"),
                "x-calm-client-secret": ("set" if client_secret_hdr else "(not set)"),
                "x-calm-auth-url": auth_url_hdr or "(not set)",
                "x-calm-base-url": base_url_hdr or "(not set)",
            },
        }
