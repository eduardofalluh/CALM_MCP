"""Tests for TOON output middleware (token-efficient tool output).

Covers: the kill switch, text-block encoding, round-trip fidelity, leaving
non-JSON and non-text content untouched, and the never-break fallback when the
encoder raises.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp.tools import ToolResult
from mcp.types import ImageContent, TextContent

from src.calm import toon_middleware as tm


# --------------------------------------------------------------------------- #
# Kill switch                                                                   #
# --------------------------------------------------------------------------- #
def test_toon_enabled_default_on(monkeypatch):
    monkeypatch.delenv("CALM_OUTPUT_FORMAT", raising=False)
    assert tm.toon_enabled() is True


def test_toon_enabled_json_kill_switch(monkeypatch):
    monkeypatch.setenv("CALM_OUTPUT_FORMAT", "json")
    assert tm.toon_enabled() is False


def test_toon_enabled_explicit_toon(monkeypatch):
    monkeypatch.setenv("CALM_OUTPUT_FORMAT", "toon")
    assert tm.toon_enabled() is True


def test_toon_enabled_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv("CALM_OUTPUT_FORMAT", "  JSON  ")
    assert tm.toon_enabled() is False


def test_toon_enabled_false_when_library_missing(monkeypatch):
    monkeypatch.setattr(tm, "_TOON_AVAILABLE", False)
    monkeypatch.delenv("CALM_OUTPUT_FORMAT", raising=False)
    assert tm.toon_enabled() is False


# --------------------------------------------------------------------------- #
# encode_text_to_toon                                                           #
# --------------------------------------------------------------------------- #
def test_encode_uniform_array_uses_tabular_toon():
    data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    out = tm.encode_text_to_toon(json.dumps(data))
    # TOON tabular header for a uniform array of 2 rows with columns a,b.
    assert out != json.dumps(data)
    assert "[2]{a,b}:" in out


def test_encode_single_object():
    data = {"status": "ok", "count": 3}
    out = tm.encode_text_to_toon(json.dumps(data))
    assert out != json.dumps(data)
    # Scalars render as key: value lines in TOON.
    assert "status" in out and "ok" in out


def test_encode_leaves_plain_string_untouched():
    text = "This is a help string, not JSON."
    assert tm.encode_text_to_toon(text) == text


def test_encode_leaves_json_scalar_untouched():
    # A bare JSON number/string doesn't start with { or [ — left as-is.
    assert tm.encode_text_to_toon("42") == "42"
    assert tm.encode_text_to_toon('"hello"') == '"hello"'


def test_encode_leaves_invalid_json_untouched():
    # Starts with { but isn't valid JSON.
    broken = '{not valid json at all'
    assert tm.encode_text_to_toon(broken) == broken


def test_encode_empty_string_untouched():
    assert tm.encode_text_to_toon("") == ""


def test_encode_empty_list():
    out = tm.encode_text_to_toon("[]")
    # Should not raise; produces a (possibly empty) TOON rendering.
    assert isinstance(out, str)


def test_encode_falls_back_to_json_on_encoder_error(monkeypatch):
    def boom(_data):
        raise RuntimeError("encoder exploded")

    monkeypatch.setattr(tm, "_toon_encode", boom)
    original = json.dumps([{"a": 1}])
    assert tm.encode_text_to_toon(original) == original


# --------------------------------------------------------------------------- #
# Round-trip fidelity                                                           #
# --------------------------------------------------------------------------- #
def test_round_trip_uniform_array():
    from toon_format import decode

    data = [{"id": "T1", "title": "Alpha"}, {"id": "T2", "title": "Beta"}]
    out = tm.encode_text_to_toon(json.dumps(data))
    assert decode(out) == data


def test_round_trip_nested_object():
    from toon_format import decode

    data = {"project": "P1", "tasks": [{"id": "T1"}, {"id": "T2"}], "count": 2}
    out = tm.encode_text_to_toon(json.dumps(data))
    assert decode(out) == data


# --------------------------------------------------------------------------- #
# _rewrite_result                                                               #
# --------------------------------------------------------------------------- #
def test_rewrite_result_encodes_text_block():
    data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    tr = ToolResult(content=[TextContent(type="text", text=json.dumps(data))])
    tm._rewrite_result(tr)
    assert "[2]{a,b}:" in tr.content[0].text


def test_rewrite_result_leaves_non_text_block():
    img = ImageContent(type="image", data="aGVsbG8=", mimeType="image/png")
    tr = ToolResult(content=[img])
    tm._rewrite_result(tr)
    # Image content is untouched.
    assert tr.content[0].data == "aGVsbG8="


def test_rewrite_result_handles_empty_content():
    tr = ToolResult(content=[])
    # Should not raise.
    assert tm._rewrite_result(tr) is tr


# --------------------------------------------------------------------------- #
# Middleware on_call_tool                                                       #
# --------------------------------------------------------------------------- #
def _run(coro):
    return asyncio.run(coro)


def test_middleware_encodes_when_enabled(monkeypatch):
    monkeypatch.setenv("CALM_OUTPUT_FORMAT", "toon")
    data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    tr = ToolResult(content=[TextContent(type="text", text=json.dumps(data))])

    async def call_next(_ctx):
        return tr

    mw = tm.ToonOutputMiddleware()
    result = _run(mw.on_call_tool(context=None, call_next=call_next))
    assert "[2]{a,b}:" in result.content[0].text


def test_middleware_leaves_json_when_kill_switch(monkeypatch):
    monkeypatch.setenv("CALM_OUTPUT_FORMAT", "json")
    data = [{"a": 1, "b": 2}]
    original = json.dumps(data)
    tr = ToolResult(content=[TextContent(type="text", text=original)])

    async def call_next(_ctx):
        return tr

    mw = tm.ToonOutputMiddleware()
    result = _run(mw.on_call_tool(context=None, call_next=call_next))
    assert result.content[0].text == original


def test_middleware_never_raises_on_bad_result(monkeypatch):
    monkeypatch.setenv("CALM_OUTPUT_FORMAT", "toon")

    sentinel = object()

    async def call_next(_ctx):
        return sentinel

    mw = tm.ToonOutputMiddleware()
    # A result with no .content attribute must pass through, not raise.
    result = _run(mw.on_call_tool(context=None, call_next=call_next))
    assert result is sentinel


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
