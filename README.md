# SAP Cloud ALM MCP Server

A local [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes SAP Cloud ALM read-only endpoints (projects, tasks, business
processes, solution processes, scopes, manual test cases) as MCP tools.

Once running, any MCP-compatible client — Claude Desktop, MCP Inspector,
Cursor, Syntax GenAI Studio, etc. — can attach the server and call the tools
just like the Python functions you already use in your existing CALM agent.

---

## Project layout

```
calm-mcp/
├── server.py            # FastMCP server — declares the MCP tools
├── calm_client.py       # HTTP wrappers for the CALM REST APIs (1:1 port of
│                        # the existing get_calm_* functions)
├── requirements.txt
├── .env.example         # Copy to `.env` and fill in CALM_TOKEN
└── README.md
```

## Tools exposed

| MCP tool name                  | What it does                                                    | Args         |
| ------------------------------ | --------------------------------------------------------------- | ------------ |
| `get_calm_projects`            | List all projects                                               | —            |
| `get_calm_tasks`               | List all tasks for a given project                              | `project_id` |
| `get_calm_business_processes`  | List business processes (process authoring API)                 | —            |
| `get_calm_solution_processes`  | List solution processes (process authoring API)                 | —            |
| `get_calm_scopes`              | List scopes (process management API)                            | —            |
| `get_calm_test_cases`          | List manual test cases (test management API)                    | —            |
| `calm_health`                  | Diagnostic — confirms server is up and a token is configured    | —            |

All response shapes are identical to those returned by the existing standalone
Python tools (same field names, same status / type / priority mappings).

---

## 1. Install

You need Python 3.10+.

```bash
cd calm-mcp
python -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .\.venv\Scripts\activate         # Windows PowerShell

pip install -r requirements.txt
```

## 2. Configure the token

```bash
cp .env.example .env
```

Open `.env` and set **one** of:

- `CALM_TOKEN=...` — paste a bearer token (what your AI team meant by "make
  a local token for now"). Easiest for local dev.
- `CALM_BASIC_AUTH=...` — the base64-encoded `client_id:client_secret`
  string from the original `get_calm_token()` snippet. The server will fetch
  a fresh access token automatically.

Optionally override `CALM_BASE_URL` / `CALM_AUTH_URL` to point at a different
client tenant. Defaults match the `illumiti-corp-cloudalm` tenant used by
the existing agent.

## 3. Run

```bash
# Default: stdio transport (Claude Desktop, MCP Inspector, Cursor, ...)
python server.py

# Or HTTP transport, e.g. for Syntax GenAI Studio remote MCP:
python server.py --http --port 8000
```

When run over stdio nothing is printed to stdout (that channel is reserved
for the MCP protocol); logs go to stderr.

---

## 4. Try it with MCP Inspector (recommended first step)

The official inspector is the fastest way to confirm everything works:

```bash
# in another terminal, with your venv active
mcp dev server.py
```

This launches a small web UI where you can:

1. See the 7 tools the server advertises.
2. Click `calm_health` -> Run. You should see `token_configured: true`.
3. Click `get_calm_projects` -> Run. You should see real CALM data come back.

## 5. Connect from Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows) and add:

```json
{
  "mcpServers": {
    "sap-cloud-alm": {
      "command": "python",
      "args": ["/absolute/path/to/calm-mcp/server.py"],
      "env": {
        "CALM_TOKEN": "paste-token-here"
      }
    }
  }
}
```

Restart Claude Desktop. The "sap-cloud-alm" server should appear in the
tools panel and Claude can now call any of the seven tools directly.

## 6. Connect from Syntax GenAI Studio

Studio supports remote MCP servers over HTTP. Once you're ready to expose
the server beyond your laptop:

1. Run `python server.py --http --port 8000`.
2. Put it behind a reachable URL (ngrok for testing, or deploy to your
   internal network).
3. In Studio -> your agent -> **Actions and Tools** -> **Add Tool** ->
   **MCP Server**, point it at `https://<your-host>/mcp`.

The same 7 tools will appear and you can swap them in for the existing
Python tools you have today.

---

## How the token swap works for clients

Today the existing Python tools talk to one tenant (`illumiti-corp-cloudalm`)
with credentials hardcoded into `get_calm_token`. With this MCP, switching
to a different client's CALM is just two env-var changes per deployment:

```bash
CALM_BASE_URL=https://<client>.<region>.alm.cloud.sap
CALM_TOKEN=<token-issued-by-the-client-tenant>
```

No code changes required. That's the main win versus the current setup.

---

## Adding more CALM endpoints later

Each tool is roughly 10 lines: an HTTP wrapper in `calm_client.py` plus a
`@mcp.tool()` decorated function in `server.py`. To add e.g. an "incidents"
endpoint:

1. In `calm_client.py`, add a `get_incidents(token, base_url)` function
   following the same pattern as `get_projects`.
2. In `server.py`, add:

   ```python
   @mcp.tool()
   def get_calm_incidents() -> list[dict]:
       """List CALM incidents."""
       return calm_client.get_incidents(_token_or_error(), BASE_URL)
   ```

3. Restart the server. The new tool is discoverable immediately.
