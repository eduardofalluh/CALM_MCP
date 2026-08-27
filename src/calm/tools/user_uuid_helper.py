"""Helper tool to guide users on getting their CALM user UUID."""

from __future__ import annotations

from fastmcp import Context, FastMCP

from src.calm.dependencies import get_calm_headers


def register(mcp: FastMCP) -> None:
    """Register UUID helper tool."""

    @mcp.tool()
    def get_my_calm_user_uuid_instructions(project_id: str, ctx: Context) -> dict:
        """Get instructions on how to find your CALM user UUID for task assignment.

        CALM requires UUIDs (not emails) for the assignee_id field. If you're seeing
        "Former Member" when assigning tasks, you need to get your UUID and add it
        to CALM_USER_IDS.md.

        This tool returns 3 methods to get your UUID, with exact URLs and steps.

        Args:
            project_id: Your CALM project ID (to generate the correct API URL)

        Returns:
            Instructions with 3 methods to get your user UUID
        """
        if not project_id:
            raise ValueError("project_id is required")

        h = get_calm_headers(ctx)
        base_url = h.base_url or "https://[tenant].[region].alm.cloud.sap"

        return {
            "Why you need this": "CALM strictly requires user UUIDs for assignee_id. Emails don't work.",
            "Your project ID": project_id,

            "Method 1 - Browser DevTools (Easiest)": {
                "steps": [
                    "Open CALM in browser → Your project → Settings → Team",
                    "Press F12 → Network tab → Reload the page",
                    f"Find request to: /projects/{project_id}/users",
                    "Click it → Preview tab → Find your email in the list",
                    "Copy the 'id' field (36-character UUID like a1b2c3d4-e5f6-...)",
                    "Add it to CALM_USER_IDS.md file",
                ],
            },

            "Method 2 - Postman / API Client": {
                "method": "GET",
                "url": f"{base_url}/api/calm-projects/v1/projects/{project_id}/users",
                "headers": {
                    "Authorization": "Bearer YOUR_CALM_TOKEN"
                },
                "steps": [
                    "Send the GET request above",
                    "Find your email in the JSON response",
                    "Copy the 'id' field next to your email",
                    "Add it to CALM_USER_IDS.md",
                ],
            },

            "Method 3 - Ask Your Team Admin": {
                "info": "Your SAP BTP admin can look up user IDs in BTP Cockpit → Subscriptions → Cloud ALM → Users"
            },

            "After you get your UUID": {
                "step 1": f"Open the file: CALM_USER_IDS.md (in the MCP server directory)",
                "step 2": f"Find the section for project {project_id}",
                "step 3": "Replace PASTE_36_CHAR_UUID_HERE with your actual UUID",
                "step 4": "Save the file",
                "step 5": "Try assigning tasks again - it will now work!",
                "example_entry": "| eduardo.falluh@syntax.com | a1b2c3d4-e5f6-7890-abcd-ef1234567890 | Eduardo Falluh |",
            },

            "File location": "CALM_MCP/CALM_USER_IDS.md",
        }
