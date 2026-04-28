"""
SAP Cloud ALM MCP Server

Exposes read-only Cloud ALM endpoints (projects, tasks, business processes,
solution processes, scopes, manual test cases) as MCP tools so any MCP-aware
agent (Claude Desktop, MCP Inspector, Syntax GenAI Studio, etc.) can call
them.

Token handling
--------------
For local development the token is supplied via the CALM_TOKEN environment
variable (loaded from a `.env` file if present). Optionally, if CALM_TOKEN
is not set but CALM_BASIC_AUTH is, the server will fetch an access token via
the OAuth2 client_credentials flow on startup. This mirrors the existing
`get_calm_token()` helper used by the standalone Python tools.

Run
---
    # stdio (default, used by Claude Desktop and MCP Inspector)
    python server.py

    # HTTP (streamable-http transport, useful for remote agents)
    python server.py --http --port 8000
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

import calm_client

# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,  # MCP stdio transport reserves stdout for protocol
)
log = logging.getLogger("calm-mcp")

BASE_URL = os.getenv("CALM_BASE_URL", calm_client.DEFAULT_BASE_URL)
AUTH_URL = os.getenv("CALM_AUTH_URL", calm_client.DEFAULT_AUTH_URL)


def _resolve_token() -> Optional[str]:
    """Return the bearer token to use for CALM API calls.

    Resolution order:
      1. CALM_TOKEN env var (preferred for local dev).
      2. CALM_BASIC_AUTH env var -> client_credentials flow.
      3. None -> tools will return an explicit error to the caller.
    """
    direct = os.getenv("CALM_TOKEN")
    if direct:
        log.info("Using CALM_TOKEN from environment")
        return direct.strip()

    basic = os.getenv("CALM_BASIC_AUTH")
    if basic:
        log.info("CALM_TOKEN not set, fetching via client_credentials")
        try:
            return calm_client.fetch_token(basic.strip(), AUTH_URL)
        except Exception as exc:  # noqa: BLE001
            log.error("client_credentials token fetch failed: %s", exc)
            return None

    log.warning(
        "No CALM_TOKEN or CALM_BASIC_AUTH found in environment. "
        "Tool calls will fail until one is provided."
    )
    return None


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP("sap-cloud-alm")


def _token_or_error() -> str:
    """Lazily resolve the token on each call so a refreshed .env is picked up.

    Raises a RuntimeError that FastMCP will surface as a tool error if no
    token is available.
    """
    token = _resolve_token()
    if not token:
        raise RuntimeError(
            "No CALM token available. Set CALM_TOKEN (or CALM_BASIC_AUTH) "
            "in your environment / .env file."
        )
    return token


@mcp.tool()
def get_calm_projects() -> list[dict]:
    """List all Cloud ALM projects visible to the configured tenant.

    Returns a list of {ID, Name, Status, Purpose}. Status is human-readable
    ("Active" / "Hidden").
    """
    return calm_client.get_projects(_token_or_error(), BASE_URL)


@mcp.tool()
def get_calm_tasks(project_id: str) -> list[dict]:
    """Return all tasks for a Cloud ALM project.

    Args:
        project_id: The CALM project ID (use `get_calm_projects` to discover).

    Each task has: ID, Title, Type (Roadmap Task / Project Task / User Story /
    Sub-task / Requirement / Defect / Quality Gate / Checklist Item) and
    Status (Open / In Progress / Blocked / Done / Not Relevant).
    """
    if not project_id:
        raise ValueError("project_id is required")
    return calm_client.get_tasks(project_id, _token_or_error(), BASE_URL)


@mcp.tool()
def get_calm_business_processes() -> list[dict]:
    """List all CALM business processes (process authoring API).

    Returns a list of {ID, Name, Description}.
    """
    return calm_client.get_business_processes(_token_or_error(), BASE_URL)


@mcp.tool()
def get_calm_solution_processes() -> list[dict]:
    """List all CALM solution processes (process authoring API).

    Returns a list of {ID, Name, Description, Status, Countries, State}.
    """
    return calm_client.get_solution_processes(_token_or_error(), BASE_URL)


@mcp.tool()
def get_calm_scopes() -> list[dict]:
    """List all CALM process-management scopes.

    Returns a list of {ID, Project ID, Name, Description}.
    """
    return calm_client.get_scopes(_token_or_error(), BASE_URL)


@mcp.tool()
def get_calm_test_cases() -> list[dict]:
    """List all manual test cases from the CALM test management API.

    Returns a list of {Project ID, Scope ID, Solution Process ID, Title,
    Prepared, Priority}. Priority is human-readable
    ("Very High" / "High" / "Medium" / "Low").
    """
    return calm_client.get_test_cases(_token_or_error(), BASE_URL)


@mcp.tool()
def calm_health() -> dict:
    """Diagnostic tool. Confirms the MCP server is up and reports whether a
    token is currently resolvable. Does NOT make a live CALM API call.
    """
    has_token = bool(os.getenv("CALM_TOKEN") or os.getenv("CALM_BASIC_AUTH"))
    return {
        "server": "sap-cloud-alm",
        "base_url": BASE_URL,
        "auth_url": AUTH_URL,
        "token_configured": has_token,
        "token_source": (
            "CALM_TOKEN" if os.getenv("CALM_TOKEN")
            else "CALM_BASIC_AUTH" if os.getenv("CALM_BASIC_AUTH")
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="SAP Cloud ALM MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Serve over Streamable HTTP instead of stdio.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "127.0.0.1"),
        help="Host for HTTP transport (default 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Port for HTTP transport (default 8000).",
    )
    args = parser.parse_args()

    if args.http:
        # FastMCP uses the `streamable-http` transport for HTTP serving.
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        log.info("Starting CALM MCP on http://%s:%s", args.host, args.port)
        mcp.run(transport="streamable-http")
    else:
        log.info("Starting CALM MCP on stdio")
        mcp.run()  # default = stdio


if __name__ == "__main__":
    main()
