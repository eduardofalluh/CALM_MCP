"""User resolution for CALM assignments.

CALM's Tasks API takes the assignee (shown as "Responsible") as the user's ID —
it refuses an email ("Invalid processor ID"). The user-list API needs a scope
service keys usually don't have, so a person is found where they already appear:

0. Existing tasks in the project assigned to them (works without that scope).
1. The project's user list, if the key may read it.
2. A manual mapping file (CALM_USER_IDS.md), if one exists.

A match is never guessed: an exact name, the name in an email ("jane.doe@…" is
"Jane Doe"), the exact email, or words that fit exactly one person. Anything
else is returned unchanged; the write then saves the item without an assignee
and says so (see unified.py), rather than assigning the wrong person.

Identifiers and names are never logged.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from src.calm import client

log = logging.getLogger("calm-mcp.user_resolver")


def _norm(text: object) -> str:
    return " ".join(str(text or "").split()).lower()


def _candidates(identifier: str) -> set[str]:
    """How the person may be written: as given, and an email's name part."""
    text = _norm(identifier)
    if "<" in text and ">" in text:  # "Jane Doe <jane.doe@x.com>"
        name, _, rest = text.partition("<")
        return {_norm(name), *_candidates(rest.split(">")[0])} - {""}
    found = {text}
    if "@" in text:
        found.add(_norm(re.sub(r"[._\-]+", " ", text.split("@")[0])))
    return found - {""}


def _pick(people: list[tuple[str, str, str]], identifier: str) -> str | None:
    """The one person (id, name, email) the identifier names, or None."""
    wanted = _candidates(identifier)
    exact = {pid for pid, name, email in people if _norm(name) in wanted or (email and _norm(email) in wanted)}
    if len(exact) == 1:
        return exact.pop()
    if exact:
        return None  # two people with that name: never guess
    words = [set(c.split()) for c in wanted if "@" not in c]
    partial = {pid for pid, name, _ in people
               if any(w and w <= set(_norm(name).split()) for w in words)}
    return partial.pop() if len(partial) == 1 else None


def resolve_assignee(
    user_identifier: str,
    project_id: str,
    token: str,
    base_url: str | None = None,
) -> str:
    """The CALM user ID for an email or name, or the identifier unchanged when
    no single person matches. Never raises."""
    identifier = str(user_identifier or "").strip()
    if client._UUID_RE.match(identifier):
        return identifier

    # Strategy 0: people already assigned to tasks in the project.
    try:
        people = {}
        for task in client.get_tasks(project_id=project_id, token=token, base_url=base_url):
            if task.get("AssigneeID") and task.get("AssigneeName"):
                people[task["AssigneeID"]] = (task["AssigneeID"], task["AssigneeName"], "")
        found = _pick(list(people.values()), identifier)
        if found:
            log.info("assignee resolved from the project's task assignments")
            return found
    except Exception as exc:  # noqa: BLE001 — try the next source
        log.warning("could not read the project's tasks to resolve an assignee: %s", type(exc).__name__)

    # Strategy 1: the project's user list (needs a scope most keys don't have).
    try:
        users = client.get_project_users(project_id, token, base_url)
        if isinstance(users, list):
            found = _pick([(u.get("ID"), u.get("Name"), u.get("Email") or "")
                           for u in users if isinstance(u, dict) and u.get("ID")], identifier)
            if found:
                log.info("assignee resolved from the project's user list")
                return found
    except Exception as exc:  # noqa: BLE001
        log.info("project user list not readable: %s", type(exc).__name__)

    # Strategy 2: a manual mapping file, "| name | uuid | email |" rows.
    try:
        mapping_file = Path(__file__).parent.parent.parent / "CALM_USER_IDS.md"
        if mapping_file.exists():
            rows = []
            for line in mapping_file.read_text().splitlines():
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 2 and client._UUID_RE.match(cells[1]):
                    rows.append((cells[1], cells[0], cells[2] if len(cells) > 2 else ""))
            found = _pick(rows, identifier)
            if found:
                log.info("assignee resolved from CALM_USER_IDS.md")
                return found
    except Exception as exc:  # noqa: BLE001
        log.warning("manual user mapping not readable: %s", type(exc).__name__)

    log.info("assignee not resolved to a CALM user; passing it through unchanged")
    return identifier
