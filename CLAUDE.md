# CALM_MCP

A Python FastMCP server that exposes SAP Cloud ALM (CALM) — Projects/Tasks,
Process Authoring, Test Management, plus an optional BTP Test Management
OData repository — as MCP tools, consolidated around one `calm_resource`
tool. Consumed by Syntax GenAI Studio agents and any other MCP client
(Claude Desktop, MCP Inspector, Cursor). Runs as a local stdio process for
desktop/dev clients, or as a Streamable-HTTP server (`--http`) for remote
deployments; a single instance can serve one tenant via server env vars or
many tenants simultaneously via per-request headers.

## Commands

- Install: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
- Test: `./venv/bin/python -m pytest -q` (unit/integration suite under `tests/`) **and** `./venv/bin/python tests/test_server.py` (e2e — spawns the real server over stdio against a mocked CALM backend). Both must pass before a change is done.
- Lint and type-check: none configured (no ruff/flake8/mypy config or `pyproject.toml` in the repo)
- Run locally: `python3 server.py` (stdio) or `python3 server.py --http --host 0.0.0.0 --port 8000` (HTTP, for Studio); `npx @modelcontextprotocol/inspector python3 server.py` for interactive testing

## Architecture

- `server.py` — entry point. Builds the FastMCP app, adds the TOON-encoding and truncation-alert middleware, initializes the OAuth2 client-credentials token manager from env vars when present, registers the tool modules below, and (in `--http` mode) exposes RFC 9728/8414 OAuth discovery routes.
- `src/calm/tools/unified.py` — the consolidated surface. `calm_resource(resource, operation, project_id, resource_id, task_type, data, user_email)` handles `list`/`get`/`create`/`update`/`delete` across 27 resource types (projects, tasks, requirements, teams, processes/business_processes/solution_processes, timeboxes, scopes, test_cases, test_plans, tags, features, project_users, customization, plus sub-entities: task_relations, task_comments, task_tags, test_actions, test_activities, scope_assignments, scenario_versions, test_case_links, analytics, team_roles, feature_status, feature_priorities), dispatching straight to functions in `src/calm/client.py`. Also registers one shortcut tool, `list_sap_cloud_alm_projects`.
- `src/calm/client.py` — the actual CALM REST/OData wrappers: request building, the status/type/priority code maps (`TASK_STATUS_MAP`, `TASK_TYPE_MAP`, `PROJECT_STATUS_MAP`, `TESTCASE_PRIORITY_MAP`) and their reverse maps for writes, ETag handling, pagination (`_get_all`), and `_api_field_names` (snake_case → camelCase for `extra_fields`).
- `src/calm/http_retry.py` — the single `send()` used by every outbound HTTP call; retries reads and the token POST on transient failures, never retries a write once it may have reached SAP.
- `src/calm/dependencies.py`, `token_manager.py`, `config.py`, `models.py` — credential and tenant-URL resolution, in order: per-request `x-calm-*` headers > server `CALM_CLIENT_ID`/`CALM_CLIENT_SECRET` > `Authorization: Bearer` header > `CALM_TOKEN` env var. `CALM_MULTI_TENANT` makes this fail closed so a shared pod never falls back to the wrong tenant's credential.
- `src/calm/tm_client.py`, `tm_dependencies.py` + `src/calm/tools/test_repo.py`/`test_repo_write.py` — the optional, separate BTP Test Management OData repository (`tm_*` tools): its own credentials/base URL and its own write guard (`TM_ENABLE_WRITES`); reports "not configured" with no TM env vars set.
- `src/calm/toon_middleware.py` — encodes tool text output as TOON by default (token-efficient; `CALM_OUTPUT_FORMAT=json` reverts it) and raises a truncation alert whenever a paged list hits its safety ceiling.
- `src/calm/tools/advanced_write.py` — generic escape hatch (`calm_api_read`/`calm_api_write`/`calm_api_delete`) for any CALM endpoint with no dedicated path through `calm_resource`.
- Start reading at `server.py` → `src/calm/tools/unified.py` → `src/calm/client.py`.

## Conventions

- Response field names in `client.py` (`ID`, `Title`, `Status`, `Type`, `Name`, `Purpose`, and the mapped human labels like "Active"/"In Progress"/"Very High") are a contract with the Syntax GenAI Studio agent's prompts — never rename them without flagging it first.
- `extra_fields` on write calls are converted snake_case → camelCase for CALM's own REST/OData APIs only (`_api_field_names` in `client.py`); the BTP Test Management (`tm_*`) service is passed through as-is — don't apply that conversion there.
- Writes are gated behind `CALM_ENABLE_WRITES` (CALM) and `TM_ENABLE_WRITES` (Test Management repo) independently, both off by default; write tools stay advertised but return a guard error when disabled — new write paths must call `ensure_writes_enabled()`.
- Configuration is entirely env-var driven (tenant identity/region zone or explicit auth/base URL overrides, client credentials or a static token, the write toggles, `CALM_OUTPUT_FORMAT`) — see `.env.example` for the variable names; never hardcode or commit a value for them.
- New features land with their own unit tests plus matching checks added to `tests/test_server.py`; `tests/conftest.py` has an autouse guard that fails any test attempting a real (non-loopback) network connection, so a forgotten mock errors loudly instead of hitting live SAP.

## Gotchas

- Two test commands, not one: plain `pytest` never exercises the real MCP protocol path — only `tests/test_server.py` spawns the actual stdio server and drives `calm_resource` end-to-end, which is what catches an argument-shift regression at the protocol level.
- There is no built-in tenant: with no zone env vars or `x-calm-*` zone headers (or explicit `CALM_BASE_URL`/`CALM_AUTH_URL`), every CALM tool raises `TenantNotConfiguredError` (`src/calm/config.py`) and `calm_health` reports it instead of a URL. `get_calm_oauth_endpoints` derives its endpoints from the server env only, not from per-request headers.
- `If-Match` is required on PATCH/DELETE for the OData services (Process Authoring, Test Management) and for Projects PATCH, but not for Tasks or Scopes. The typed tools in `client.py` auto-fetch the ETag; the `calm_api_write`/`calm_api_delete` escape hatch does not — pass `if_match` yourself there.
- `http_retry.send()` never retries a write once it may have been sent: a dropped connection on a POST raises an error telling you to check whether the item was already created, rather than silently duplicating it.
- Several per-resource tool modules still sit under `src/calm/tools/` (`projects.py`, `tasks_write.py`, `teams.py`, `test_cases.py`, etc.) from before the unified-tool consolidation. `server.py` no longer imports them and `unified.py` doesn't call into them either — they're dead code, not an alternate path to the same resources.
- README.md's install steps reference a `.venv` directory; the repo's actual virtualenv (and the one the test commands above use) is `venv/`.
- The repo pushes to two remotes on `main` — `origin` (GitHub) and `gitlab` — keep them in sync; nothing automates that.
