"""
SAP Cloud ALM MCP Server — entry point.

Run
---
    python server.py               # stdio (Claude Desktop, MCP Inspector, Cursor)
    python server.py --http --port 8000   # HTTP for Syntax GenAI Studio

Auth  (two separate SAP URLs are involved)
------------------------------------------
  Auth URL  → https://<tenant>.authentication.<region>.hana.ondemand.com/oauth/token
  API  URL  → https://<tenant>.<region>.alm.cloud.sap/api/...

Token resolution order:
  1. Client credentials (recommended) — set CALM_CLIENT_ID + CALM_CLIENT_SECRET.
     The server calls the SAP XSUAA token endpoint with Basic Auth
     (Base64 client_id:client_secret), caches the access token, and refreshes
     it automatically before it expires. No manual token management needed.

  2. Authorization header (legacy HTTP) — pass the token per-request as
     Authorization: Bearer <token>.

  3. CALM_TOKEN env var (stdio / local dev) — static token for development.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from src.calm.tools import (
    advanced_write,
    health,
    processes,
    processes_write,
    projects,
    projects_write,
    scopes,
    scopes_write,
    tasks_write,
    teams,
    test_cases,
    test_cases_write,
    timeboxes,
)

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("calm-mcp")


def _resolve_client_cert() -> str | tuple[str, str] | None:
    """Return a requests-compatible `cert` value for x509/mTLS, or None.

    Accepts either file paths (CALM_CLIENT_CERT [+ CALM_CLIENT_KEY]) or inline PEM
    (CALM_CLIENT_CERT_PEM [+ CALM_CLIENT_KEY_PEM]), the latter written to temp files
    for the process lifetime.
    """
    cert_path = os.getenv("CALM_CLIENT_CERT")
    key_path = os.getenv("CALM_CLIENT_KEY")
    cert_pem = os.getenv("CALM_CLIENT_CERT_PEM")
    key_pem = os.getenv("CALM_CLIENT_KEY_PEM")

    if cert_pem:
        import tempfile

        cf = tempfile.NamedTemporaryFile(prefix="calm_cert_", suffix=".pem", delete=False)
        cf.write(cert_pem.encode())
        cf.close()
        cert_path = cf.name
        if key_pem:
            kf = tempfile.NamedTemporaryFile(prefix="calm_key_", suffix=".pem", delete=False)
            kf.write(key_pem.encode())
            kf.close()
            key_path = kf.name

    if cert_path and key_path:
        return (cert_path, key_path)
    if cert_path:
        return cert_path  # combined cert+key PEM
    return None


def _maybe_init_token_manager() -> bool:
    """Initialise the client-credentials token manager if credentials are set.

    Prefers x509/mTLS when a client certificate is configured; otherwise uses the
    client_secret (Basic auth) flow.
    """
    client_id = os.getenv("CALM_CLIENT_ID")
    if not client_id:
        return False

    from src.calm.token_manager import init_token_manager

    client_cert = _resolve_client_cert()
    if client_cert:
        from src.calm.config import get_cert_auth_url

        auth_url = get_cert_auth_url()
        init_token_manager(client_id=client_id, auth_url=auth_url, client_cert=client_cert)
        log.info("Token manager initialised in x509/mTLS mode (client_id=%s, auth_url=%s)", client_id, auth_url)
        return True

    client_secret = os.getenv("CALM_CLIENT_SECRET")
    if client_secret:
        from src.calm.config import get_auth_url

        auth_url = get_auth_url()
        init_token_manager(client_id=client_id, client_secret=client_secret, auth_url=auth_url)
        log.info("Token manager initialised in client_secret mode (client_id=%s, auth_url=%s)", client_id, auth_url)
        return True

    log.warning("CALM_CLIENT_ID set but no CALM_CLIENT_SECRET or client certificate found.")
    return False


class _TrustProxyMiddleware:
    """Rewrites the Host header to 'localhost' before the MCP transport security check.

    In k8s/reverse-proxy deployments the Host header is the internal service name
    (e.g. mcp-calm.genai-mcp), which some versions of the MCP SDK reject with 421.
    The cluster ingress already handles external exposure so disabling the check here
    is safe.  Set MCP_TRUST_PROXY=false to opt out.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"host"]
            headers.append((b"host", b"localhost"))
            scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)


mcp = FastMCP("sap-cloud-alm")

projects.register(mcp)
processes.register(mcp)
scopes.register(mcp)
test_cases.register(mcp)
timeboxes.register(mcp)
teams.register(mcp)
health.register(mcp)

# Write tools (guarded by CALM_ENABLE_WRITES)
tasks_write.register(mcp)
projects_write.register(mcp)
processes_write.register(mcp)
scopes_write.register(mcp)
test_cases_write.register(mcp)
advanced_write.register(mcp)


def main() -> None:
    parser = argparse.ArgumentParser(description="SAP Cloud ALM MCP server")
    parser.add_argument("--http", action="store_true", help="Serve over Streamable HTTP instead of stdio.")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))
    args = parser.parse_args()

    using_managed_tokens = _maybe_init_token_manager()
    if not using_managed_tokens:
        log.info(
            "CALM_CLIENT_ID/CALM_CLIENT_SECRET not set — "
            "falling back to Authorization header or CALM_TOKEN env var."
        )

    if args.http:
        log.info("Starting CALM MCP on http://%s:%s", args.host, args.port)
        trust_proxy = os.getenv("MCP_TRUST_PROXY", "true").lower() not in ("false", "0", "no")
        middleware: list[Any] = [Middleware(_TrustProxyMiddleware)] if trust_proxy else []
        if trust_proxy:
            log.info("MCP_TRUST_PROXY enabled — Host header normalised for proxy deployments")
        mcp.run(transport="streamable-http", host=args.host, port=args.port, middleware=middleware)
    else:
        log.info("Starting CALM MCP on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
