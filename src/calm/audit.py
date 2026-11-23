"""One audit line per tool call: who, which SAP Cloud ALM, which tool, the outcome, how long.

So an admin can say who read or changed which client's CALM (ISO 27001 / SOC 2), without
keeping what was asked or answered: never the data, the search text or the result. The
caller is the person whose sign-in the server verified ("local" on a local MCP,
"not signed in" otherwise); their corporate email is an operational reference.
"""

from __future__ import annotations

import logging
import time

from fastmcp.server.middleware import Middleware

audit_log = logging.getLogger("calm-mcp.audit")


def _caller() -> str:
    from fastmcp.server.dependencies import get_http_request

    from src.calm import tenants

    try:
        request = get_http_request()
    except Exception:  # noqa: BLE001 — no HTTP request: a local (stdio) MCP
        return "local"
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    person = tenants.verified_person(token.strip()) if scheme.lower() == "bearer" else None
    return tenants.person_email(person) if person else "not signed in"


def _word(value) -> str:
    """A short, plain label from an argument: never free text."""
    text = str(value or "").strip()
    return text[:40] if text and all(c.isalnum() or c in "-_ ." for c in text) else ("-" if not text else "?")


class AuditMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        args = getattr(context.message, "arguments", None) or {}
        started, outcome = time.monotonic(), "ok"
        try:
            return await call_next(context)
        except Exception as exc:
            outcome = f"failed ({type(exc).__name__})"
            raise
        finally:
            try:
                audit_log.info("AUDIT user=%s tenant=%s tool=%s resource=%s operation=%s outcome=%s ms=%d",
                               _caller(), _word(args.get("tenant")) if args.get("tenant") else "-",
                               getattr(context.message, "name", "?"), _word(args.get("resource")),
                               _word(args.get("operation") or args.get("action")), outcome,
                               int((time.monotonic() - started) * 1000))
            except Exception:  # noqa: BLE001 — the audit line never breaks the call
                audit_log.warning("AUDIT line could not be written", exc_info=True)
