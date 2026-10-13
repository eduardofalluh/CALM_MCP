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


def test_with_skip_preserves_encoded_filter_verbatim():
    # Regression: a percent-encoded $filter (space -> %20, unquoted Edm.Guid)
    # must survive _with_skip byte-for-byte. Re-encoding the whole query turned
    # %20 into + and corrupted the GUID comparison, so CALM returned HTTP 400
    # ("Edm.Boolean / Edm.Guid are not compatible") and filtered listings
    # silently capped at the first 100 rows.
    guid = "11111111-1111-1111-1111-111111111111"
    url = ("https://h/api/calm-testmanagement/v1/ManualTestCases"
           "?$expand=toTagAssignments"
           f"&$filter=projectId%20eq%20{guid}")
    out = client._with_skip(url, 100)
    assert f"$filter=projectId%20eq%20{guid}" in out  # untouched, no '+' mangling
    assert "projectId+eq" not in out
    assert "$expand=toTagAssignments" in out
    assert out.endswith("%24skip=100")


# ---- end-to-end: get_test_cases now pages --------------------------------

# ---- truncation alerting: a ceiling-hit read is never silent -------------

def _install_sink():
    return client.install_truncation_sink()


def test_skip_paging_records_truncation_when_request_ceiling_hit():
    # Endless distinct full pages: only the request ceiling can stop paging.
    def endless(url, token):
        skip = 0
        if "skip=" in url:
            import re
            m = re.search(r"skip=(\d+)", url)
            skip = int(m.group(1)) if m else 0
        return _page([{"id": skip + i} for i in range(100)])  # 100 fresh ids

    sink, token = _install_sink()
    orig = client._PAGE_MAX_REQUESTS
    client._PAGE_MAX_REQUESTS = 3
    try:
        with patch("src.calm.client._get", endless):
            rows = client._get_all("https://x.alm.cloud.sap/api/calm-tasks/v1/things", "tok")
    finally:
        client._PAGE_MAX_REQUESTS = orig
        client.reset_truncation_sink(token)
    assert len(rows) >= 100            # returned the rows it did fetch
    assert len(sink) == 1              # and recorded exactly one truncation
    assert sink[0]["limit"] == "max-requests"
    assert sink[0]["resource"] == "things"
    assert "TRUNCATED" in sink[0]["message"]


def test_nextlink_paging_records_truncation_when_row_ceiling_hit():
    def linked(url, token):
        return _page([{"id": f"{url}-{i}"} for i in range(100)],
                     next_link="https://x.alm.cloud.sap/next")

    sink, token = _install_sink()
    orig = client._PAGE_MAX_ROWS
    client._PAGE_MAX_ROWS = 250
    try:
        with patch("src.calm.client._get", linked):
            rows = client._get_all("https://x.alm.cloud.sap/api/calm-features/v1/Features", "tok")
    finally:
        client._PAGE_MAX_ROWS = orig
        client.reset_truncation_sink(token)
    assert len(sink) == 1
    assert sink[0]["limit"] == "max-rows"
    assert sink[0]["resource"] == "Features"


def test_complete_paging_records_no_truncation():
    # Two clean pages that end naturally -> no truncation notice at all.
    full = [{"id": i} for i in range(100)]
    rest = [{"id": i} for i in range(100, 140)]
    sink, token = _install_sink()
    try:
        with patch("src.calm.client._get",
                   lambda url, tok: _page(rest if "skip=100" in url else full)):
            rows = client._get_all("https://x.alm.cloud.sap/c", "tok")
    finally:
        client.reset_truncation_sink(token)
    assert len(rows) == 140
    assert sink == []  # complete read -> silent, no false alarm


def test_bare_list_records_no_truncation():
    sink, token = _install_sink()
    try:
        with patch("src.calm.client._get", lambda url, tok: [{"id": i} for i in range(5000)]):
            rows = client._get_all("https://x.alm.cloud.sap/api/calm-tasks/v1/tasks", "tok")
    finally:
        client.reset_truncation_sink(token)
    assert len(rows) == 5000
    assert sink == []  # bare lists are complete in one response


def test_record_truncation_without_sink_only_logs(caplog):
    # No sink installed (e.g. a direct unit call): must not raise, just warn.
    client._record_truncation("https://x/api/calm-tasks/v1/tasks", 500, "max-rows")
    # (no assertion on the log; the point is it does not raise)


# ---- middleware surfaces the alert to the agent --------------------------

class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResult:
    def __init__(self, blocks):
        self.content = blocks


def test_middleware_prepends_alert_block_on_truncation():
    import asyncio
    from src.calm.toon_middleware import TruncationAlertMiddleware

    mw = TruncationAlertMiddleware()

    async def call_next(context):
        # Simulate a tool whose paged read hit a ceiling mid-call.
        client._record_truncation("https://x/api/calm-tasks/v1/tasks", 50_000, "max-requests")
        return _FakeResult([_FakeTextBlock('[{"id":1}]')])

    result = asyncio.run(mw.on_call_tool(context=None, call_next=call_next))
    assert len(result.content) == 2                       # alert block prepended
    assert result.content[0].text.startswith("⚠️ TRUNCATION ALERT")
    assert "tasks" in result.content[0].text
    assert result.content[1].text == '[{"id":1}]'         # original data untouched


def test_middleware_adds_nothing_without_truncation():
    import asyncio
    from src.calm.toon_middleware import TruncationAlertMiddleware

    mw = TruncationAlertMiddleware()

    async def call_next(context):
        return _FakeResult([_FakeTextBlock('[{"id":1}]')])

    result = asyncio.run(mw.on_call_tool(context=None, call_next=call_next))
    assert len(result.content) == 1                       # no spurious alert
    assert result.content[0].text == '[{"id":1}]'


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
