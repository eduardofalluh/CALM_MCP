"""Tests for task tag exposure + client-side tag-FAMILY filtering.

Unlike CALM test cases (an OData service that filters tags server-side via the
``toTagAssignments`` navigation), the calm-tasks endpoint is a BARE LIST: it
carries each task's tags as a plain inline ``tags`` list of label strings and
offers no server-side ``$filter``. So ``client.get_tasks`` surfaces those labels
as a ``Tags`` list and applies the tag-FAMILY filter client-side.

The family semantics must match the test-case filter EXACTLY (verified live on
NEBCO where ``tag="SIT"`` must return the exact "SIT" tag plus every
"SIT - <area>" sub-tag): a label matches when it equals the tag, or starts with
``"<tag> "`` or ``"<tag>-"``. The trailing space/dash stops "SIT" catching
unrelated tags that merely share the prefix (e.g. "SITE"). The match is lossless
because the task list pages to completion first (no page cap can drop a match).
"""

from unittest.mock import patch

import pytest

from src.calm import client


# A mixed task set: SIT exact, two SIT sub-tags, a prefix-only decoy that must
# NOT match ("SITE"), an untagged task, and an unrelated tag.
_TASKS = [
    {"id": "t1", "title": "Exact SIT", "tags": ["SIT"]},
    {"id": "t2", "title": "SIT Finance", "tags": ["SIT - Finance"]},
    {"id": "t3", "title": "SIT dash", "tags": ["SIT-POS", "Other"]},
    {"id": "t4", "title": "Decoy", "tags": ["SITE survey"]},
    {"id": "t5", "title": "No tags"},
    {"id": "t6", "title": "Unrelated", "tags": ["OCM"]},
]


def _run(**kwargs):
    with patch("src.calm.client._get", lambda url, token: _TASKS):
        return client.get_tasks("proj", "tok", "https://x.alm.cloud.sap", **kwargs)


def test_tags_exposed_in_formatter():
    rows = _run()
    by_id = {r["ID"]: r for r in rows}
    assert by_id["t1"]["Tags"] == ["SIT"]
    assert by_id["t3"]["Tags"] == ["SIT-POS", "Other"]
    # Untagged task gets an empty list, never None/KeyError.
    assert by_id["t5"]["Tags"] == []


def test_no_tag_returns_everything():
    rows = _run()
    assert len(rows) == len(_TASKS)


def test_tag_filter_matches_whole_family():
    rows = _run(tag="SIT")
    ids = {r["ID"] for r in rows}
    # Exact + both sub-tag forms, but NOT the "SITE" decoy and NOT the untagged.
    assert ids == {"t1", "t2", "t3"}


def test_tag_filter_is_case_sensitive():
    # Mirrors the server-side test-case filter, which is case-sensitive.
    assert _run(tag="sit") == []


def test_tag_filter_exact_only_when_no_family():
    rows = _run(tag="OCM")
    assert {r["ID"] for r in rows} == {"t6"}


def test_unknown_tag_returns_empty():
    assert _run(tag="DOES-NOT-EXIST") == []


@pytest.mark.parametrize(
    "tags,tag,expected",
    [
        (["SIT"], "SIT", True),
        (["SIT - Finance"], "SIT", True),
        (["SIT-POS"], "SIT", True),
        (["SITE"], "SIT", False),            # prefix without space/dash: no match
        (["SITUATION"], "SIT", False),
        (["sit"], "SIT", False),             # case-sensitive
        ([], "SIT", False),
        (None, "SIT", False),
        (["Other", "SIT"], "SIT", True),     # match anywhere in the list
        ([123, "SIT"], "SIT", True),         # non-str labels skipped safely
        ([123], "SIT", False),
    ],
)
def test_tag_in_family_helper(tags, tag, expected):
    assert client._tag_in_family(tags, tag) is expected


def test_tag_and_type_filter_combine():
    tasks = [
        {"id": "a", "type": "CALMREQU", "tags": ["SIT"]},
        {"id": "b", "type": "CALMTASK", "tags": ["SIT"]},
        {"id": "c", "type": "CALMREQU", "tags": ["OCM"]},
    ]
    with patch("src.calm.client._get", lambda url, token: tasks):
        rows = client.get_tasks(
            "proj", "tok", "https://x.alm.cloud.sap",
            task_type="Requirement", tag="SIT",
        )
    assert {r["ID"] for r in rows} == {"a"}
