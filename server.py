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


def _maybe_init_token_manager() -> bool:
    """Initialise the client-credentials token manager if credentials are set."""
    client_id = os.getenv("CALM_CLIENT_ID")
    client_secret = os.getenv("CALM_CLIENT_SECRET")
    if not (client_id and client_secret):
        return False

    from src.calm.config import get_auth_url
    from src.calm.token_manager import init_token_manager

    auth_url = get_auth_url()
    init_token_manager(client_id=client_id, client_secret=client_secret, auth_url=auth_url)
    log.info("Token manager initialised (client_id=%s, auth_url=%s)", client_id, auth_url)
    return True


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

    using_managed_tokens = _maybe_init_token_manager()
    if not using_managed_tokens:
        log.info(
            "CALM_CLIENT_ID/CALM_CLIENT_SECRET not set — "
            "falling back to Authorization header or CALM_TOKEN env var."
        )

    if args.http:
        log.info("Starting CALM MCP on http://%s:%s", args.host, args.port)
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        log.info("Starting CALM MCP on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
