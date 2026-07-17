# SAP Cloud ALM — write-API specs needed to verify the MCP write tools

We built create/update tools for 6 entities but **could not read SAP's docs**
(help.sap.com / api.sap.com render their tables with JavaScript, so automated
fetching returns only the page title). Below is exactly what we need scraped for
each API so we can reconcile the request payloads and URLs against reality.

For **every** endpoint below, please capture:

1. **HTTP method** (POST / PATCH / PUT) — is update a PATCH or a full PUT?
2. **Full URL path**, including API version.
3. **Single-entity URL format for update/delete** — is it `.../entity/{id}` or the
   OData form `.../Entity('{id}')` or `.../Entity({id})`? (This differs between the
   plain-JSON APIs and the OData `value`-wrapped ones — critical to get right.)
4. **Request body**: every field name (exact casing), type, and whether required.
5. **Enum / code values** for any coded field (status, type, priority, state…).
6. **Response body** on success (fields + shape), and success status code
   (200/201/204?).
7. **Auth / headers** — any required header beyond `Authorization: Bearer` and
   `Content-Type: application/json` (e.g. CSRF `x-csrf-token` for OData writes?).
8. **Delete** support (method + URL), if we should add delete tools later.

Doc landing page: https://help.sap.com/docs/cloud-alm/apis/  (each API has its own
sub-page; the "API Reference" / "API Specification (EDMX/OpenAPI)" download link on
each page is the ideal artifact — grab that file if available).

---

## 1. Tasks API  — `/api/calm-tasks/v1/tasks`
Doc: Tasks API. (Read returns a bare JSON array — likely NOT OData.)

Need for **create task (POST)** and **update task (PATCH/PUT)**:
- Confirm body field names. We currently send:
  `projectId`, `title`, `type`, `status`, `startDate`, `dueDate`, `assigneeId`,
  `description`, `obsolete`.
- Is assignee `assigneeId`, `assignee`, `assigneeEmail`, or something else?
- Are `startDate`/`dueDate` `YYYY-MM-DD` or full ISO datetime?
- Full list of **`type` codes** (we have CALMTASK, CALMUS, CALMST, CALMREQU,
  CALMDEF, CALMQGATE, CALMCHKLI, CALMTMPL) and **`status` codes per type**
  (CIPTK*, CIPUS*, CIPREQU*, CIPDFCT*, CIPQG*). Confirm these are complete/correct.
- Update URL: `/tasks/{id}` correct?
- Any required fields on create beyond projectId + title + type?

## 2. Projects API — `/api/calm-projects/v1/projects`
Doc: Projects API.

Need for **create (POST)** and **update (PATCH)**:
- Confirm body fields. We send: `name`, `status` (O/C), `purpose`,
  `operationalStatus`.
- Full list of `status` codes (we have O=Active, C=Hidden — any others?) and
  `operationalStatus` allowed values.
- Are there required fields we're missing (e.g. projectType, startDate, endDate,
  language, template)?
- Update URL: `/projects/{id}` correct?

## 3. Process Authoring API — `/api/calm-processauthoring/v1/...`  (OData — read wraps in `value`)
Doc: Business Process / Solution Process API.

### 3a. Business processes — `/businessProcesses`
- Create (POST) + update body fields. We send: `name`, `description`.
- Required fields? Any parent/scope linkage required to create one?
- **Update URL format** (OData): `businessProcesses('{id}')`? PATCH or PUT?
- CSRF token required for writes?

### 3b. Solution processes — `/solutionProcesses`
- Create/update body fields. We send: `name`, `description`, `status`,
  `countries`, `state`.
- Allowed values for `status` and `state`; `countries` shape (array of ISO codes?).
- Required fields? Update URL format? CSRF?

## 4. Process Management API — `/api/calm-processmanagement/v1/scopes`  (OData)
Doc: Scopes / Process Management API.

- Create (POST) + update body fields. We send: `projectId`, `name`, `description`.
- Required fields (is `projectId` required, or is scope created under a project
  path like `/projects/{id}/scopes`?).
- Update URL format: `scopes('{id}')`? PATCH/PUT? CSRF?

## 5. Test Management API — `/api/calm-testmanagement/v1/ManualTestCases`  (OData)
Doc: **Test Cases API** (https://help.sap.com/docs/cloud-alm/apis/test-cases-api)

- Create (POST) + update body fields. We send: `title`, `projectId`, `scopeId`,
  `solutionProcessId`, `priorityCode`, `isPrepared`.
- Is priority `priorityCode` (10/20/30/40) or a different field/name?
- Required fields on create (title only, or also projectId/scopeId)?
- Are there test **steps** / **preconditions** sub-fields we should support?
- Update URL format: `ManualTestCases('{id}')`? PATCH/PUT? CSRF?
- Does the read/response include an `id` we can use for updates? (Our current read
  mapping does NOT expose an id for test cases — we need the id field name.)

---

## Nice-to-have (for future write tools)
- Any other write-capable CALM APIs worth wrapping: **Requirements**, **Defects**,
  **Features/User Stories** (if separate from tasks), **Test Executions/Runs**,
  **Quality Gates**, **Deployments**, **Landscape/Systems**.
- For each: base path, create/update body, id-in-URL format, enums.
