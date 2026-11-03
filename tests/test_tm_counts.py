"""BTP Test Management lists: exact totals, server-side counts, no answer too
long to count right — the same rules as calm_resource lists (2026-11-03)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm.tools.unified import LIST_ROW_LIMIT  # noqa: E402


class Ctx:
    """No request_context — credentials come from env."""


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setenv("TM_BASE_URL", "https://tm.example.hana.ondemand.com/odata/v4/test-management")
    monkeypatch.setenv("TM_TOKEN", "tm-tok")
    from fastmcp import FastMCP

    from src.calm.tools.test_repo import register

    mcp = FastMCP("t")
    register(mcp)
    return {n: asyncio.run(mcp.get_tool(n)).fn for n in ("get_tm_test_cases", "get_tm_requirements", "tm_odata_read")}


def _cases(n):
    return {"items": [{"id": f"tc{i}", "priority_code": "10" if i % 3 else "20", "scenario_type": "negative"}
                      for i in range(n)]}


def test_counts_are_made_by_the_server(tools):
    with patch("src.calm.tm_client.get_test_cases", return_value=_cases(9)):
        out = tools["get_tm_test_cases"](Ctx(), filter="scenario_type eq 'negative'", summarize_by="Priority_Code")
    assert out["Total"] == 9 and {(g["priority_code"], g["Count"]) for g in out["Groups"]} == {("10", 6), ("20", 3)}
    assert out["Check"] == {"Rows Read": 9, "Groups Add Up": True}


def test_a_whole_read_says_its_exact_total(tools):
    with patch("src.calm.tm_client.get_test_cases", return_value=_cases(4)):
        out = tools["get_tm_test_cases"](Ctx())
    assert out["Total"] == 4 and len(out["items"]) == 4


def test_a_long_list_gives_the_total_not_the_rows(tools):
    with patch("src.calm.tm_client.get_requirements", return_value=_cases(LIST_ROW_LIMIT + 1)):
        out = tools["get_tm_requirements"](Ctx())
    assert out["Total"] == LIST_ROW_LIMIT + 1 and out["Returned"] == 0 and "items" not in out
    assert "summarize_by" in out["How To Get Rows"]


def test_a_page_uses_sap_s_count_as_the_total(tools):
    page = {"items": _cases(2)["items"], "count": 40}
    with patch("src.calm.tm_client.get_test_cases", return_value=page):
        out = tools["get_tm_test_cases"](Ctx(), top=2, count=True)
    assert out["Total"] == 40
    with patch("src.calm.tm_client.get_test_cases", return_value={"items": page["items"]}):
        out = tools["get_tm_test_cases"](Ctx(), top=2)
    assert "Total" not in out  # one page, no count asked: no total claimed


def test_summarize_needs_the_whole_set_and_real_fields(tools):
    # Answers, not tool errors — the same rule as every CALM read.
    with patch("src.calm.tm_client.get_test_cases", return_value=_cases(3)):
        out = tools["get_tm_test_cases"](Ctx(), top=2, summarize_by="priority_code")
        assert out["status"] == "invalid_request" and "drop top" in out["message"]
        out = tools["get_tm_test_cases"](Ctx(), summarize_by="colour")
        assert out["status"] == "invalid_request" and "priority_code" in out["message"]


def test_a_whole_read_is_checked_against_sap_s_count(tools):
    with patch("src.calm.tm_client.get_test_cases", return_value={**_cases(4), "count": 4}) as gt:
        out = tools["get_tm_test_cases"](Ctx())
    assert gt.call_args.kwargs["count"] is True  # always ask SAP for its total
    assert out["Check"] == {"Rows Read": 4, "Returned": 4, "Not Returned": 0, "SAP Count": 4}
    assert "Warning" not in out
    with patch("src.calm.tm_client.get_test_cases", return_value={**_cases(4), "count": 6}):
        out = tools["get_tm_test_cases"](Ctx(), summarize_by="priority_code")
    assert "6 rows but 4 were read" in out["Warning"] and out["Check"]["SAP Count"] == 6


def test_pages_are_capped_and_say_where_to_continue(tools):
    full_page = {"items": _cases(LIST_ROW_LIMIT)["items"], "count": 700}
    with patch("src.calm.tm_client.get_test_cases", return_value=full_page) as gt:
        out = tools["get_tm_test_cases"](Ctx(), top=1000, skip=300, count=True)
    assert gt.call_args.kwargs["top"] == LIST_ROW_LIMIT
    assert out["Next Skip"] == 300 + LIST_ROW_LIMIT and out["Check"]["Not Returned"] == 700 - 600
    with patch("src.calm.tm_client.get_requirements", return_value={"items": [], "count": 0}) as gr:
        tools["get_tm_requirements"](Ctx(), top=10, skip=20)
    assert gr.call_args.kwargs["skip"] == 20 and gr.call_args.kwargs["top"] == 10


def test_a_read_sap_refuses_is_an_answer_but_a_credential_fault_fails(tools):
    bad = RuntimeError("TM OData request failed: HTTP 400 at https://x/TestCases — {\"error\":\"bad filter\"}")
    with patch("src.calm.tm_client.get_test_cases", side_effect=bad):
        out = tools["get_tm_test_cases"](Ctx(), filter="nope eq 1")
    assert out["status"] == "invalid_request" and "bad filter" in out["message"]
    with patch("src.calm.tm_client.get_test_cases", side_effect=RuntimeError("TM OData request failed: HTTP 401")):
        with pytest.raises(RuntimeError, match="401"):
            tools["get_tm_test_cases"](Ctx())


def test_raw_read_is_capped_too(tools):
    with patch("src.calm.tm_client.odata_read", return_value=_cases(LIST_ROW_LIMIT + 1)):
        out = tools["tm_odata_read"]("TestCases", Ctx())
    assert out["Returned"] == 0 and out["Total"] == LIST_ROW_LIMIT + 1
    with patch("src.calm.tm_client.odata_read", return_value={"value": "x"}):
        assert tools["tm_odata_read"]("TestCases('a')", Ctx()) == {"value": "x"}


def test_health_says_whether_the_credential_can_read(monkeypatch):
    # Live 2026-11-03: /health answered (no sign-in needed) while every read got 401.
    monkeypatch.setenv("TM_BASE_URL", "https://tm.example.hana.ondemand.com/odata/v4/test-management")
    monkeypatch.setenv("TM_TOKEN", "tm-tok")
    from fastmcp import FastMCP

    from src.calm.tools.test_repo import register

    mcp = FastMCP("t")
    register(mcp)
    health = asyncio.run(mcp.get_tool("tm_health")).fn
    with patch("src.calm.tm_client.service_health", return_value={"status": "UP"}), \
            patch("src.calm.tm_client.get_test_cases", side_effect=RuntimeError("TM OData request failed: HTTP 401")):
        out = health(Ctx())
    assert out["reachable"] is True and out["authorized"] is False and "401" in out["authorization_error"]
    with patch("src.calm.tm_client.service_health", return_value={"status": "UP"}), \
            patch("src.calm.tm_client.get_test_cases", return_value={"items": []}):
        assert health(Ctx())["authorized"] is True
