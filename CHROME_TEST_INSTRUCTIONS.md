# Testing the CALM MCP server from Chrome (MCP Inspector)

The server is running locally in HTTP mode with writes enabled:

- **Endpoint:** `http://127.0.0.1:8000/mcp`  (Streamable HTTP)
- **Writes:** enabled (`CALM_ENABLE_WRITES=true`)
- **Auth:** none baked in — you supply CALM credentials as HTTP headers per session
  (see step 3). Until you do, tools return a clear "Missing CALM token" error and
  `calm_health` shows `"token_configured": false`.

> Only reachable on the machine that started it (`127.0.0.1`). If the tester is on
> another machine, expose it (restart with `MCP_HOST=0.0.0.0` and tunnel/port-forward),
> or run the server on their machine.

## 1. Open the MCP Inspector in Chrome

The Inspector is the official browser UI for poking an MCP server. In a terminal:

```
npx @modelcontextprotocol/inspector
```

It prints a URL (e.g. `http://localhost:6274`) and opens Chrome. (Node.js required.)

## 2. Connect to the server

In the Inspector's left panel:

- **Transport Type:** `Streamable HTTP`
- **URL:** `http://127.0.0.1:8000/mcp`
- Click **Connect**.

Then click **List Tools** — you should see the read tools, the write/delete tools,
the sub-entity tools, and the two generic `calm_api_*` tools.

## 3. Provide CALM credentials (HTTP headers)

Open **Authentication / Header Configuration** in the Inspector and add ONE of:

**Option A — client credentials (recommended):**

| Header | Value |
|--------|-------|
| `x-calm-client-id` | `<your OAuth client id>` |
| `x-calm-client-secret` | `<your OAuth client secret>` |
| `x-calm-identity-zone` | `<your BTP identity zone>` |
| `x-calm-region-zone` | `<your BTP region zone, e.g. eu10>` |

(or instead of the two zone headers: `x-calm-auth-url` + `x-calm-base-url` with the full URLs.)

**Option B — bearer token:**

| Header | Value |
|--------|-------|
| `Authorization` | `Bearer <your CALM token>` |
| `x-calm-base-url` | `https://<tenant>.<region>.alm.cloud.sap` |

Reconnect after setting headers.

## 4. Sanity check

Run the **`calm_health`** tool (no args). Expect:
`"writes_enabled": true`, `"token_configured": true`, and the correct `base_url`.

## 5. Run the smoke sequence

Follow **LIVE_TEST_RUNBOOK.md** in this repo — least-to-most-destructive, on a
**sandbox project**:

1. `get_calm_projects` → pick a sandbox project ID `P`.
2. `create_calm_task` → `{project_id:P, title:"smoke test", task_type:"Project Task", status:"Open"}` → note `ID` = `T`.
3. `update_calm_task` → `{task_id:T, status:"In Progress", task_type:"Project Task"}`.
4. `get_calm_tasks` → `{project_id:P}` → confirm the change.
5. `delete_calm_task` → `{task_id:T}`.
6. (OData + If-Match) `create_calm_business_process` → `update_...` → `delete_...`.
7. (Test mgmt) `create_calm_test_case` → `update_calm_test_case`.

## 6. If a tool errors, capture this

- tool name + arguments used,
- the error text returned,
- HTTP status if shown: **400** payload/field, **403** missing scope, **404** bad id/path, **412/428** ETag/If-Match.

Send those back and the payload can be corrected quickly.

## Stopping / restarting the server

- **Stop:** `kill 27762`  (or `pkill -f "server.py --http"`).
- **Restart:** from the repo dir:
  `CALM_ENABLE_WRITES=true python3 server.py --http --port 8000`
- **Local dev without headers:** set `CALM_TOKEN=<token>` (and `CALM_BASE_URL`) in the
  environment before starting, then no per-request headers are needed.
