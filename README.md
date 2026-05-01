# SAP Cloud ALM MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
SAP Cloud ALM read-only endpoints as MCP tools. Any MCP-compatible client —
Claude Desktop, MCP Inspector, Cursor, Syntax GenAI Studio — can attach and call
the tools directly.

---

## Project layout

```
CALM_MCP/
├── src/
│   └── calm/
│       ├── client.py          # CALM REST API wrappers
│       ├── models.py          # CALMHeaders Pydantic model
│       ├── dependencies.py    # get_calm_headers() — resolves token from header or env var
│       └── tools/
│           ├── projects.py    # get_calm_projects, get_calm_tasks
│           ├── processes.py   # get_calm_business_processes, get_calm_solution_processes
│           ├── scopes.py      # get_calm_scopes
│           ├── test_cases.py  # get_calm_test_cases
│           └── health.py      # calm_health
├── tests/
│   └── test_server.py
├── server.py                  # Entry point
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
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
```

## 2. Configure credentials

### Local dev / stdio (e.g. Claude Desktop)

```bash
cp .env.example .env
# Open .env and set CALM_TOKEN=<your bearer token>
```

### HTTP transport (e.g. Syntax GenAI Studio)

No `.env` needed on the server. The client passes credentials as request headers
on every call:

| Header | Required | Description |
|--------|----------|-------------|
| `x-calm-token` | Yes | Bearer token for the CALM tenant |
| `x-calm-base-url` | No | Override tenant URL (defaults to `illumiti-corp-cloudalm`) |

Token resolution order: `x-calm-token` header → `CALM_TOKEN` env var → error.

## 3. Run

```bash
# stdio — Claude Desktop, MCP Inspector, Cursor
python server.py

# HTTP — Syntax GenAI Studio remote MCP
python server.py --http --port 8000
```

## 4. Test

```bash
python tests/test_server.py    # must show 19/19 passed
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
      "command": "python",
      "args": ["/absolute/path/to/CALM_MCP/server.py"],
      "env": { "CALM_TOKEN": "paste-token-here" }
    }
  }
}
```

## 7. Connect from Syntax GenAI Studio

1. `python server.py --http --port 8000`
2. Expose via ngrok or deploy to your network
3. Studio → agent → **Actions and Tools** → **Add Tool** → **MCP Server** → `https://<host>/mcp`
4. Set `x-calm-token` as a request header in Studio's MCP config

---

## Adding more CALM endpoints

Each tool is ~10 lines. To add an "incidents" endpoint:

1. Add `get_incidents(token, base_url)` to `src/calm/client.py`
2. Create `src/calm/tools/incidents.py` with a `register(mcp)` function
3. Import and call `incidents.register(mcp)` in `server.py`
4. Restart — the new tool is immediately discoverable

## Switching client tenants

```bash
CALM_BASE_URL=https://<client>.<region>.alm.cloud.sap
CALM_TOKEN=<token-for-that-tenant>
```

No code changes required.
