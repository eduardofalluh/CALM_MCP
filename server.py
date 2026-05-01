"""
SAP Cloud ALM MCP Server — entry point.

Run
---
    python server.py               # stdio (Claude Desktop, MCP Inspector, Cursor)
    python server.py --http --port 8000   # HTTP for Syntax GenAI Studio

Token
-----
- HTTP transport: pass  x-calm-token  (and optionally x-calm-base-url) as
  request headers. The server is stateless — credentials come per-request.
- stdio / local dev: set CALM_TOKEN in your .env file.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from src.calm.tools import health, processes, projects, scopes, test_cases

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("calm-mcp")

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
        log.info("Starting CALM MCP on http://%s:%s", args.host, args.port)
        mcp.run(transport="streamable-http")
    else:
        log.info("Starting CALM MCP on stdio")
        mcp.run()


if __name__ == "__main__":
    main()
