"""
SAP Cloud ALM MCP Server — entry point.

Run
---
    python server.py               # stdio (Claude Desktop, MCP Inspector, Cursor)
    python server.py --http --port 8000   # HTTP for Syntax GenAI Studio

Auth
----
- HTTP transport + OAuth (recommended):
  Set CALM_OAUTH_CLIENT_ID, CALM_OAUTH_CLIENT_SECRET, CALM_OAUTH_AUTH_URL,
  CALM_OAUTH_TOKEN_URL, CALM_OAUTH_JWKS_URI, CALM_OAUTH_ISSUER, and MCP_BASE_URL.
  MCP clients will be redirected to SAP BTP for authentication. Tokens are
  refreshed automatically — no manual copy-paste required.

- HTTP transport, no OAuth (legacy):
  Pass x-calm-token (and optionally x-calm-base-url) as request headers.

- stdio / local dev:
  Set CALM_TOKEN in your .env file.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP

from src.calm.tools import health, processes, projects, scopes, test_cases

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("calm-mcp")


def _build_oauth_proxy():
    """Return an OAuthProxy for SAP BTP if credentials are configured, else None."""
    client_id = os.getenv("CALM_OAUTH_CLIENT_ID")
    if not client_id:
        return None

    client_secret = os.getenv("CALM_OAUTH_CLIENT_SECRET", "")
    auth_url = os.getenv("CALM_OAUTH_AUTH_URL")
    token_url = os.getenv("CALM_OAUTH_TOKEN_URL")
    jwks_uri = os.getenv("CALM_OAUTH_JWKS_URI")
    issuer = os.getenv("CALM_OAUTH_ISSUER")
    audience = os.getenv("CALM_OAUTH_AUDIENCE", client_id)
    base_url = os.getenv("MCP_BASE_URL", "http://127.0.0.1:8000")
    scopes_env = os.getenv("CALM_OAUTH_SCOPES")

    missing = [k for k, v in {
        "CALM_OAUTH_AUTH_URL": auth_url,
        "CALM_OAUTH_TOKEN_URL": token_url,
        "CALM_OAUTH_JWKS_URI": jwks_uri,
        "CALM_OAUTH_ISSUER": issuer,
    }.items() if not v]
    if missing:
        log.warning("OAuth disabled — missing env vars: %s", ", ".join(missing))
        return None

    from fastmcp.server.auth import OAuthProxy
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    token_verifier = JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=issuer,
        audience=audience,
    )

    extra_authorize = {}
    if scopes_env:
        extra_authorize["scope"] = scopes_env

    proxy = OAuthProxy(
        upstream_authorization_endpoint=auth_url,
        upstream_token_endpoint=token_url,
        upstream_client_id=client_id,
        upstream_client_secret=client_secret or None,
        token_verifier=token_verifier,
        base_url=base_url,
        allowed_client_redirect_uris=[
            "http://localhost:*",
            "https://claude.ai/api/mcp/auth_callback",
            "https://*.syntaxsystems.ai/*",
        ],
        extra_authorize_params=extra_authorize if extra_authorize else None,
    )
    log.info("OAuth proxy configured (SAP BTP client_id=%s)", client_id)
    return proxy


mcp = FastMCP("sap-cloud-alm")

projects.register(mcp)
processes.register(mcp)
scopes.register(mcp)
test_cases.register(mcp)
health.register(mcp)


def main() -> None:
    parser = argparse.ArgumentParser(description="SAP Cloud ALM MCP server")
    parser.add_argument("--http", action="store_true", help="Serve over Streamable HTTP instead of stdio.")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))
    args = parser.parse_args()

    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port

        auth = _build_oauth_proxy()
        if auth:
            mcp.settings.auth = auth
            log.info("Starting CALM MCP with OAuth on http://%s:%s", args.host, args.port)
        else:
            log.info("Starting CALM MCP (no OAuth) on http://%s:%s", args.host, args.port)

        mcp.run(transport="streamable-http")
    else:
        log.info("Starting CALM MCP on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
