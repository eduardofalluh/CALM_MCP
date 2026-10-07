"""Tests for test-case tag exposure + server-side tag/project filtering.

CALM's Test Management OData service exposes a test case's tags via the
``toTagAssignments`` navigation collection. The client expands it so every
test case carries a ``Tags`` list, and supports server-side filtering by tag
label and/or project id. The exact OData forms here were verified live against
a real tenant: ``projectId`` (Edm.Guid) must be UNquoted, the tag label is a
quoted string, and both combine with ``and``.
"""

from unittest.mock import patch

from src.calm import client


def _capture(**kwargs):
    captured = {}

    def fake_get(url, token):
        captured["url"] = url
        return {"value": [
            {"uuid": "u1", "displayId": "8-1-9", "projectId": "p1", "title": "SIT - Login",
             "priorityCode": 2, "toTagAssignments": [{"label": "SIT"}, {"label": "P2P"}]},
        ]}

    with patch("src.calm.client._get", fake_get):
        rows = client.get_test_cases("tok", "https://x.alm.cloud.sap", **kwargs)
    return captured["url"], rows


def test_tags_exposed_in_formatter():
    _, rows = _capture()
    assert rows[0]["Tags"] == ["SIT", "P2P"]
    assert rows[0]["Display ID"] == "8-1-9"


def test_expand_always_present():
    url, _ = _capture()
    assert "$expand=toTagAssignments" in url
    # No filter when neither tag nor project given.
    assert "$filter" not in url


def test_project_filter_guid_unquoted():
    url, _ = _capture(project_id="c7773e52-9eb2-446f-8e7e-4cd4a00819bb")
    # Edm.Guid must not be quoted (quoting returns HTTP 400 from CALM).
    assert "projectId%20eq%20c7773e52-9eb2-446f-8e7e-4cd4a00819bb" in url
    assert "projectId%20eq%20%27" not in url


def test_tag_filter_label_quoted():
    url, _ = _capture(tag="SIT")
    assert "toTagAssignments" in url and "label%20eq%20%27SIT%27" in url


def test_combined_filter_uses_and():
    url, _ = _capture(project_id="g1", tag="SIT")
    assert "%20and%20" in url


def test_tag_single_quote_escaped():
    url, _ = _capture(tag="O'Brien")
    # Embedded single quote doubled per OData, then percent-encoded.
    assert "O%27%27Brien" in url


def test_missing_tag_assignments_yields_empty_list():
    def fake_get(url, token):
        return {"value": [{"uuid": "u2", "title": "No tags", "priorityCode": 1}]}

    with patch("src.calm.client._get", fake_get):
        rows = client.get_test_cases("tok", "https://x.alm.cloud.sap")
    assert rows[0]["Tags"] == []
