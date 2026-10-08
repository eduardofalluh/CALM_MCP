"""Tests that formatted CALM tasks expose the FRICEF code and the parent link.

FRICEF/RICEFW/FS codes are stored in a CALM task's ``externalId`` (verified live:
values like ``FTS-DEV-01``), and a task's link to its parent work item (e.g. a
requirement) is ``parentId``. Both were previously dropped by ``_format_task``;
these tests pin them so the agent can read FRICEF IDs and resolve requirement
<-> task hierarchies.
"""

from src.calm import client


def _raw(**overrides):
    base = {
        "id": "t-child",
        "displayId": "3-4000",
        "externalId": "FTS-DEV-01",
        "title": "FTS-DEV-01: Develop RICEF",
        "type": "CALMTASK",
        "status": "CIPTKCOMP",
        "parentId": "t-parent",
    }
    base.update(overrides)
    return base


def test_fricef_external_id_surfaced():
    out = client._format_task(_raw())
    assert out["External ID (FRICEF)"] == "FTS-DEV-01"


def test_parent_id_surfaced():
    out = client._format_task(_raw())
    assert out["Parent ID"] == "t-parent"


def test_null_values_pass_through():
    out = client._format_task(_raw(externalId=None, parentId=None))
    assert out["External ID (FRICEF)"] is None
    assert out["Parent ID"] is None


def test_display_id_falls_back_to_external_id():
    out = client._format_task(_raw(displayId=None))
    assert out["Display ID"] == "FTS-DEV-01"
