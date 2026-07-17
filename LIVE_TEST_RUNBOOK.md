# Live-tenant smoke test — CALM write tools

The mock test suite (`python3 tests/test_server.py`, 32 blocks) proves the plumbing:
URLs, If-Match/ETag flow, label↔code mapping, deep insert, and the write guard. It
does **not** hit SAP. This run-book is for confirming the real payloads against a
tenant. Do it on a **throwaway/sandbox project**, not production data.

## 1. Configure credentials + enable writes

Set these (e.g. in `.env` or the shell). Client-credentials is easiest:

```
CALM_CLIENT_ID=<oauth client id>
CALM_CLIENT_SECRET=<oauth client secret>
IDENTITY_ZONE=<your-btp-identity-zone>      # or CALM_AUTH_URL / CALM_BASE_URL
REGION_ZONE=<your-btp-region-zone>
CALM_ENABLE_WRITES=true                      # <-- required, else writes error out
```

Needed OAuth scopes for a full run: `calm-api.tasks.write`,
`calm-api.projects.write`, `calm-api.processauthoring.write`,
`calm-api.processmanagement.write`, `calm-api.testcases.write`
(+ `.delete` / `.force-delete` to exercise deletes).

## 2. Start the server

```
python server.py --http --port 8000        # HTTP, for Studio / Inspector
# or: python server.py                       # stdio, for MCP Inspector / Claude Desktop
```

Sanity check first — this makes NO write and reports the guard state:

```
calm_health   ->  expect  "writes_enabled": true   and a resolved base_url
```

## 3. Suggested smoke sequence (least → most destructive)

Tasks are the simplest (plain REST, no If-Match) — start there.

1. `get_calm_projects` → pick a **sandbox** project ID `P`.
2. `create_calm_task` → `{project_id: P, title: "smoke test", task_type: "Project Task", status: "Open"}`
   - Expect the created task back with `ID`, `Status: "Open"`. Note its `ID` = `T`.
3. `update_calm_task` → `{task_id: T, status: "In Progress", task_type: "Project Task"}`
   - Expect `Status: "In Progress"`.
4. `get_calm_tasks` → `{project_id: P}` → confirm `T` shows the new status.
5. `delete_calm_task` → `{task_id: T}` (or leave it; it's a sandbox).

Then, if you want to cover the OData services + If-Match:

6. `create_calm_business_process` → `{name: "smoke BP"}` → note `ID`.
7. `update_calm_business_process` → `{business_process_id: <id>, name: "smoke BP 2"}`
   - This auto-fetches the ETag then PATCHes. If it 428/412s, the ETag flow needs a look.
8. `delete_calm_business_process` → `{business_process_id: <id>}`.
9. `create_calm_test_case` → `{title: "smoke TC", project_id: P, priority: "High"}` → note `uuid`.
10. `update_calm_test_case` → `{test_case_id: <uuid>, title: "smoke TC 2"}` (ETag = modifiedAt, auto).

## 4. What to send back if something fails

For any tool that errors, copy me:
- the **tool name + arguments** you called,
- the **error text** the tool returned, and (if visible) the **HTTP status**
  (400 = payload/field issue, 403 = missing scope, 404 = bad id/path,
  412/428 = ETag/If-Match issue).

That's enough for me to pinpoint and fix the payload. Most likely fix areas if
the specs and reality differ: an exact field name, a code value, or an ETag source.

## 5. Notes

- Writes are **disabled** unless `CALM_ENABLE_WRITES=true`; without it every write
  tool returns a clear error and nothing hits the tenant.
- The generic `calm_api_write` / `calm_api_delete` tools do not auto-fetch ETags —
  pass `if_match` yourself for OData / Projects PATCH.
- No project DELETE exists in the API, so there is no `delete_calm_project` tool.
