"""Tests for the analytics, team_roles, and feature reference-data resources.

Verified live against a real tenant (Ebsco): analytics DataSet rows are a
pivoted key/value grid (d1k/d1v..d30k/d30v + m1k/m1v..m15k/m15v) and the server
caps each page at 1000 rows with no @odata.nextLink, so completeness requires
$skip paging. These tests pin the unpivoting, the paging loop, the client-side
project filter, and the formatter shapes.
"""

from unittest.mock import patch

from src.calm import client


def _row(dims: dict, mets: dict, provider="DP_TASKS", date="20261007") -> dict:
    r = {"provider": provider, "date": date}
    for i, (k, v) in enumerate(dims.items(), start=1):
        r[f"d{i}k"] = k
        r[f"d{i}v"] = v
    for i, (k, v) in enumerate(mets.items(), start=1):
        r[f"m{i}k"] = k
        r[f"m{i}v"] = v
    return r


def test_unpivot_collapses_dimensions_and_metrics():
    raw = _row({"project": "p1", "statusText": "Done"}, {"counter": "1", "effort": "2.5"})
    out = client._unpivot_analytics_row(raw)
    assert out["project"] == "p1"
    assert out["statusText"] == "Done"
    assert out["Metrics"] == {"counter": "1", "effort": "2.5"}
    assert out["Provider"] == "DP_TASKS"
    assert out["Snapshot"] == "20261007"


def test_analytics_pages_with_skip_until_short_page():
    # First page: a full 1000 rows -> must fetch again. Second page: 3 rows -> stop.
    page1 = [_row({"project": "p1", "statusText": "Open"}, {"counter": "1"})] * 1000
    page2 = [_row({"project": "p1", "statusText": "Done"}, {"counter": "1"})] * 3
    calls = []

    # Deterministic stub keyed on the $skip value in the URL.
    def staged_get(url, token):
        calls.append(url)
        return {"value": page1 if "skip=0" in url else page2}

    with patch("src.calm.client._get", staged_get):
        rows = client.get_analytics("tok", base_url="https://x.alm.cloud.sap")
    assert len(rows) == 1003
    assert len(calls) == 2  # paged exactly twice (1000 then 3)


def test_analytics_project_filter_client_side():
    rows_raw = [
        _row({"project": "keep", "statusText": "Done"}, {"counter": "1"}),
        _row({"project": "drop", "statusText": "Open"}, {"counter": "1"}),
    ]
    with patch("src.calm.client._get", lambda url, token: {"value": rows_raw}):
        rows = client.get_analytics("tok", base_url="https://x.alm.cloud.sap", project_id="keep")
    assert len(rows) == 1 and rows[0]["project"] == "keep"


def test_analytics_filter_url_has_provider_and_skip():
    captured = {}

    def fake_get(url, token):
        captured["url"] = url
        return {"value": []}

    with patch("src.calm.client._get", fake_get):
        client.get_analytics("tok", provider="DP_PROJECTS", base_url="https://x.alm.cloud.sap")
    assert "provider%20eq%20%27DP_PROJECTS%27" in captured["url"]
    assert "skip=0" in captured["url"]


def test_analytics_top_caps_rows():
    rows_raw = [_row({"project": "p", "statusText": "Open"}, {"counter": "1"})] * 10
    with patch("src.calm.client._get", lambda url, token: {"value": rows_raw}):
        rows = client.get_analytics("tok", base_url="https://x.alm.cloud.sap", top=4)
    assert len(rows) == 4


def test_team_roles_formatting():
    raw = [
        {"roleId": "r1", "roleName": "Project Lead", "roleDescription": "Leads",
         "isCustom": False, "members": [{"id": "u1"}, {"id": "u2"}]},
        {"roleId": "r2", "roleName": "Tester", "roleDescription": "Tests",
         "isCustom": True, "members": []},
    ]
    with patch("src.calm.client._get", lambda url, token: raw):
        rows = client.get_team_roles("team-1", "tok", "https://x.alm.cloud.sap")
    assert rows[0]["Role Name"] == "Project Lead"
    assert rows[0]["Member Count"] == 2
    assert rows[1]["Member Count"] == 0 and rows[1]["Custom"] is True


def test_feature_status_and_priorities():
    with patch("src.calm.client._get",
               lambda url, token: {"value": [{"code": "CREATED", "name": "In Specification"}]}):
        assert client.get_feature_status("tok", "https://x.alm.cloud.sap") == [
            {"Code": "CREATED", "Name": "In Specification"}
        ]
    with patch("src.calm.client._get",
               lambda url, token: {"value": [{"code": "10", "name": "Very High"}]}):
        assert client.get_feature_priorities("tok", "https://x.alm.cloud.sap") == [
            {"Code": "10", "Name": "Very High"}
        ]
