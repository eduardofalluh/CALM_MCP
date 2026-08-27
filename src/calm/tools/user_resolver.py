"""Smart user resolution for CALM assignments.

Tries multiple strategies to resolve a user email/name to a valid CALM user ID:
0. Search existing tasks where the user is already assigned (FULLY AUTOMATIC!)
1. API lookup via get_project_users (if permissions allow)
2. Manual mapping file (CALM_USER_IDS.md)
3. Direct email pass-through (CALM may reject this)

Strategy 0 is the key: if the user has ANY task assigned to them in the project,
we can extract their UUID from that task. This works even with 403 permissions!
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from src.calm import client

log = logging.getLogger("calm-mcp.user_resolver")


def resolve_assignee(
    user_identifier: str,
    project_id: str,
    token: str,
    base_url: str | None = None,
) -> str:
    """Resolve a user email/name to a CALM user ID, trying all available methods.

    Args:
        user_identifier: Email or name (e.g. "eduardo.falluh@syntax.com" or "Eduardo Falluh")
        project_id: CALM project ID (for API lookup)
        token: Auth token
        base_url: CALM base URL

    Returns:
        A valid user ID or email that CALM can resolve. Never raises - always
        returns something usable (worst case: returns the original identifier).
    """
    # Already looks like a UUID? Return as-is
    if len(user_identifier) == 36 and "-" in user_identifier:
        log.info(f"User identifier is already a UUID: {user_identifier}")
        return user_identifier

    user_lower = user_identifier.lower()

    # Strategy 0: Search existing tasks where this user is assigned
    # This is FULLY AUTOMATIC and works even with 403 on user API
    try:
        from src.calm.client import get_tasks

        tasks = get_tasks(project_id=project_id, token=token, base_url=base_url)

        # Look for tasks where AssigneeName matches the user identifier
        for task in tasks[:100]:  # Check first 100 tasks (performance limit)
            assignee_name = (task.get("AssigneeName") or "").lower()
            assignee_id = task.get("AssigneeID")

            if not assignee_id:
                continue

            # Match by name or email in the identifier
            if user_lower in assignee_name or assignee_name in user_lower:
                log.info(
                    f"Resolved '{user_identifier}' to UUID {assignee_id} "
                    f"by finding existing task where user is assigned (AssigneeName: {task.get('AssigneeName')})"
                )
                return assignee_id

    except Exception as e:
        log.warning(f"Could not search existing tasks for user UUID: {e}")

    # Strategy 1: Try API lookup
    try:
        users = client.get_project_users(project_id, token, base_url)
        for u in users:
            email = (u.get("Email") or "").lower()
            name = (u.get("Name") or "").lower()
            if user_lower in email or user_lower in name or email in user_lower:
                log.info(f"Resolved '{user_identifier}' to user ID {u['ID']} via API")
                return u["ID"]
    except Exception as e:
        log.warning(f"API user lookup failed (likely 403): {e}")

    # Strategy 2: Check manual mapping file
    try:
        mapping_file = Path(__file__).parent.parent.parent / "CALM_USER_IDS.md"
        if mapping_file.exists():
            content = mapping_file.read_text()
            for line in content.split("\n"):
                if "|" in line and user_lower in line.lower():
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 3 and parts[2] and "-" in parts[2]:
                        log.info(f"Resolved '{user_identifier}' to {parts[2]} via manual mapping")
                        return parts[2]
    except Exception as e:
        log.warning(f"Manual mapping lookup failed: {e}")

    # Strategy 3: Return email directly (CALM might try to resolve it)
    # But log a warning since CALM strictly prefers UUIDs
    if "<" in user_identifier and ">" in user_identifier:
        email = user_identifier.split("<")[1].split(">")[0].strip()
        log.warning(
            f"Could not resolve '{user_identifier}' to UUID - using email '{email}' directly. "
            f"CALM may show 'Former Member' unless you add UUIDs to CALM_USER_IDS.md"
        )
        return email

    # If it's already an email, return as-is but warn
    if "@" in user_identifier:
        log.warning(
            f"Could not resolve '{user_identifier}' to UUID - using email directly. "
            f"CALM strictly requires UUIDs for assignee_id. To fix: add user UUIDs to CALM_USER_IDS.md "
            f"(instructions in file). Without UUID mapping, assignee may show as 'Former Member'."
        )
        return user_identifier

    # Last resort: return whatever was given
    log.warning(
        f"Could not resolve '{user_identifier}' to UUID, passing through as-is. "
        f"Add user UUID mappings to CALM_USER_IDS.md to fix 'Former Member' issue."
    )
    return user_identifier
