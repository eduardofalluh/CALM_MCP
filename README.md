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

1. **Request headers** (preferred for HTTP / multi-tenant) — client sends `x-calm-client-id` + `x-calm-client-secret` (+ optional zone headers). Server fetches and caches a token per tenant.
2. **Server env vars** — set `CALM_CLIENT_ID` + `CALM_CLIENT_SECRET` at startup. Single-tenant server-managed mode.
3. **Authorization header** — pass `Authorization: Bearer <token>` per request (legacy HTTP).
4. **Env var** — set `CALM_TOKEN` (local dev / stdio).

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
│           ├── health.py       # calm_health
│           ├── tasks_write.py       # create/update_calm_task (guarded)
│           ├── projects_write.py    # create/update_calm_project (guarded)
│           ├── processes_write.py   # create/update business & solution processes (guarded)
│           ├── scopes_write.py      # create/update_calm_scope (guarded)
│           └── test_cases_write.py  # create/update_calm_test_case (guarded)
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

### Write tools (guarded)

Disabled unless `CALM_ENABLE_WRITES=true` is set. When off, these tools are still
advertised but return a clear error, so the server is read-only by default and
nothing can accidentally change the tenant.

| Tool | Description | Args |
|------|-------------|------|
| `create_calm_task` | Create a task in a project | `project_id`, `title`, `task_type` (+ optional `status`, `start_date`, `due_date`, `assignee_id`, `description`) |
| `update_calm_task` | Partial-update a task | `task_id` (+ any of `title`, `task_type`, `status`, `start_date`, `due_date`, `assignee_id`, `description`, `obsolete`) |
| `create_calm_project` | Create a project | `name` (+ optional `status`, `purpose`, `operational_status`) |
| `update_calm_project` | Partial-update a project | `project_id` (+ any of `name`, `status`, `purpose`, `operational_status`) |
| `create_calm_business_process` | Create a business process | `name` (+ optional `description`) |
| `update_calm_business_process` | Partial-update a business process | `business_process_id` (+ `name`, `description`) |
| `create_calm_solution_process` | Create a solution process | `name` (+ optional `description`, `status`, `countries`, `state`) |
| `update_calm_solution_process` | Partial-update a solution process | `solution_process_id` (+ any of the above) |
| `create_calm_scope` | Create a process-management scope | `project_id`, `name` (+ optional `description`) |
| `update_calm_scope` | Partial-update a scope | `scope_id` (+ `name`, `description`) |
| `create_calm_test_case` | Create a manual test case | `title` (+ optional `project_id`, `scope_id`, `solution_process_id`, `priority`, `is_prepared`, `activities`, `references`, process-link fields) |
| `update_calm_test_case` | Partial-update a test case | `test_case_id` (+ any of `title`, `scope_id`, `solution_process_id`, `priority`, `is_prepared`, `if_match`) |
| `delete_calm_task` | Delete a task | `task_id` |
| `delete_calm_business_process` | Delete a business process | `business_process_id` (+ optional `if_match`) |
| `delete_calm_solution_process` | Delete a solution process | `solution_process_id` (+ optional `if_match`) |
| `delete_calm_scope` | Delete a scope | `scope_id` (+ optional `if_match`) |
| `delete_calm_test_case` | Delete a test case (`force` incl. runs/results) | `test_case_id` (+ optional `force`, `if_match`) |

`task_type`/`status` (tasks), `status` (projects: Active/Hidden), and `priority`
(test cases: Very High/High/Medium/Low) accept human labels or raw CALM codes.
Because task status codes are type-specific, pass `task_type` alongside a human
`status` when updating a task.

### Write contract notes (reconciled against SAP Help Portal docs, v2 — 2026-07-17)

- **Single-entity URL is a path segment** (`/entity/{id}`) for every API, including
  OData — *not* `Entity('id')`. Confirmed verbatim from the Help Portal.
- **No CSRF token** (stateless OAuth Bearer).
- **`If-Match: <etag>` is required on PATCH/DELETE** for the OData services
  (Process Authoring, Test Management — missing → 428, stale → 412) **and for
  Projects `PATCH`** (etag = the project's numeric `etag` field). Update/delete
  tools **auto-fetch the ETag** or accept `if_match`. ETag source: response header
  (Process Authoring), `modifiedAt` (Test Management), or `etag` body field
  (Projects). Tasks and **Scopes need no If-Match** (confirmed).
- **Tasks:** `assigneeId` is the assignee's **email**; `priorityId` numeric
  (10/20/30/40); sub-tasks (`CALMST`) use the task `CIPTK*` status codes; `CALMRISK`
  is a valid type. The full documented field set (subStatus, approvalState, scopeId,
  storyPoints, effort, workstream, involvedParties, classificationId,
  customField1–20, …) is reachable via the `extra_fields` dict.
- **Projects:** PATCH body is limited to `name`/`deploymentPlanId`/`programId`;
  `status`/`operationalStatus`/`purpose`/`phaseId` are **not** patchable via the API
  (`operationalStatus` enum: ONTRK/NATTN/CRIT). No project DELETE exists.
- **Solution process:** `countries` is a **comma-string** (`"DE,FR"`); the parent
  is the nested `businessProcess:{id}` object (`business_process_id`). Lifecycle
  (publish / new draft) is driven by dedicated action endpoints, not a status PATCH.
- **Test case:** id is `uuid`; `priorityCode` is **numeric** (10/20/30/40); the only
  status-like field is the boolean `isPrepared`. POST supports **deep insert** of
  `toActivities`/`toActions`/`toReferences` (deep *update* is not supported — edit
  nested items via their own endpoints). Process-linked test cases need all four of
  `solution_process_id`, `solution_process_flow_id`,
  `solution_process_flow_diagram_id`, `content_package_id` together.
- **Delete:** tasks, business/solution processes, scopes, and test cases support
  DELETE (no project delete exists). Test cases add a `force` variant that also
  removes runs/results (needs the `force-delete` scope).

> Contract now fully reconciled against the raw OpenAPI specs (CALM_TKM v1.0.29,
> CALM_PJM, CALM_PM) — no open documentation gaps. Payload shapes should still be
> smoke-tested against a live tenant before merging to main.

### Sub-entity tools

Typed tools for the documented sub-entities:

| Tool | Description |
|------|-------------|
| `create_calm_task_relation` / `delete_calm_task_relation` | Link/unlink tasks |
| `set_calm_task_tags` | Replace a task's tags (`"Group: Tag"`) |
| `create/update/delete_calm_task_comment` | Task comments |
| `create/update/delete_calm_timebox` | Project timeboxes |
| `assign_calm_scenario_versions` | Assign scenario versions to a scope |
| `update_calm_scope_assignments` | Scope/unscope solution processes |
| `update/delete_calm_test_activity` | Test-case activities (step groups) |
| `create/update/delete_calm_test_action` | Test-case actions (steps) |

### Generic escape hatch

For any endpoint without a dedicated tool (feature/document/hierarchy assignments,
workstreams, deliverables, programs, system groups, deployment plans, external
integrations, process-authoring assets/flows/diagrams/activities, publish/draft
actions, test-case applications/references/task assignments, …):

| Tool | Description |
|------|-------------|
| `calm_api_write` | `method` (POST/PATCH) + API-relative `path` + `body` (+ optional `if_match`) |
| `calm_api_delete` | API-relative `path` (+ optional `if_match`) |

`calm_api_*` do **not** auto-fetch ETags — pass `if_match` explicitly for the
OData services / Projects PATCH, or use the dedicated typed tool which does.

---

## 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt
```

## 2. Configure credentials

### Option A: Client-side headers (recommended for GenAI Studio / HTTP)

No `.env` file needed on the server. The MCP client (e.g. GenAI Studio) injects the four headers with every request. The server derives both the auth URL and the API base URL from the zone headers, fetches an OAuth token, and caches it per tenant automatically.

| Header | Required | Example |
|--------|----------|---------|
| `x-calm-identity-zone` | Yes | `illumiti-corp-cloudalm` |
| `x-calm-region-zone` | Yes | `eu10` |
| `x-calm-client-id` | Yes | `sb-cloud-alm-api!b175722\|sapcloudalm!b16907` |
| `x-calm-client-secret` | Yes | `<your-client-secret>` |
| `x-calm-base-url` | No | Explicit API base URL override |

A single server instance can serve multiple tenants — each request's headers are resolved independently and cached per `(client_id, auth_url)` pair.

### Option B: Server env vars (single-tenant server-managed)

Set credentials once at server startup. Useful when all users share the same CALM tenant.

```bash
cp .env.example .env
# Open .env and set:
IDENTITY_ZONE=<your-btp-identity-zone>
REGION_ZONE=<your-btp-region-zone>
CALM_CLIENT_ID=<your-oauth-client-id>
CALM_CLIENT_SECRET=<your-oauth-client-secret>
```

The server derives the URLs from those BTP values:

```
CALM_AUTH_URL → https://<identity-zone>.authentication.<region-zone>.hana.ondemand.com/oauth/token
CALM_BASE_URL → https://<identity-zone>.<region-zone>.alm.cloud.sap
```

You can still set `CALM_AUTH_URL` or `CALM_BASE_URL` directly if a deployment needs explicit URL overrides.

### Option C: Bearer token env var (local dev / stdio)

```bash
cp .env.example .env
# Open .env and set:
CALM_TOKEN=<your-bearer-token>
```

### Option D: Bearer token header (HTTP legacy / per-request)

Pass a pre-fetched token per request — no credential management by the server.

| Header | Description |
|--------|-------------|
| `Authorization` | `Bearer <token>` |
| `x-calm-base-url` | Optional tenant URL override |

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

### With client-side headers (recommended)

Deploy the MCP server with **no credential env vars** — credentials come entirely from GenAI Studio's header configuration. This is the recommended approach for multi-tenant or managed deployments.

**Server** only needs:

| Variable | Required | Purpose |
|----------|----------|---------|
| `MCP_HOST` | Recommended | `0.0.0.0` for hosted/container deployments |
| `MCP_PORT` | Recommended | Port exposed by the platform, e.g. `8000` |
| `LOG_LEVEL` | Optional | Defaults to `INFO` |

**GenAI Studio** MCP connection settings:

| Setting | Value |
|---------|-------|
| MCP server URL | `https://<deployed-host>/mcp` |
| Bearer token | Leave empty |
| Custom headers | See table below |

Custom headers to configure in Studio:

| Header | Value |
|--------|-------|
| `x-calm-identity-zone` | `illumiti-corp-cloudalm` |
| `x-calm-region-zone` | `eu10` |
| `x-calm-client-id` | `<your-oauth-client-id>` |
| `x-calm-client-secret` | `<your-oauth-client-secret>` |

Connection steps:

1. Start the server: `python3 server.py --http --host 0.0.0.0 --port 8000`
2. In Studio → agent → **Actions and Tools** → **Add Tool** → **MCP Server**
3. Enter `https://<deployed-host>/mcp`
4. Add the four headers above in Studio's custom headers field
5. Leave the "Bearer token" field empty — the server fetches SAP tokens using the header credentials

### With server env vars (single-tenant alternative)

Set `IDENTITY_ZONE`, `REGION_ZONE`, `CALM_CLIENT_ID`, `CALM_CLIENT_SECRET` on the server (see Option B above). Studio connects to `https://<host>/mcp` with no custom headers.

### Legacy (Authorization header)

Studio → agent → **Actions and Tools** → **Add Tool** → **MCP Server** → `https://<host>/mcp`  
Set `Authorization: Bearer <token>` as a custom header. Requires manual token refresh on expiry.

---

## Adding more CALM endpoints

Each tool is ~10 lines. To add an "incidents" endpoint:

1. Add `get_incidents(token, base_url)` to `src/calm/client.py`
2. Create `src/calm/tools/incidents.py` with a `register(mcp)` function
3. Import and call `incidents.register(mcp)` in `server.py`
4. Restart — the new tool is immediately discoverable

## Switching client tenants

**Header mode (recommended):** update the four `x-calm-*` headers in GenAI Studio. No server restart needed — each request is resolved independently and cached per tenant.

**Env var mode:** update `IDENTITY_ZONE`, `REGION_ZONE`, `CALM_CLIENT_ID`, `CALM_CLIENT_SECRET` and restart the server. No code changes required.

---

## How TokenManager works

On first use, `TokenManager` POSTs to the SAP XSUAA token endpoint with Basic Auth (`Base64(client_id:client_secret)`). SAP returns `{ "access_token": "...", "expires_in": 3600 }`. The token is cached in memory and silently refreshed 60 seconds before expiry — no manual token management needed.

**Per-tenant cache:** when credentials arrive via request headers, the server maintains a separate `TokenManager` per `(client_id, auth_url)` pair. A single server process can therefore serve multiple CALM tenants simultaneously without credential bleed between requests.

This is OAuth2 Client Credentials flow — the standard for server-to-server authentication.
