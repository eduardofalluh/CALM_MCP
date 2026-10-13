"""TOON output encoding for tool results (token savings).

Re-encodes the *text* content block of every tool result from JSON into TOON
(Token-Oriented Object Notation, https://github.com/toon-format/toon), which
represents the same data in far fewer tokens — ~40-60% smaller for the uniform
arrays that ``calm_resource`` list operations return.

Why middleware (not changing tool return values)?
  Tool functions keep returning plain Python ``dict``/``list`` objects, so:
    * every unit test that calls a tool function directly still gets objects;
    * the ``structured_content`` field on the MCP wire stays JSON, so any client
      that reads structured output is unaffected.
  Only the human/LLM-facing text block is rewritten — that is what an LLM agent
  actually reads into its context, so that is where the token savings land.

Kill switch (no code redeploy needed):
    CALM_OUTPUT_FORMAT unset / "toon"  -> TOON (default)
    CALM_OUTPUT_FORMAT = "json"        -> leave JSON untouched

Safety: this can never break a tool call. If the library is missing, the text
isn't JSON (e.g. a plain help/instructions string), or the encoder raises, the
original text is left exactly as it was.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastmcp.server.middleware import Middleware

log = logging.getLogger("calm-mcp")

try:  # The encoder is an optional dependency; degrade gracefully if absent.
    from toon_format import encode as _toon_encode

    _TOON_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when lib is uninstalled
    _TOON_AVAILABLE = False


def toon_enabled() -> bool:
    """True when tool text output should be TOON-encoded.

    Default is on; set ``CALM_OUTPUT_FORMAT=json`` to revert to JSON instantly
    (per-agent env var, no code change). Disabled automatically if the TOON
    library isn't importable.
    """
    if not _TOON_AVAILABLE:
        return False
    return os.getenv("CALM_OUTPUT_FORMAT", "toon").strip().lower() != "json"


def encode_text_to_toon(text: str) -> str:
    """Return the TOON encoding of a JSON text block, or the original text.

    Leaves the text untouched when it isn't a JSON object/array (plain help or
    instruction strings), when it doesn't parse, or when encoding fails — so the
    caller always has valid output.
    """
    if not isinstance(text, str) or not text:
        return text
    stripped = text.lstrip()
    # Only JSON objects/arrays carry the structured payloads worth re-encoding.
    # Plain strings (help text, instructions) start with neither { nor [.
    if not stripped or stripped[0] not in "[{":
        return text
    try:
        data: Any = json.loads(text)
    except ValueError:
        return text
    if not isinstance(data, (dict, list)):
        return text
    try:
        return _toon_encode(data)
    except Exception:  # pragma: no cover - defensive; encoder is robust
        log.debug("TOON encode failed; keeping JSON", exc_info=True)
        return text


def _rewrite_result(result: Any) -> Any:
    """Rewrite JSON text blocks of a ToolResult to TOON, in place."""
    content = getattr(result, "content", None)
    if not content:
        return result
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
        new_text = encode_text_to_toon(getattr(block, "text", None))
        if new_text is not None and new_text != getattr(block, "text", None):
            block.text = new_text
    return result


class ToonOutputMiddleware(Middleware):
    """Encode tool text output as TOON when enabled (see module docstring)."""

    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        result = await call_next(context)
        if not toon_enabled():
            return result
        try:
            return _rewrite_result(result)
        except Exception:  # pragma: no cover - belt and suspenders
            log.debug("TOON middleware skipped on error", exc_info=True)
            return result


try:  # content-block class for the alert; degrade gracefully if unavailable
    from mcp.types import TextContent as _TextContent
except Exception:  # pragma: no cover
    _TextContent = None  # type: ignore[assignment]


def _attach_truncation_alert(result: Any, notices: list) -> None:
    """Prepend a clear, human-readable truncation alert block to ``result``.

    A separate text block (not a rewrite of the data block) so it survives TOON
    encoding and any middleware ordering, and so structured-output clients still
    get their untouched JSON payload. Never raises.
    """
    content = getattr(result, "content", None)
    if content is None:
        return
    lines = ["⚠️ TRUNCATION ALERT — the results below are INCOMPLETE:"]
    for n in notices:
        lines.append(f"  • {n.get('message', 'a listing was truncated')}")
    lines.append("Re-run with a narrower filter to get the full set.")
    alert = "\n".join(lines)

    block = None
    for b in content:  # mirror an existing text block's class for wire-compat
        if getattr(b, "type", None) == "text":
            try:
                block = type(b)(type="text", text=alert)
            except Exception:
                block = None
            break
    if block is None and _TextContent is not None:
        block = _TextContent(type="text", text=alert)
    if block is not None:
        content.insert(0, block)


class TruncationAlertMiddleware(Middleware):
    """Alert the user whenever a paged read was cut short by a safety ceiling.

    Installs a per-request truncation sink before each tool call; if the client's
    paging helper recorded any truncation while serving the call, prepends a loud
    alert block to the result. Applies to EVERY collection (tasks, test cases,
    features, …) because all list getters page through ``client._get_all``.
    """

    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        from src.calm import client

        sink, token = client.install_truncation_sink()
        try:
            result = await call_next(context)
        finally:
            client.reset_truncation_sink(token)
        if sink:
            try:
                _attach_truncation_alert(result, sink)
            except Exception:  # pragma: no cover - alerting must never break a call
                log.debug("could not attach truncation alert", exc_info=True)
        return result
