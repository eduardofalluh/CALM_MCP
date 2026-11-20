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

from src.calm.toon_middleware import ToonOutputMiddleware, TruncationAlertMiddleware
from src.calm.tools import (
    admin,
    advanced_write,
    health,
    oauth_info,
    test_repo,
    test_repo_write,
    unified,
    user_uuid_helper,
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

    from src.calm.config import TenantNotConfiguredError

    try:
        return _init_env_token_manager(client_id)
    except TenantNotConfiguredError as exc:
        # There is no built-in tenant, so the env credential can't be used until
        # one is configured. Keep serving: requests that carry their own x-calm-*
        # tenant headers still work, and env-credential requests get this error.
        log.error("CALM_CLIENT_ID is set but the env credential is disabled. %s", exc)
        return False


def _init_env_token_manager(client_id: str) -> bool:
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


def _startup_auth_check() -> None:
    """Fetch one token at startup so a bad/corrupted credential fails loudly here
    instead of as a confusing 'invalid credentials' 401 on the first data request.

    Never crashes the server: XSUAA may be briefly unreachable, and the request-time
    path still works once it recovers. We only *log* the outcome, with an actionable
    hint for the most common deployment mistake — a secret containing '$' that the
    shell / Docker / k8s expanded away because it wasn't single-quoted.
    """
    from src.calm.token_manager import get_managed_token

    try:
        token = get_managed_token()
        if token:
            log.info("CALM auth self-check OK — acquired a token at startup (len=%d).", len(token))
        return
    except Exception as exc:  # noqa: BLE001 - want the full message in the log
        log.error("CALM auth self-check FAILED at startup: %s", exc)
        # Note: we can't inspect the secret for a '$' here — if the shell already
        # expanded it, the '$...' tail is gone by the time we read the env var — so
        # we always surface this as the most common cause of a startup 401.
        log.error(
            "Most common cause: CALM_CLIENT_SECRET was corrupted in transit. SAP "
            "service-key secrets often contain '$'; an unquoted shell export, "
            "Dockerfile ENV, docker-compose, or k8s value expands everything after "
            "'$' to empty, so CALM receives a truncated secret. Single-quote the "
            "value (CALM_CLIENT_SECRET='...$...') or escape it as '\\$' so it reaches "
            "the server intact. Also verify the id/secret are current and that "
            "CALM_IDENTITY_ZONE/CALM_REGION_ZONE match the service key."
        )
        log.error(
            "The server will keep running and retry on each request, but CALM calls "
            "will return 'invalid credentials' until the credential is fixed."
        )


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

# Encode tool text output as TOON (token-efficient) by default; set
# CALM_OUTPUT_FORMAT=json to revert per-agent with no redeploy. Structured
# content on the wire stays JSON, so clients reading it are unaffected.
mcp.add_middleware(ToonOutputMiddleware())

# Alert the user whenever a paged list read is cut short by a safety ceiling
# (never by the normal 100-per-page cap, which is fully paged). Applies to every
# collection, since all list getters page through client._get_all.
mcp.add_middleware(TruncationAlertMiddleware())

# ============================================================================
# PHASE 3 COMPLETE: Tool Consolidation
# ============================================================================
# Unified tool consolidates 41 basic CRUD operations (15 read + 26 write)
# into a single calm_resource() interface for maximum context efficiency.
#
# Result: 75 tools → 28 tools (62.7% reduction, 12,500+ token savings)
#
# Removed Tools (41 legacy CRUD tools replaced by unified):
#   - Basic reads: projects, tasks, requirements, teams, processes, timeboxes,
#     scopes, test_cases, tags, features, test_plans, users, customization
#   - Basic writes: create/update/delete for projects, tasks, requirements,
#     scopes, test_cases, timeboxes, business_processes, solution_processes,
#     tags, features, test_plans
#
# Kept Tools (specialized operations not in unified):
#   - Unified tool (calm_resource)
#   - Helper tools (health, oauth, user_uuid)
#   - Advanced operations (calm_api_write, calm_api_delete)
#   - BTP Test Management (13 TM-specific tools)
# ============================================================================

# Core unified tool - handles 15 resource types with 5 operations each
unified.register(mcp)

# Helper/utility tools (not consolidated - specialized functionality)
user_uuid_helper.register(mcp)
oauth_info.register(mcp)
health.register(mcp)

# Admins add / change / remove clients (SAP Cloud ALMs) from a chat; secrets only via a terminal command
admin.register(mcp)

# Advanced write operations (generic escape hatches for any CALM API endpoint)
advanced_write.register(mcp)

# BTP Test Management OData repository (separate system, specialized tools)
# Reads need TM_* config / x-tm-* headers; writes guarded by TM_ENABLE_WRITES
test_repo.register(mcp)
test_repo_write.register(mcp)


def main() -> None:
    parser = argparse.ArgumentParser(description="SAP Cloud ALM MCP server")
    parser.add_argument("--http", action="store_true", help="Serve over Streamable HTTP instead of stdio.")
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))
    args = parser.parse_args()

    using_managed_tokens = _maybe_init_token_manager()
    if not using_managed_tokens:
        log.info(
            "No usable server env credential — requests use x-calm-* headers, "
            "the Authorization header or the CALM_TOKEN env var."
        )
    else:
        # In the background: the check only logs, so a slow XSUAA must never
        # delay the server from accepting requests.
        import threading

        threading.Thread(target=_startup_auth_check, name="calm-startup-auth-check", daemon=True).start()

    # A file path names a file on the machine the MCP runs on: only meaningful (and
    # only safe) when that is the user's own machine, never the shared HTTP server.
    from src.calm import doc_content
    doc_content.LOCAL_FILES = not args.http

    if args.http:
        log.info("Starting CALM MCP on http://%s:%s", args.host, args.port)
        trust_proxy = os.getenv("MCP_TRUST_PROXY", "true").lower() not in ("false", "0", "no")
        middleware: list[Any] = [Middleware(_TrustProxyMiddleware)] if trust_proxy else []
        if trust_proxy:
            log.info("MCP_TRUST_PROXY enabled — Host header normalised for proxy deployments")

        # Outermost, so it sees the real Host before _TrustProxyMiddleware rewrites it:
        # serves the OAuth metadata and asks a caller with no credential to sign in.
        from src.calm.oauth import OAuthMiddleware
        middleware.insert(0, Middleware(OAuthMiddleware))
        log.info("OAuth sign-in for %s (set MCP_PUBLIC_URL to the address clients use)",
                 os.getenv("MCP_PUBLIC_URL") or "the address each request names")

        mcp.run(transport="streamable-http", host=args.host, port=args.port, middleware=middleware)
    else:
        log.info("Starting CALM MCP on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
