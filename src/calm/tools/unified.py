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
                data={"title": "New task", "type": "User Story", "description": "..."},
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

        # Route to appropriate client function based on resource type
        if resource == "projects":
            if operation == "list":
                return client.get_projects(h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_project(data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_project(resource_id, data, h.token, h.base_url, h.user_email or user_email)
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
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_task(project_id, data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "update":
                ensure_writes_enabled()
                if not project_id:
                    raise ValueError("project_id is required for tasks")
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_task(project_id, resource_id, data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_task(h.token, resource_id, h.base_url, h.user_email or user_email)
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
                if not data:
                    raise ValueError("data is required for create operation")
                # Ensure type is set to Requirement
                data_with_type = {**data, "type": "Requirement"}
                return client.create_task(project_id, data_with_type, h.token, h.base_url, h.user_email or user_email)
            elif operation == "update":
                ensure_writes_enabled()
                if not project_id:
                    raise ValueError("project_id is required for requirements")
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_task(project_id, resource_id, data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_task(h.token, resource_id, h.base_url, h.user_email or user_email)
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
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_business_process(data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_business_process(resource_id, data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_business_process(h.token, resource_id, h.base_url, h.user_email or user_email)
            elif operation == "get":
                raise ValueError("Use operation='list' to get all business_processes, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for business_processes")

        elif resource == "solution_processes":
            if operation == "list":
                return client.get_solution_processes(h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_solution_process(data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_solution_process(resource_id, data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_solution_process(h.token, resource_id, h.base_url, h.user_email or user_email)
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
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_timebox(data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_timebox(resource_id, data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_timebox(h.token, resource_id, h.base_url, h.user_email or user_email)
            elif operation == "get":
                raise ValueError("Use operation='list' with project_id to get timeboxes, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for timeboxes")

        elif resource == "scopes":
            if operation == "list":
                return client.get_scopes(h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_scope(data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_scope(resource_id, data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_scope(h.token, resource_id, h.base_url, h.user_email or user_email)
            elif operation == "get":
                raise ValueError("Use operation='list' to get all scopes, then filter by ID")
            else:
                raise ValueError(f"Unknown operation '{operation}' for scopes")

        elif resource == "test_cases":
            if operation == "list":
                return client.get_test_cases(h.token, h.base_url)
            elif operation == "create":
                ensure_writes_enabled()
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_test_case(data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "update":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for update operation")
                if not data:
                    raise ValueError("data is required for update operation")
                return client.update_test_case(resource_id, data, h.token, h.base_url, h.user_email or user_email)
            elif operation == "delete":
                ensure_writes_enabled()
                if not resource_id:
                    raise ValueError("resource_id is required for delete operation")
                return client.delete_test_case(h.token, resource_id, h.base_url, h.user_email or user_email)
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
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_tag(data, h.token, h.base_url, h.user_email or user_email)
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
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_feature(data, h.token, h.base_url, h.user_email or user_email)
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
                if not data:
                    raise ValueError("data is required for create operation")
                return client.create_test_plan(data, h.token, h.base_url, h.user_email or user_email)
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

        else:
            raise ValueError(f"Unknown resource type: {resource}")
