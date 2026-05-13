# SAP Cloud ALM MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
SAP Cloud ALM read-only endpoints as MCP tools. Any MCP-compatible client —
Claude Desktop, MCP Inspector, Cursor, Syntax GenAI Studio — can attach and call
the tools directly.

---

## Authentication

The server implements **OAuth2 Client Credentials flow** to fetch and cache bearer tokens automatically. No hourly copy-paste required.

### How it works

SAP Cloud ALM uses two separate URLs:

| Purpose | URL | Auth method |
|---------|-----|-------------|
| **Token endpoint** | `https://<tenant>.authentication.<region>.hana.ondemand.com/oauth/token` | Basic Auth with `Base64(client_id:client_secret)` |
| **API endpoint** | `https://<tenant>.<region>.alm.cloud.sap/api/...` | Bearer token from token endpoint |

The `TokenManager` (in `src/calm/token_manager.py`) calls the token endpoint once on first use, caches the access token, and silently refreshes it 60 seconds before expiry. You never touch a token manually.

### Token resolution (fallback order)

1. **Client Credentials** (preferred) — set `CALM_CLIENT_ID` + `CALM_CLIENT_SECRET`. Server fetches and manages tokens.
2. **Header** — pass `Authorization: Bearer <token>` in request headers (legacy HTTP mode).
3. **Env var** — set `CALM_TOKEN` (local dev / stdio).

---

## Project layout

```
CALM_MCP/
├── src/
│   └── calm/
│       ├── client.py           # CALM REST API wrappers
│       ├── models.py           # CALMHeaders Pydantic model
│       ├── token_manager.py    # OAuth2 client credentials + token cache
│       ├── dependencies.py     # get_calm_headers() — resolves token
│       └── tools/
│           ├── projects.py     # get_calm_projects, get_calm_tasks
│           ├── processes.py    # get_calm_business_processes, get_calm_solution_processes
│           ├── scopes.py       # get_calm_scopes
│           ├── test_cases.py   # get_calm_test_cases
│           └── health.py       # calm_health
├── tests/
│   └── test_server.py
├── server.py                   # Entry point
├── requirements.txt
└── .env.example
```

## Tools exposed

| Tool | Description | Args |
|------|-------------|------|
| `get_calm_projects` | List all projects | — |
| `get_calm_tasks` | List tasks for a project | `project_id` |
| `get_calm_business_processes` | List business processes | — |
| `get_calm_solution_processes` | List solution processes | — |
| `get_calm_scopes` | List process-management scopes | — |
| `get_calm_test_cases` | List manual test cases | — |
| `calm_health` | Diagnostic — server up, token configured? | — |

---

## 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
```

## 2. Configure credentials

### Option A: Client Credentials (recommended for production)

For a deployed GenAI Studio MCP server, we need the SAP OAuth **client ID and client secret** plus the tenant identity zone and region zone from BTP. These are deployment settings for the MCP server, not values that a user pastes into the GenAI Studio chat or Bearer token field.

Register an OAuth client in the SAP BTP subaccount that has access to the Cloud ALM APIs, then set:

```bash
cp .env.example .env
# Open .env and set:
IDENTITY_ZONE=<your-btp-identity-zone>
REGION_ZONE=<your-btp-region-zone>
CALM_CLIENT_ID=<your-oauth-client-id>
CALM_CLIENT_SECRET=<your-oauth-client-secret>
```

The server derives the URLs from those BTP values:

```bash
CALM_AUTH_URL=https://<identity-zone>.authentication.<region-zone>.hana.ondemand.com/oauth/token
CALM_BASE_URL=https://<identity-zone>.<region-zone>.alm.cloud.sap
```

You can still set `CALM_AUTH_URL` or `CALM_BASE_URL` directly if a deployment needs explicit URL overrides.

The server automatically fetches a token on first use and refreshes it before expiry.

### Option B: Bearer token env var (local dev / stdio)

```bash
cp .env.example .env
# Open .env and set:
CALM_TOKEN=<your-bearer-token>
```

### Option C: Bearer token header (HTTP legacy / per-request)

No `.env` needed. Pass credentials as request headers on each call:

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | Yes | Bearer token for the CALM tenant, formatted as `Bearer <token>` |
| `x-calm-base-url` | No | Override tenant URL for that request |

Token resolution order: client credentials → `Authorization` header → `CALM_TOKEN` env var → error.

## 3. Run

```bash
# stdio — Claude Desktop, MCP Inspector, Cursor
python3 server.py

# HTTP — Syntax GenAI Studio remote MCP
python3 server.py --http --host 0.0.0.0 --port 8000
```

## 4. Test

```bash
python3 tests/test_server.py    # must show 19/19 passed
```

## 5. MCP Inspector (interactive)

```bash
npx @modelcontextprotocol/inspector python3 server.py
```

## 6. Connect from Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sap-cloud-alm": {
      "command": "python3",
      "args": ["/absolute/path/to/CALM_MCP/server.py"],
      "env": {
        "IDENTITY_ZONE": "<your-btp-identity-zone>",
        "REGION_ZONE": "<your-btp-region-zone>",
        "CALM_CLIENT_ID": "your-client-id",
        "CALM_CLIENT_SECRET": "your-client-secret"
      }
    }
  }
}
```

## 7. Connect from Syntax GenAI Studio

### With client credentials (recommended)

Deploy the MCP server in HTTP mode and expose it over HTTPS so GenAI Studio can reach it.

What the deployed MCP server needs as environment variables:

| Variable | Required | Purpose |
|----------|----------|---------|
| `IDENTITY_ZONE` | Yes | BTP identity zone, for example `illumiti-corp-cloudalm` |
| `REGION_ZONE` | Yes | BTP region zone, for example `eu10` |
| `CALM_CLIENT_ID` | Yes | OAuth client ID from SAP BTP |
| `CALM_CLIENT_SECRET` | Yes | OAuth client secret from SAP BTP |
| `CALM_BASE_URL` | Optional | Explicit SAP Cloud ALM API base URL override |
| `CALM_AUTH_URL` | Optional | Explicit SAP XSUAA token URL override |
| `MCP_HOST` | Recommended | Use `0.0.0.0` in hosted/container deployments |
| `MCP_PORT` | Recommended | Port exposed by the hosting platform, for example `8000` |
| `LOG_LEVEL` | Optional | Defaults to `INFO` |

What GenAI Studio needs:

| Studio setting | Value |
|----------------|-------|
| MCP server URL | `https://<deployed-host>/mcp` |
| Bearer token | Leave empty when using client credentials |
| Custom headers | None required for the recommended deployment |

Connection steps:

1. Start the server with `python3 server.py --http --host 0.0.0.0 --port 8000`, or set `MCP_HOST=0.0.0.0` and `MCP_PORT=8000`.
2. In Studio, go to agent → **Actions and Tools** → **Add Tool** → **MCP Server**.
3. Enter `https://<deployed-host>/mcp`.
4. Leave the "Bearer token" field **empty**. The server derives the SAP URLs from `IDENTITY_ZONE` + `REGION_ZONE`, then uses `CALM_CLIENT_ID` + `CALM_CLIENT_SECRET` to fetch SAP tokens.

### Legacy (Authorization header)

1. Deploy server to your network (HTTP mode)
2. Studio → agent → **Actions and Tools** → **Add Tool** → **MCP Server** → `https://<host>/mcp`
3. Set `Authorization` as a request header in Studio's MCP config, with value `Bearer <token>`
4. Paste a bearer token each time it expires

---

## Adding more CALM endpoints

Each tool is ~10 lines. To add an "incidents" endpoint:

1. Add `get_incidents(token, base_url)` to `src/calm/client.py`
2. Create `src/calm/tools/incidents.py` with a `register(mcp)` function
3. Import and call `incidents.register(mcp)` in `server.py`
4. Restart — the new tool is immediately discoverable

## Switching client tenants

```bash
IDENTITY_ZONE=<client-identity-zone>
REGION_ZONE=<client-region-zone>
CALM_CLIENT_ID=<client-id-for-that-tenant>
CALM_CLIENT_SECRET=<client-secret-for-that-tenant>
```

No code changes required.

---

## How TokenManager works

When you set `CALM_CLIENT_ID` + `CALM_CLIENT_SECRET`:

1. On first tool call, `TokenManager` POSTs to the SAP XSUAA token endpoint with Basic Auth
2. SAP returns `{ "access_token": "...", "expires_in": 3600 }`
3. Token is cached in memory
4. On subsequent calls within the TTL, the cached token is reused
5. When the token expires, `TokenManager` automatically fetches a fresh one
6. No token field in Studio UI needed — it all happens transparently

This is OAuth2 Client Credentials flow — the standard for server-to-server authentication.
