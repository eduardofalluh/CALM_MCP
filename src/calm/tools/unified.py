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
from src.calm.dependencies import get_calm_headers


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
        operation: Literal["list", "get"] = "list",
        project_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        task_type: Optional[str] = None,
    ) -> list[dict] | dict:
        """Unified resource management for SAP Cloud ALM.

        Context optimization: This tool consolidates multiple resource-specific tools
        into one interface, reducing token overhead and improving agent efficiency.

        Args:
            resource: The CALM resource type to access.
            operation: The operation to perform (list or get).
            project_id: Required for project-scoped resources (tasks, teams, timeboxes, etc).
            resource_id: Required for "get" operation - the specific resource ID.
            task_type: Optional filter for tasks operation (e.g., "Requirement", "User Story").

        Returns:
            List of resources for "list" operation, single resource dict for "get" operation.

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
            else:
                raise ValueError(f"Operation '{operation}' not supported for projects in Phase 1")

        elif resource == "tasks":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for tasks")
                return client.get_tasks(project_id, h.token, h.base_url, task_type=task_type)
            else:
                raise ValueError(f"Operation '{operation}' not supported for tasks in Phase 1")

        elif resource == "requirements":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for requirements")
                # Requirements are tasks with type="Requirement"
                return client.get_tasks(project_id, h.token, h.base_url, task_type="Requirement")
            else:
                raise ValueError(f"Operation '{operation}' not supported for requirements in Phase 1")

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
                raise ValueError(f"Operation '{operation}' not supported for processes in Phase 1")

        elif resource == "business_processes":
            if operation == "list":
                return client.get_business_processes(h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for business_processes in Phase 1")

        elif resource == "solution_processes":
            if operation == "list":
                return client.get_solution_processes(h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for solution_processes in Phase 1")

        elif resource == "timeboxes":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for timeboxes")
                return client.get_timeboxes(project_id, h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for timeboxes in Phase 1")

        elif resource == "scopes":
            if operation == "list":
                return client.get_scopes(h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for scopes in Phase 1")

        elif resource == "test_cases":
            if operation == "list":
                return client.get_test_cases(h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for test_cases in Phase 1")

        elif resource == "tags":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for tags")
                return client.get_tags(project_id, h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for tags in Phase 1")

        elif resource == "features":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for features")
                return client.get_features(project_id, h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for features in Phase 1")

        elif resource == "test_plans":
            if operation == "list":
                if not project_id:
                    raise ValueError("project_id is required for test_plans")
                return client.get_test_plans(project_id, h.token, h.base_url)
            else:
                raise ValueError(f"Operation '{operation}' not supported for test_plans in Phase 1")

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
