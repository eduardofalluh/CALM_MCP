"""calm_health lists the connection key's CALM API permissions against the set in
the Syntax setup guide (2026-11-09: "I don't know if all of my keys have this").
Names come from the key's own token; the token itself is never returned."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm.tools import health  # noqa: E402


def _jwt(scopes):
    part = base64.urlsafe_b64encode(json.dumps({"scope": scopes}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{part}.sig"


def test_granted_and_missing_permissions_with_what_each_one_opens():
    granted = [f"sapcloudalm!b1.{s}" for s in health.DOCUMENTED_SCOPES if s != "calm-api.testplans.read"]
    with patch.object(health, "get_calm_headers", return_value=SimpleNamespace(token=_jwt(granted + ["uaa.resource"]))):
        out = health._permissions(object())
    assert len(out["granted"]) == len(health.DOCUMENTED_SCOPES) - 1 and "uaa.resource" not in out["granted"]
    assert list(out["missing"]) == ["calm-api.testplans.read"]
    assert out["missing"]["calm-api.testplans.read"].startswith("without it:")
    assert out["has_every_documented_permission"] is False
    assert all("eyJ" not in str(v) for v in out.values())  # the token never comes back


def test_unknown_when_there_is_no_token_or_it_is_not_a_jwt():
    with patch.object(health, "get_calm_headers", side_effect=RuntimeError("No SAP Cloud ALM tenant configured")):
        assert "no token" in health._permissions(object())["reason"]
    with patch.object(health, "get_calm_headers", return_value=SimpleNamespace(token="opaque-token")):
        assert health._permissions(object())["status"] == "unknown"


def test_the_documented_set_is_the_setup_guide_list():
    assert len(health.DOCUMENTED_SCOPES) == 24
    assert {"calm-api.testplans.read", "calm-api.tests.read", "calm-api.analytics.read",
            "calm-api.documents.delete"} <= set(health.DOCUMENTED_SCOPES)
