"""Unified MCP tools for SAP Cloud ALM - Context-optimized resource management.

This module provides consolidated tools that reduce the MCP tool overhead from ~20,000
tokens to ~7,500 tokens, saving 12,500 tokens per agent conversation (15% more context).

Phase 1: Read-only operations (list, get)
Phase 2: Write operations (create, update, delete) - future
Phase 3: Complete migration from legacy tools - future

All existing individual tools remain functional for backwards compatibility.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastmcp import Context, FastMCP

from src.calm import client
from src.calm.dependencies import ensure_writes_enabled, get_calm_headers
from src.calm.tools.user_resolver import resolve_assignee


def _normalize_tag(t: Any) -> str:
    """Normalize a tag to a comparable 'group:tag' key.

    Accepts a "Group: Tag" string (colon spacing is ignored) or a
    {"group": ..., "tag": ...} dict, so "Scope: Baseline", "Scope:Baseline"
    and {"group": "Scope", "tag": "Baseline"} all compare equal.
    """
    if isinstance(t, dict):
        return f"{str(t.get('group', '')).strip()}:{str(t.get('tag', '')).strip()}".lower()
    s = str(t)
    if ":" in s:
        group, _, tag = s.partition(":")
        return f"{group.strip()}:{tag.strip()}".lower()
    return s.strip().lower()


def _validate_task_tags(tags: list, project_id: str, token: str, base_url: str | None) -> None:
    """Reject tags that aren't defined in the project before assigning them.

    CALM *silently drops* tags on a task when they don't exactly match a
    project-configured tag, so a caller never learns the tag didn't stick. We
    read the project's configured tag list and raise a clear, actionable error
    listing the valid tags instead of letting the assignment vanish.
    """
    if not tags:
        return
    configured = client.get_tags(project_id, token, base_url)
    valid_by_norm = {
        _normalize_tag({"group": t.get("Group"), "tag": t.get("Tag")}): t.get("Full Name")
        for t in configured
        if t.get("Group") and t.get("Tag")
    }
    unknown = [t for t in tags if _normalize_tag(t) not in valid_by_norm]
    if unknown:
        valid_names = sorted(v for v in valid_by_norm.values() if v)
        raise ValueError(
            f"These tag(s) are not defined in project {project_id} and CALM would "
            f"silently drop them: {unknown}. "
            f"Valid tags for this project: {valid_names or '(none configured yet)'}. "
            f"Create a missing tag first with resource='tags', operation='create', "
            f"data={{'group': ..., 'tag': ...}}."
        )


def register(mcp: FastMCP) -> None:
    """Register unified MCP tools for context optimization."""

    @mcp.tool()
    def calm_resource(
        ctx: Context,
        resource: Literal[
            "projects",
            "tasks",
            "requirements",
            "teams",
            "processes",
            "business_processes",
            "solution_processes",
            "timeboxes",
            "scopes",
            "test_cases",
            "tags",
            "features",
            "test_plans",
            "project_users",
            "customization",
            "task_relations",
            "task_comments",
            "task_tags",
            "test_actions",
            "test_activities",
            "scope_assignments",
            "scenario_versions",
            "test_case_links",
            "test_plan_assignments",
        ],
        operation: Literal["list", "get", "create", "update", "delete"] = "list",
        project_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        task_type: Optional[str] = None,
        data: Optional[dict] = None,
        user_email: Optional[str] = None,
    ) -> list[dict] | dict:
        """Unified resource management for SAP Cloud ALM.

        Context optimization: This tool consolidates multiple resource-specific tools
        into one interface, reducing token overhead and improving agent efficiency.

        Args:
            resource: The CALM resource type to access.
            operation: The operation to perform (list, get, create, update, delete).
            project_id: Required for project-scoped resources (tasks, teams, timeboxes, etc).
            resource_id: Required for "get", "update", "delete" operations - the specific resource ID.
            task_type: Optional filter for tasks operation (e.g., "Requirement", "User Story").
            data: Required for "create" and "update" operations - the resource data.
                Keys are snake_case and match the original per-resource tools:
                - projects: name, program_id, deployment_plan_id, extra_fields, if_match
                - tasks: title, task_type, status, start_date, due_date, assignee_id
                    (email/name/UUID — auto-resolved), description, priority_id,
                    external_id, parent_id, obsolete, extra_fields
                - requirements: title, status, description, assignee_id, start_date,
                    due_date, priority_id, sub_status, obsolete, extra_fields
                - business_processes: name, description, if_match
                - solution_processes: name, description, status, countries, state,
                    business_process_id, external_id, if_match
                - timeboxes: name, timebox_type, start_date, end_date, closed, extra_fields
                - scopes: name, description, if_match
                - test_cases: title, scope_id (required), project_id, solution_process_id,
                    priority, is_prepared, activities, references, force, if_match
                - tags: group, tag (both required; project_id from the param)
                - features: name (required), description, external_id, extra_fields
                - test_plans: name (required), description, extra_fields
                # --- sub-entity / relationship resources (create/update/delete) ---
                - task_relations: create → resource_id=parent task_id,
                    data={relation_task_id (required), relation_type (default "0")};
                    delete → resource_id=relation_id
                - task_comments: create → resource_id=task_id, data={text, extra_fields};
                    update → resource_id=comment_id, data={text, extra_fields};
                    delete → resource_id=comment_id
                - task_tags: update (set/replace a task's tags) → resource_id=task_id,
                    data={tags: ["Group: Tag", ...]}. Pass project_id to validate the
                    tags against the project's configured list (recommended — CALM
                    silently drops tags that aren't defined; validation turns that
                    into a clear error). data={skip_validation: True} bypasses the check.
                - test_actions: create → resource_id=activity_id,
                    data={title (required), description, expected_result, sequence,
                    is_evidence_required}; update → resource_id=action_id,
                    data={..., if_match}; delete → resource_id=action_id, data={if_match}
                - test_activities: update → resource_id=activity_id,
                    data={title, sequence, is_in_scope, if_match};
                    delete → resource_id=activity_id, data={if_match}
                - scope_assignments: update → data={assignments: [{scopeId,
                    solutionScenarioVersionId, solutionProcessVersionId, isScoped,
                    statusId?}, ...]} (scope/unscope solution processes)
                - scenario_versions: create (assign versions to a scope) →
                    resource_id=scope_id, data={version_ids: [...]}
                - test_case_links: create (link test case → requirement) →
                    resource_id=test_case_id, data={requirement_id (required), link_type}
                - test_plan_assignments: create (assign test case → plan) →
                    resource_id=test_plan_id, data={test_case_id (required),
                    tester_email, extra_fields}
            user_email: Optional for write operations - acting user's email for audit logs.

        Returns:
            List of resources for "list", single resource dict for "get"/"create"/"update"/"delete".

        Examples:
            # List all projects
            calm_resource(resource="projects", operation="list")

            # List tasks for a project
            calm_resource(resource="tasks", operation="list", project_id="P001")

            # Get requirements (tasks with type filter)
            calm_resource(resource="requirements", operation="list", project_id="P001")

            # List teams (all or project-specific)
            calm_resource(resource="teams", operation="list")
            calm_resource(resource="teams", operation="list", project_id="P001")

            # List timeboxes for a project
            calm_resource(resource="timeboxes", operation="list", project_id="P001")

            # List all scopes
            calm_resource(resource="scopes", operation="list")

            # List test cases
            calm_resource(resource="test_cases", operation="list")

            # List business processes
            calm_resource(resource="business_processes", operation="list")

            # List solution processes
            calm_resource(resource="solution_processes", operation="list")

            # List project-specific resources
            calm_resource(resource="tags", operation="list", project_id="P001")
            calm_resource(resource="features", operation="list", project_id="P001")
            calm_resource(resource="test_plans", operation="list", project_id="P001")
            calm_resource(resource="project_users", operation="list", project_id="P001")

            # Get project customization
            calm_resource(resource="customization", operation="get", project_id="P001")

            # Phase 2: Write operations
            # Create a new task
            calm_resource(
                resource="tasks",
                operation="create",
                project_id="P001",
                data={"title": "New task", "task_type": "User Story", "description": "..."},
                user_email="user@example.com"
            )

            # Update an existing task
            calm_resource(
                resource="tasks",
                operation="update",
                project_id="P001",
                resource_id="3-12345",
                data={"status": "In Progress"},
                user_email="user@example.com"
            )

            # Delete a task
            calm_resource(
                resource="tasks",
                operation="delete",
                project_id="P001",
                resource_id="3-12345",
                user_email="user@example.com"
            )

            # Create a scope
            calm_resource(
                resource="scopes",
                operation="create",
                data={"name": "New Scope", "description": "..."},
                user_email="user@example.com"
            )

        Resource Mappings (for reference):
            - projects → get_calm_projects()
            - tasks → get_calm_tasks(project_id, task_type?)
            - requirements → get_calm_requirements(project_id) [tasks with type="Requirement"]
            - teams → get_calm_teams(project_id?)
            - processes → get_calm_processes() [combined business + solution]
            - business_processes → get_calm_business_processes()
            - solution_processes → get_calm_solution_processes()
            - timeboxes → get_calm_timeboxes(project_id)
            - scopes → get_calm_scopes()
            - test_cases → get_calm_test_cases()
            - tags → get_calm_tags(project_id)
            - features → get_calm_features(project_id)
            - test_plans → get_calm_test_plans(project_id)
            - project_users → get_calm_project_users(project_id)
            - customization → get_calm_project_customization(project_id)

        Note: All legacy individual tools remain functional for backwards compatibility.
        This unified tool is provided for improved context efficiency.
        """
        h = get_calm_headers(ctx)
        d = data or {}
        # Prefer an explicitly-passed acting user, else the header-derived email.
        acting_email = user_email or h.user_email

        # Route to appropriate client function based on resource type
        if resource == "projects":
            if operation == "list":
                return client.get_projects(h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                if not d.get("name"):
                    raise ValueError("data must include 'name' for create operation")
                return client.create_project(
                    token=h.token,
                    name=d.get("name"),
                    program_id=d.get("program_id"),
                    deployment_plan_id=d.get("deployment_plan_id"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_project(
                    token=h.token,
                    project_id=resource_id,
                    name=d.get("name"),
                    program_id=d.get("program_id"),
                    deployment_plan_id=d.get("deployment_plan_id"),
                    if_match=d.get("if_match"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                raise ValueError("Delete operation not supported for projects")
            elif operation == "get":
                raise ValueError("Use operation='list' to get all projects, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for projects")

        elif resource == "tasks":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for tasks")
                return client.get_tasks(project_id, h.token, h.base_url, task_type=task_type)
            elif operation == "create":
                ensure_writes_enabled()
                if not project_id:
                    raise ValueError("project_id is required for tasks")
                if not d.get("title"):
                    raise ValueError("data must include 'title' for create operation")
                if not d.get("task_type"):
                    raise ValueError("data must include 'task_type' for create operation")
                # Smart assignee resolution (email/name/UUID -> assignable ID).
                assignee = d.get("assignee_id")
                if assignee:
                    assignee = resolve_assignee(
                        user_identifier=assignee,
                        project_id=project_id,
                        token=h.token,
                        base_url=h.base_url,
                    )
                return client.create_task(
                    token=h.token,
                    project_id=project_id,
                    title=d.get("title"),
                    task_type=d.get("task_type"),
                    status=d.get("status"),
                    start_date=d.get("start_date"),
                    due_date=d.get("due_date"),
                    assignee_id=assignee,
                    description=d.get("description"),
                    priority_id=d.get("priority_id"),
                    external_id=d.get("external_id"),
                    parent_id=d.get("parent_id"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                # Smart assignee resolution — needs the task's project to look up users.
                assignee = d.get("assignee_id")
                if assignee:
                    proj_id = project_id or (d.get("extra_fields") or {}).get("projectId")
                    if not proj_id:
                        try:
                            task_data = client._get(
                                f"{client._base_url(h.base_url)}/api/calm-tasks/v1/tasks/{resource_id}",
                                h.token,
                            )
                            proj_id = task_data.get("projectId")
                        except Exception:
                            pass  # fall back to the raw identifier
                    if proj_id:
                        assignee = resolve_assignee(
                            user_identifier=assignee,
                            project_id=proj_id,
                            token=h.token,
                            base_url=h.base_url,
                        )
                return client.update_task(
                    token=h.token,
                    task_id=resource_id,
                    title=d.get("title"),
                    task_type=d.get("task_type"),
                    status=d.get("status"),
                    start_date=d.get("start_date"),
                    due_date=d.get("due_date"),
                    assignee_id=assignee,
                    description=d.get("description"),
                    priority_id=d.get("priority_id"),
                    external_id=d.get("external_id"),
                    obsolete=d.get("obsolete"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_task(
                    token=h.token, task_id=resource_id, base_url=h.base_url, user_email=acting_email
                )
            elif operation == "get":
                raise ValueError("Use operation='list' with project_id and optionally filter by task_type")
            else:
                raise ValueError(f"Unknown operation '{operation}' for tasks")

        elif resource == "requirements":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for requirements")
                # Requirements are tasks with type="Requirement"
                return client.get_tasks(project_id, h.token, h.base_url, task_type="Requirement")
            elif operation == "create":
                ensure_writes_enabled()
                if not project_id:
                    raise ValueError("project_id is required for requirements")
                if not d.get("title"):
                    raise ValueError("data must include 'title' for create operation")
                # sub_status is folded into extra_fields as subStatus (as the old tool did).
                extra = dict(d.get("extra_fields") or {})
                if d.get("sub_status") is not None:
                    extra["subStatus"] = d.get("sub_status")
                return client.create_task(
                    token=h.token,
                    project_id=project_id,
                    title=d.get("title"),
                    task_type="Requirement",
                    status=d.get("status"),
                    start_date=d.get("start_date"),
                    due_date=d.get("due_date"),
                    assignee_id=d.get("assignee_id"),
                    description=d.get("description"),
                    priority_id=d.get("priority_id"),
                    extra_fields=extra or None,
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                extra = dict(d.get("extra_fields") or {})
                if d.get("sub_status") is not None:
                    extra["subStatus"] = d.get("sub_status")
                return client.update_task(
                    token=h.token,
                    task_id=resource_id,
                    task_type="Requirement",
                    title=d.get("title"),
                    status=d.get("status"),
                    start_date=d.get("start_date"),
                    due_date=d.get("due_date"),
                    assignee_id=d.get("assignee_id"),
                    description=d.get("description"),
                    priority_id=d.get("priority_id"),
                    obsolete=d.get("obsolete"),
                    extra_fields=extra or None,
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_task(
                    token=h.token, task_id=resource_id, base_url=h.base_url, user_email=acting_email
                )
            elif operation == "get":
                raise ValueError("Use operation='list' with project_id to get requirements, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for requirements")

        elif resource == "teams":
            if operation == "list":
                if project_id:
                    return client.get_project_teams(project_id, h.token, h.base_url)
                return client.get_teams(h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for teams in Phase 1")

        elif resource == "processes":
            if operation == "list":
                # Combined business and solution processes
                business = client.get_business_processes(h.token, h.base_url)
                solution = client.get_solution_processes(h.token, h.base_url)
                return business + solution
            else:
                raise ValueError(
                    "For write operations on processes, use 'business_processes' or 'solution_processes' "
                    "to specify which type. Use 'processes' only for read operations that return both types."
                )

        elif resource == "business_processes":
            if operation == "list":
                return client.get_business_processes(h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                if not d.get("name"):
                    raise ValueError("data must include 'name' for create operation")
                return client.create_business_process(
                    token=h.token,
                    name=d.get("name"),
                    description=d.get("description"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_business_process(
                    token=h.token,
                    business_process_id=resource_id,
                    name=d.get("name"),
                    description=d.get("description"),
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_business_process(
                    token=h.token,
                    business_process_id=resource_id,
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "get":
                raise ValueError("Use operation='list' to get all business_processes, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for business_processes")

        elif resource == "solution_processes":
            if operation == "list":
                return client.get_solution_processes(h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                if not d.get("name"):
                    raise ValueError("data must include 'name' for create operation")
                return client.create_solution_process(
                    token=h.token,
                    name=d.get("name"),
                    description=d.get("description"),
                    status=d.get("status"),
                    countries=d.get("countries"),
                    state=d.get("state"),
                    business_process_id=d.get("business_process_id"),
                    external_id=d.get("external_id"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_solution_process(
                    token=h.token,
                    solution_process_id=resource_id,
                    name=d.get("name"),
                    description=d.get("description"),
                    status=d.get("status"),
                    countries=d.get("countries"),
                    state=d.get("state"),
                    external_id=d.get("external_id"),
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_solution_process(
                    token=h.token,
                    solution_process_id=resource_id,
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "get":
                raise ValueError("Use operation='list' to get all solution_processes, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for solution_processes")

        elif resource == "timeboxes":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for timeboxes")
                return client.get_timeboxes(project_id, h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                if not project_id:
                    raise ValueError("project_id is required for timeboxes")
                return client.create_timebox(
                    token=h.token,
                    project_id=project_id,
                    name=d.get("name"),
                    timebox_type=d.get("timebox_type"),
                    start_date=d.get("start_date"),
                    end_date=d.get("end_date"),
                    closed=d.get("closed"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_timebox(
                    token=h.token,
                    timebox_id=resource_id,
                    name=d.get("name"),
                    start_date=d.get("start_date"),
                    end_date=d.get("end_date"),
                    closed=d.get("closed"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_timebox(
                    token=h.token, timebox_id=resource_id, base_url=h.base_url, user_email=acting_email
                )
            elif operation == "get":
                raise ValueError("Use operation='list' with project_id to get timeboxes, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for timeboxes")

        elif resource == "scopes":
            if operation == "list":
                # The scopes endpoint is tenant-wide; when a project_id is given,
                # filter to that project (each record carries "Project ID") so the
                # param is honored. Without one, return all scopes (unchanged).
                scopes = client.get_scopes(h.token, h.base_url)
                if project_id:
                    scopes = [s for s in scopes if s.get("Project ID") == project_id]
                return scopes
            elif operation == "create":
                ensure_writes_enabled()
                if not project_id:
                    raise ValueError("project_id is required for scopes")
                if not d.get("name"):
                    raise ValueError("data must include 'name' for create operation")
                return client.create_scope(
                    token=h.token,
                    project_id=project_id,
                    name=d.get("name"),
                    description=d.get("description"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_scope(
                    token=h.token,
                    scope_id=resource_id,
                    name=d.get("name"),
                    description=d.get("description"),
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_scope(
                    token=h.token,
                    scope_id=resource_id,
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "get":
                raise ValueError("Use operation='list' to get all scopes, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for scopes")

        elif resource == "test_cases":
            if operation == "list":
                return client.get_test_cases(h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                tc_project_id = project_id or d.get("project_id")
                tc_scope_id = d.get("scope_id")
                if not d.get("title"):
                    raise ValueError("data must include 'title' for create operation")
                if not tc_project_id:
                    raise ValueError("project_id is required for test_cases (pass project_id or data['project_id'])")
                if not tc_scope_id:
                    raise ValueError("data must include 'scope_id' (the API rejects a test case without one)")
                return client.create_test_case(
                    token=h.token,
                    title=d.get("title"),
                    project_id=tc_project_id,
                    scope_id=tc_scope_id,
                    solution_process_id=d.get("solution_process_id"),
                    priority=d.get("priority"),
                    is_prepared=d.get("is_prepared"),
                    activities=d.get("activities"),
                    references=d.get("references"),
                    solution_process_flow_id=d.get("solution_process_flow_id"),
                    solution_process_flow_diagram_id=d.get("solution_process_flow_diagram_id"),
                    content_package_id=d.get("content_package_id"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_test_case(
                    token=h.token,
                    test_case_id=resource_id,
                    title=d.get("title"),
                    scope_id=d.get("scope_id"),
                    solution_process_id=d.get("solution_process_id"),
                    priority=d.get("priority"),
                    is_prepared=d.get("is_prepared"),
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_test_case(
                    token=h.token,
                    test_case_id=resource_id,
                    force=bool(d.get("force", False)),
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "get":
                raise ValueError("Use operation='list' to get all test_cases, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for test_cases")

        elif resource == "tags":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for tags")
                return client.get_tags(project_id, h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                if not project_id:
                    raise ValueError("project_id is required for tags")
                group, tag = d.get("group"), d.get("tag")
                if not group or not tag:
                    raise ValueError("data must include 'group' and 'tag'")
                return client.create_tag(
                    token=h.token,
                    project_id=project_id,
                    group=group,
                    tag=tag,
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation in ["update", "delete"]:
                raise ValueError(f"Operation '{operation}' not supported for tags (read-only after creation)")
            elif operation == "get":
                raise ValueError("Use operation='list' with project_id to get tags, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for tags")

        elif resource == "features":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for features")
                return client.get_features(project_id, h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                f_project_id = project_id or d.get("project_id")
                if not f_project_id:
                    raise ValueError("project_id is required for features (pass project_id or data['project_id'])")
                if not d.get("name"):
                    raise ValueError("data must include 'name' for create operation")
                return client.create_feature(
                    token=h.token,
                    project_id=f_project_id,
                    name=d.get("name"),
                    description=d.get("description"),
                    external_id=d.get("external_id"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation in ["update", "delete"]:
                raise ValueError(f"Operation '{operation}' not supported for features (read-only after creation)")
            elif operation == "get":
                raise ValueError("Use operation='list' with project_id to get features, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for features")

        elif resource == "test_plans":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for test_plans")
                return client.get_test_plans(project_id, h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                tp_project_id = project_id or d.get("project_id")
                if not tp_project_id:
                    raise ValueError("project_id is required for test_plans (pass project_id or data['project_id'])")
                if not d.get("name"):
                    raise ValueError("data must include 'name' for create operation")
                return client.create_test_plan(
                    token=h.token,
                    project_id=tp_project_id,
                    name=d.get("name"),
                    description=d.get("description"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation in ["update", "delete"]:
                raise ValueError(f"Operation '{operation}' not supported for test_plans (read-only after creation)")
            elif operation == "get":
                raise ValueError("Use operation='list' with project_id to get test_plans, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for test_plans")

        elif resource == "project_users":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for project_users")
                return client.get_project_users(project_id, h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for project_users in Phase 1")

        elif resource == "customization":
            if operation == "get":
                if not project_id:
                    raise ValueError("project_id is required for customization")
                return client.get_project_customization(project_id, h.token, h.base_url)
            elif operation == "list":
                raise ValueError("Use operation='get' for customization (returns single project config)")
            else:
                raise ValueError(f"Operation '{operation}' not supported for customization in Phase 1")

        # ------------------------------------------------------------------ #
        # Sub-entity / relationship resources (folded back in for full parity
        # with the original 75-tool surface — each maps to a client function).
        # ------------------------------------------------------------------ #
        elif resource == "task_relations":
            if operation == "create":
                ensure_writes_enabled()
                task_id = resource_id or d.get("task_id")
                if not task_id:
                    raise ValueError("resource_id (parent task_id) is required to create a task relation")
                relation_task_id = d.get("relation_task_id")
                if not relation_task_id:
                    raise ValueError("data must include 'relation_task_id'")
                return client.create_task_relation(
                    token=h.token,
                    task_id=task_id,
                    relation_task_id=relation_task_id,
                    relation_type=str(d.get("relation_type", "0")),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id (relation_id) is required to delete a task relation")
                return client.delete_task_relation(
                    token=h.token, relation_id=resource_id, base_url=h.base_url, user_email=acting_email
                )
            else:
                raise ValueError(f"Operation '{operation}' not supported for task_relations (use create/delete)")

        elif resource == "task_comments":
            if operation == "create":
                ensure_writes_enabled()
                task_id = resource_id or d.get("task_id")
                if not task_id:
                    raise ValueError("resource_id (task_id) is required to create a task comment")
                return client.create_task_comment(
                    token=h.token,
                    task_id=task_id,
                    text=d.get("text"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id (comment_id) is required to update a task comment")
                return client.update_task_comment(
                    token=h.token,
                    comment_id=resource_id,
                    text=d.get("text"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id (comment_id) is required to delete a task comment")
                return client.delete_task_comment(
                    token=h.token, comment_id=resource_id, base_url=h.base_url, user_email=acting_email
                )
            else:
                raise ValueError(f"Operation '{operation}' not supported for task_comments (use create/update/delete)")

        elif resource == "task_tags":
            # Setting a task's tags is a replace operation; accept create or update.
            if operation in ("update", "create"):
                ensure_writes_enabled()
                task_id = resource_id or d.get("task_id")
                if not task_id:
                    raise ValueError("resource_id (task_id) is required to set task tags")
                tags = d.get("tags")
                if tags is None:
                    raise ValueError("data must include 'tags' (a list like ['Group: Tag', ...])")
                # Validate against the project's configured tags so unknown tags
                # raise a clear error instead of being silently dropped by CALM.
                # Pass project_id to enable validation (skip only if caller opts
                # out with data={'skip_validation': True}).
                if project_id and not d.get("skip_validation"):
                    _validate_task_tags(tags, project_id, h.token, h.base_url)
                return client.set_task_tags(
                    token=h.token, task_id=task_id, tags=tags, base_url=h.base_url, user_email=acting_email
                )
            else:
                raise ValueError(f"Operation '{operation}' not supported for task_tags (use update to set tags)")

        elif resource == "test_actions":
            if operation == "create":
                ensure_writes_enabled()
                activity_id = resource_id or d.get("activity_id")
                if not activity_id:
                    raise ValueError("resource_id (activity_id) is required to create a test action")
                if not d.get("title"):
                    raise ValueError("data must include 'title' for create operation")
                return client.create_test_action(
                    token=h.token,
                    activity_id=activity_id,
                    title=d.get("title"),
                    description=d.get("description"),
                    expected_result=d.get("expected_result"),
                    sequence=d.get("sequence"),
                    is_evidence_required=d.get("is_evidence_required"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id (action_id) is required to update a test action")
                return client.update_test_action(
                    token=h.token,
                    action_id=resource_id,
                    title=d.get("title"),
                    description=d.get("description"),
                    expected_result=d.get("expected_result"),
                    sequence=d.get("sequence"),
                    is_evidence_required=d.get("is_evidence_required"),
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id (action_id) is required to delete a test action")
                return client.delete_test_action(
                    token=h.token,
                    action_id=resource_id,
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            else:
                raise ValueError(f"Operation '{operation}' not supported for test_actions (use create/update/delete)")

        elif resource == "test_activities":
            if operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id (activity_id) is required to update a test activity")
                return client.update_test_activity(
                    token=h.token,
                    activity_id=resource_id,
                    title=d.get("title"),
                    sequence=d.get("sequence"),
                    is_in_scope=d.get("is_in_scope"),
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id (activity_id) is required to delete a test activity")
                return client.delete_test_activity(
                    token=h.token,
                    activity_id=resource_id,
                    if_match=d.get("if_match"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            else:
                raise ValueError(f"Operation '{operation}' not supported for test_activities (use update/delete)")

        elif resource == "scope_assignments":
            if operation == "update":
                ensure_writes_enabled()
                assignments = d.get("assignments")
                if not assignments:
                    raise ValueError("data must include 'assignments' (a non-empty list)")
                return client.update_scope_assignments(
                    token=h.token, assignments=assignments, base_url=h.base_url, user_email=acting_email
                )
            else:
                raise ValueError(f"Operation '{operation}' not supported for scope_assignments (use update)")

        elif resource == "scenario_versions":
            # Assigning solution-scenario versions to a scope.
            if operation in ("create", "update"):
                ensure_writes_enabled()
                scope_id = resource_id or d.get("scope_id")
                if not scope_id:
                    raise ValueError("resource_id (scope_id) is required to assign scenario versions")
                version_ids = d.get("version_ids")
                if not version_ids:
                    raise ValueError("data must include 'version_ids' (a non-empty list)")
                return client.assign_scenario_versions(
                    token=h.token,
                    scope_id=scope_id,
                    version_ids=version_ids,
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            else:
                raise ValueError(f"Operation '{operation}' not supported for scenario_versions (use create)")

        elif resource == "test_case_links":
            # Linking a test case to a requirement for traceability.
            if operation == "create":
                ensure_writes_enabled()
                test_case_id = resource_id or d.get("test_case_id")
                if not test_case_id:
                    raise ValueError("resource_id (test_case_id) is required to link a test case")
                requirement_id = d.get("requirement_id")
                if not requirement_id:
                    raise ValueError("data must include 'requirement_id'")
                return client.link_test_case_to_requirement(
                    token=h.token,
                    test_case_id=test_case_id,
                    requirement_id=requirement_id,
                    link_type=d.get("link_type", "covers"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            else:
                raise ValueError(f"Operation '{operation}' not supported for test_case_links (use create)")

        elif resource == "test_plan_assignments":
            # Assigning a test case to a test plan.
            if operation == "create":
                ensure_writes_enabled()
                test_plan_id = resource_id or d.get("test_plan_id")
                if not test_plan_id:
                    raise ValueError("resource_id (test_plan_id) is required to assign a test case to a plan")
                test_case_id = d.get("test_case_id")
                if not test_case_id:
                    raise ValueError("data must include 'test_case_id'")
                return client.assign_test_case_to_plan(
                    token=h.token,
                    test_plan_id=test_plan_id,
                    test_case_id=test_case_id,
                    tester_email=d.get("tester_email"),
                    extra_fields=d.get("extra_fields"),
                    base_url=h.base_url,
                    user_email=acting_email,
                )
            else:
                raise ValueError(f"Operation '{operation}' not supported for test_plan_assignments (use create)")

        else:
            raise ValueError(f"Unknown resource type: {resource}")
