"""Tests for _get_all — the no-truncation paging helper.

CALM OData services cap each response at a server page size (e.g. 100 test
cases) and signal continuation either via standard ``@odata.nextLink`` or as a
plain capped page the client must advance with ``$skip``. _get_all follows
whichever is in play so listing functions never silently truncate. These tests
pin both mechanisms, the de-dup guard against an endpoint that ignores $skip,
the small-collection fast path, and that get_test_cases now pages end to end.
"""

from unittest.mock import patch

from src.calm import client


def _page(items, next_link=None):
    d = {"value": items}
    if next_link:
        d["@odata.nextLink"] = next_link
    return d


# ---- (a) server-driven paging via @odata.nextLink -------------------------

def test_follows_absolute_next_link_to_exhaustion():
    base = "https://x.alm.cloud.sap/api/calm-testmanagement/v1/ManualTestCases?$top=100"
    pages = {
        base: _page([{"id": i} for i in range(100)],
                    next_link="https://x.alm.cloud.sap/next?$skiptoken=A"),
        "https://x.alm.cloud.sap/next?$skiptoken=A":
            _page([{"id": i} for i in range(100, 150)]),  # short -> last
    }
    with patch("src.calm.client._get", lambda url, token: pages[url]):
        rows = client._get_all(base, "tok")
    assert len(rows) == 150
    assert rows[0]["id"] == 0 and rows[-1]["id"] == 149


def test_follows_relative_next_link():
    base = "https://x.alm.cloud.sap/api/calm-features/v1/Features"
    pages = {
        base: _page([{"id": 1}], next_link="Features?$skiptoken=xyz"),
        "https://x.alm.cloud.sap/api/calm-features/v1/Features?$skiptoken=xyz":
            _page([{"id": 2}]),
    }
    with patch("src.calm.client._get", lambda url, token: pages[url]):
        rows = client._get_all(base, "tok")
    assert [r["id"] for r in rows] == [1, 2]


# ---- (b) $skip fallback when there is no nextLink -------------------------

def test_skip_fallback_when_page_is_capped_without_link():
    full = [{"id": i} for i in range(100)]          # exactly a capped page
    rest = [{"id": i} for i in range(100, 123)]     # short tail -> stop
    calls = []

    def staged(url, token):
        calls.append(url)
        return _page(rest if "skip=100" in url else full)

    with patch("src.calm.client._get", staged):
        rows = client._get_all("https://x.alm.cloud.sap/c", "tok")
    assert len(rows) == 123
    assert any("%24skip=100" in c or "$skip=100" in c for c in calls)


def test_skip_fallback_dedupes_and_stops_if_skip_ignored():
    # Endpoint ignores $skip and keeps returning the SAME full page.
    full = [{"id": i} for i in range(100)]
    with patch("src.calm.client._get", lambda url, token: _page(full)):
        rows = client._get_all("https://x.alm.cloud.sap/c", "tok")
    # De-dup detects no new rows on the second request -> no runaway, no dupes.
    assert len(rows) == 100


def test_skip_rejected_stops_gracefully():
    # Envelope endpoint caps at a full page but rejects $skip (HTTP 400). The
    # first page must still be returned, not raised — listing never gets worse.
    full = [{"id": i} for i in range(100)]

    def staged(url, token):
        if "skip=100" in url:
            raise RuntimeError('CALM API error: HTTP 400 — "$skip" is not supported yet.')
        return _page(full)

    with patch("src.calm.client._get", staged):
        rows = client._get_all("https://x.alm.cloud.sap/c", "tok")
    assert len(rows) == 100  # page one returned despite the $skip 400


def test_small_collection_makes_no_probe_request():
    calls = []

    def once(url, token):
        calls.append(url)
        return _page([{"id": i} for i in range(5)])  # below _PAGE_PROBE_MIN

    with patch("src.calm.client._get", once):
        rows = client._get_all("https://x.alm.cloud.sap/c", "tok")
    assert len(rows) == 5
    assert len(calls) == 1  # complete in a single read, no needless $skip probe


def test_bare_list_response_handled():
    with patch("src.calm.client._get", lambda url, token: [{"id": 1}, {"id": 2}]):
        rows = client._get_all("https://x.alm.cloud.sap/api/calm-projects/v1/tasks", "tok")
    assert [r["id"] for r in rows] == [1, 2]


def test_with_skip_replaces_existing_skip():
    out = client._with_skip("https://h/c?$top=100&$skip=0&$filter=a", 100)
    assert "%24skip=100" in out or "$skip=100" in out
    assert "skip=0" not in out


# ---- end-to-end: get_test_cases now pages --------------------------------

def test_get_test_cases_pages_all_matches():
    p1 = _page([{"uuid": f"u{i}", "displayId": str(i),
                 "toTagAssignments": [{"label": "SIT"}]} for i in range(100)],
               next_link="https://x.alm.cloud.sap/next")
    p2 = _page([{"uuid": "u100", "displayId": "100",
                 "toTagAssignments": [{"label": "SIT"}]}])
    pages = iter([p1, p2])
    with patch("src.calm.client._get", lambda url, token: next(pages)):
        rows = client.get_test_cases("tok", "https://x.alm.cloud.sap", tag="SIT")
    assert len(rows) == 101  # the 101st SIT match is no longer dropped
    assert rows[-1]["Display ID"] == "100"
