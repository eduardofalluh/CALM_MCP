"""Documents, Features and automated test cases through the schema-driven OData layer.

SAP Cloud ALM's Documents (calm-documents), Features (calm-features) and Test
Management (calm-testmanagement) are OData v4 CAP services. The MCP reads each
service's $metadata from the tenant, so rows, filters and write payloads use
SAP's real property names and a misspelt field is refused instead of ignored.

The Documents/Features schemas below are CAP-style fakes; the AutomatedTestCases
type is the one read live from a tenant's calm-testmanagement $metadata.
Everything runs against mocks — no network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import client, http_retry, odata_service  # noqa: E402

BASE = "https://x.alm.cloud.sap"
DOC_UUID = "0b1c2d3e-4f50-4a61-8b72-9c83d4e5f601"
FEAT_UUID = "1c2d3e4f-5061-4b72-8c83-9d94e5f60712"

CSDL = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
 <edmx:DataServices><Schema Namespace="api.v1.Svc" xmlns="http://docs.oasis-open.org/odata/ns/edm">
  <EntityContainer Name="EntityContainer">
   <EntitySet Name="Documents" EntityType="api.v1.Svc.Documents">
    <NavigationPropertyBinding Path="toURLReferences" Target="URLReferences"/>
   </EntitySet>
   <EntitySet Name="URLReferences" EntityType="api.v1.Svc.URLReferences"/>
   <EntitySet Name="Features" EntityType="api.v1.Svc.Features"/>
   <EntitySet Name="AutomatedTestCases" EntityType="api.v1.Svc.AutomatedTestCases"/>
  </EntityContainer>
  <EntityType Name="Documents">
   <Key><PropertyRef Name="uuid"/></Key>
   <Property Name="uuid" Type="Edm.Guid" Nullable="false"/>
   <Property Name="displayId" Type="Edm.String"/>
   <Property Name="title" Type="Edm.String" Nullable="false"/>
   <Property Name="content" Type="Edm.String"/>
   <Property Name="projectId" Type="Edm.Guid"/>
   <Property Name="statusCode" Type="Edm.String"/>
   <Property Name="typeCode" Type="Edm.String"/>
   <Property Name="version" Type="Edm.Int32"/>
   <Property Name="isTemplate" Type="Edm.Boolean"/>
   <Property Name="createdAt" Type="Edm.DateTimeOffset"/>
   <Property Name="modifiedAt" Type="Edm.DateTimeOffset"/>
   <NavigationProperty Name="toURLReferences" Type="Collection(api.v1.Svc.URLReferences)"/>
  </EntityType>
  <EntityType Name="URLReferences">
   <Key><PropertyRef Name="uuid"/></Key>
   <Property Name="uuid" Type="Edm.Guid" Nullable="false"/>
   <Property Name="name" Type="Edm.String"/>
   <Property Name="url" Type="Edm.String"/>
   <Property Name="parent_ID" Type="Edm.Guid"/>
  </EntityType>
  <EntityType Name="Features">
   <Key><PropertyRef Name="uuid"/></Key>
   <Property Name="uuid" Type="Edm.Guid" Nullable="false"/>
   <Property Name="displayId" Type="Edm.String"/>
   <Property Name="title" Type="Edm.String"/>
   <Property Name="description" Type="Edm.String"/>
   <Property Name="projectId" Type="Edm.Guid"/>
   <Property Name="statusCode" Type="Edm.String"/>
   <Property Name="priorityCode" Type="Edm.Int32"/>
   <Property Name="responsibleId" Type="Edm.Guid"/>
   <Property Name="externalId" Type="Edm.String"/>
   <Property Name="modifiedAt" Type="Edm.DateTimeOffset"/>
  </EntityType>
  <EntityType Name="AutomatedTestCases">
   <Key><PropertyRef Name="uuid"/></Key>
   <Property Name="uuid" Type="Edm.Guid" Nullable="false"/>
   <Property Name="title" Type="Edm.String"/>
   <Property Name="projectId" Type="Edm.Guid"/>
   <Property Name="scopeId" Type="Edm.Guid"/>
   <Property Name="solutionProcessId" Type="Edm.Guid"/>
   <Property Name="contentPackageId" Type="Edm.Guid"/>
   <Property Name="isPrepared" Type="Edm.Boolean"/>
   <Property Name="priorityCode" Type="Edm.Int32"/>
   <Property Name="createdAt" Type="Edm.DateTimeOffset"/>
   <Property Name="modifiedAt" Type="Edm.DateTimeOffset"/>
   <Property Name="datavariantId" Type="Edm.String"/>
   <Property Name="datavariantName" Type="Edm.String"/>
   <Property Name="displayId" Type="Edm.String"/>
   <NavigationProperty Name="toTagAssignments" Type="Collection(api.v1.Svc.TagAssignments)"/>
  </EntityType>
 </Schema></edmx:DataServices>
</edmx:Edmx>"""

SETS = odata_service.parse_metadata(CSDL)
PROJECT = "2d3e4f50-6172-4c83-9d94-aea5f6071823"


@pytest.fixture
def with_schema(monkeypatch):
    """Every OData service answers with the fake schema above."""
    monkeypatch.setattr(odata_service, "schema", lambda service, token, base_url=None: SETS)


class Ctx:
    """No request_context — credentials come from env."""


@pytest.fixture
def calm(monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", "tok")
    monkeypatch.setenv("CALM_BASE_URL", BASE)
    monkeypatch.setenv("CALM_ENABLE_WRITES", "true")
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("t")
    register(mcp)
    return asyncio.run(mcp.get_tool("calm_resource")).fn


def _doc(i=1, **kw):
    d = {"@odata.etag": f'W/"{i}"', "uuid": DOC_UUID if i == 1 else f"0b1c2d3e-4f50-4a61-8b72-9c83d4e5f6{i:02d}",
         "displayId": f"7-{100 + i}", "title": f"Solution design {i}", "content": "<p>Long <b>text</b></p>",
         "projectId": PROJECT, "statusCode": "IN_PROGRESS", "typeCode": "SDD", "version": 1,
         "createdAt": "2026-10-23T10:00:00.000Z", "modifiedAt": "2026-10-23T11:00:00.000Z"}
    d.update(kw)
    return d


# --------------------------------------------------------------------------- #
# Schema parsing and labels
# --------------------------------------------------------------------------- #

def test_parse_metadata_reads_sets_keys_props_and_navs():
    docs = SETS["Documents"]
    assert docs["key"] == ["uuid"] and docs["type"] == "Documents"
    assert docs["props"]["title"] == {"type": "Edm.String", "nullable": False}
    assert docs["navs"]["toURLReferences"]["many"] is True
    assert set(SETS) == {"Documents", "URLReferences", "Features", "AutomatedTestCases"}


@pytest.mark.parametrize("prop, expected", [
    ("uuid", "ID"), ("displayId", "Display ID"), ("statusCode", "Status Code"),
    ("parent_ID", "Parent ID"), ("parentTestCase_ID", "Parent Test Case ID"),
    ("toURLReferences", "URL References"), ("isPrepared", "Is Prepared"),
    ("createdAt", "Created"), ("modifiedAt", "Last Changed"), ("datavariantName", "Datavariant Name"),
])
def test_labels_follow_one_fixed_rule(prop, expected):
    assert odata_service.label(prop) == expected


def test_format_row_plain_text_nested_navs_and_compact_lists():
    item = _doc(toURLReferences=[{"uuid": "r1", "name": "Spec", "url": "https://x/spec"}])
    full = odata_service.format_row(item)
    assert full["Content"] == "Long text"
    assert full["URL References"] == [{"ID": "r1", "Name": "Spec", "URL": "https://x/spec"}]
    assert "@odata.etag" not in str(full)
    compact = odata_service.format_row(item, long_text=False)
    assert "Content" not in compact and compact["Title"] == "Solution design 1"


def test_schema_errors_are_schema_unavailable(monkeypatch):
    monkeypatch.undo()  # use the real schema() for this test, with HTTP mocked

    class R:
        status_code, text = 403, '{"message":"Forbidden"}'
    odata_service._SCHEMAS.clear()
    with patch.object(odata_service.requests, "get", return_value=R()), \
         pytest.raises(odata_service.SchemaUnavailable, match="HTTP 403"):
        odata_service.schema("calm-documents", "tok", BASE)


def test_schema_is_cached_and_bounded(monkeypatch):
    monkeypatch.undo()

    class R:
        status_code, text = 200, CSDL
    odata_service._SCHEMAS.clear()
    try:
        with patch.object(odata_service.requests, "get", return_value=R()) as g:
            odata_service.schema("calm-documents", "tok", BASE)
            odata_service.schema("calm-documents", "tok", BASE)
            assert g.call_count == 1
            for i in range(odata_service._SCHEMAS_MAX + 5):
                odata_service.schema("calm-documents", "tok", f"https://t{i}.example.com")
        assert len(odata_service._SCHEMAS) == odata_service._SCHEMAS_MAX
    finally:
        odata_service._SCHEMAS.clear()


def test_oversized_schema_is_refused(monkeypatch):
    monkeypatch.undo()

    class R:
        status_code, text = 200, "x" * (odata_service._METADATA_MAX_BYTES + 1)
    odata_service._SCHEMAS.clear()
    with patch.object(odata_service.requests, "get", return_value=R()), \
         pytest.raises(odata_service.SchemaUnavailable, match="unexpectedly large"):
        odata_service.schema("calm-documents", "tok", BASE)


# --------------------------------------------------------------------------- #
# Filters: escaped literals, never spliced raw
# --------------------------------------------------------------------------- #

def test_string_literals_double_quotes(with_schema):
    es = SETS["Documents"]
    assert odata_service._filter(es, {"title": "O'Neil plan"}) == "title eq 'O''Neil plan'"


@pytest.mark.parametrize("field, value", [
    ("projectId", "x' or 1 eq 1 or 'a"), ("version", "1 or true"), ("isTemplate", "maybe"),
])
def test_typed_literals_reject_injection(with_schema, field, value):
    with pytest.raises(ValueError):
        odata_service._filter(SETS["Documents"], {field: value})


def test_list_filters_server_side_with_aliases_and_multiple_values(with_schema):
    with patch.object(client, "_get_all", return_value=[_doc()]) as ga:
        rows = odata_service.list_rows(odata_service.DOCUMENTS, "tok", BASE, project_id=PROJECT,
                                       data={"status": ["IN_PROGRESS", "IN_REVIEW"], "type": "SDD"})
    url = ga.call_args.args[0]
    assert url.startswith(f"{BASE}/api/calm-documents/v1/Documents?$filter=")
    from urllib.parse import unquote
    assert unquote(url.split("$filter=")[1]) == (
        f"projectId eq {PROJECT} and (statusCode eq 'IN_PROGRESS' or statusCode eq 'IN_REVIEW') "
        "and typeCode eq 'SDD'")
    assert rows[0]["Display ID"] == "7-101" and "Content" not in rows[0]


def test_unknown_list_key_is_refused_with_real_fields(with_schema):
    with patch.object(client, "_get_all") as ga, pytest.raises(ValueError) as err:
        odata_service.list_rows(odata_service.DOCUMENTS, "tok", BASE, data={"owner_name": "x"})
    ga.assert_not_called()
    assert "owner_name" in str(err.value) and "statusCode" in str(err.value)


def test_list_search_top_and_fields(with_schema):
    docs = [_doc(i, title=t) for i, t in enumerate(
        ["Solution design finance", "Cutover plan", "Finance solution design v2", "Test strategy"], start=1)]
    with patch.object(client, "_get_all", return_value=docs):
        out = odata_service.list_rows(odata_service.DOCUMENTS, "tok", BASE, project_id=PROJECT,
                                      data={"search": "solution design finance", "fields": ["Title"]})
    assert out["Total Matching"] == 2 and out["Search"] == "solution design finance"
    assert out["Documents"][0] == {"ID": docs[0]["uuid"], "Title": "Solution design finance"}
    with patch.object(client, "_get_all", return_value=docs), pytest.raises(ValueError, match="unknown field"):
        odata_service.list_rows(odata_service.DOCUMENTS, "tok", BASE, data={"fields": ["Owner Name"]})


# --------------------------------------------------------------------------- #
# Get / create / update / delete
# --------------------------------------------------------------------------- #

def test_get_by_uuid_expands_every_navigation(with_schema):
    with patch.object(client, "_get_with_meta", return_value=(_doc(), 'W/"1"')) as gm:
        data, etag = odata_service.get_raw(*odata_service.DOCUMENTS, "tok", DOC_UUID, BASE)
    assert gm.call_args.args[0] == f"{BASE}/api/calm-documents/v1/Documents/{DOC_UUID}?$expand=toURLReferences"
    assert etag == 'W/"1"' and data["title"] == "Solution design 1"


def test_get_by_display_id_filters_then_reads_by_key(with_schema):
    with patch.object(client, "_get_all", return_value=[_doc()]) as ga, \
         patch.object(client, "_get_with_meta", return_value=(_doc(), None)):
        data, etag = odata_service.get_raw(*odata_service.DOCUMENTS, "tok", "7-101", BASE, project_id=PROJECT)
    from urllib.parse import unquote
    assert unquote(ga.call_args.args[0]).endswith(f"displayId eq '7-101' and projectId eq {PROJECT}")
    assert etag == 'W/"1"'  # from @odata.etag when no ETag header


def test_display_id_not_found_and_ambiguous(with_schema):
    with patch.object(client, "_get_all", return_value=[]), pytest.raises(ValueError, match="No document"):
        odata_service.resolve_uuid(*odata_service.DOCUMENTS, "tok", "7-999", BASE)
    twins = [_doc(1), _doc(2, displayId="7-101")]
    with patch.object(client, "_get_all", return_value=twins), pytest.raises(ValueError, match="2 documents"):
        odata_service.resolve_uuid(*odata_service.DOCUMENTS, "tok", "7-101", BASE)
    # A filter the service ignored can't pick the wrong item: IDs are re-checked.
    with patch.object(client, "_get_all", return_value=[_doc(2), _doc(1)]):
        assert odata_service.resolve_uuid(*odata_service.DOCUMENTS, "tok", "7-101", BASE) == DOC_UUID


def test_body_for_maps_names_and_refuses_unknown(with_schema):
    es = SETS["Documents"]
    assert odata_service.body_for(es, {"title": "A", "status": "IN_REVIEW", "type_code": "SDD",
                                       "project_id": PROJECT}) == {
        "title": "A", "statusCode": "IN_REVIEW", "typeCode": "SDD", "projectId": PROJECT}
    with pytest.raises(ValueError, match="no writable field") as err:
        odata_service.body_for(es, {"title": "A", "modifiedAt": "x", "colour": "red"})
    assert "modifiedAt" in str(err.value) and "colour" in str(err.value)


def test_create_dropped_but_created_is_confirmed(with_schema):
    with patch.object(client.requests, "request", side_effect=_dropped()), \
         patch.object(client, "_get_all", return_value=[_doc(createdAt=_now_iso())]), \
         patch.object(http_retry, "_sleep", lambda s: None):
        raw, note = odata_service.create(*odata_service.DOCUMENTS, "tok",
                                         {"title": "Solution design 1", "projectId": PROJECT}, BASE)
    assert raw["uuid"] == DOC_UUID and "created" in note


def test_create_dropped_and_not_found_keeps_the_doubt(with_schema):
    with patch.object(client.requests, "request", side_effect=_dropped()), \
         patch.object(client, "_get_all", return_value=[]), \
         patch.object(http_retry, "_sleep", lambda s: None), \
         pytest.raises(http_retry.WriteUnconfirmed):
        odata_service.create(*odata_service.DOCUMENTS, "tok", {"title": "X", "projectId": PROJECT}, BASE)


def test_update_sends_the_etag_and_returns_the_fresh_entity(with_schema):
    reads = iter([(_doc(), 'W/"7"'), (_doc(statusCode="IN_REVIEW"), 'W/"8"')])
    with patch.object(client, "_get_with_meta", side_effect=lambda *a: next(reads)), \
         patch.object(client, "_write", return_value={}) as w:
        out = odata_service.update(*odata_service.DOCUMENTS, "tok", DOC_UUID, {"statusCode": "IN_REVIEW"}, BASE)
    assert w.call_args.args[:2] == ("PATCH", f"{BASE}/api/calm-documents/v1/Documents/{DOC_UUID}")
    assert w.call_args.kwargs["if_match"] == 'W/"7"'
    assert out["statusCode"] == "IN_REVIEW"


def test_update_needs_fields_and_delete_sends_etag(with_schema):
    with pytest.raises(ValueError, match="No fields"):
        odata_service.update(*odata_service.DOCUMENTS, "tok", DOC_UUID, {}, BASE)
    with patch.object(client, "_get_with_meta", return_value=(_doc(), 'W/"3"')), \
         patch.object(client, "_delete") as dl:
        assert odata_service.delete(*odata_service.DOCUMENTS, "tok", DOC_UUID, BASE) == {"deleted": DOC_UUID}
    assert dl.call_args.kwargs["if_match"] == 'W/"3"'


def test_key_url_rejects_non_uuid(with_schema):
    with pytest.raises(ValueError):
        odata_service._key_url("calm-documents", SETS["Documents"], BASE, "../projects")


# --------------------------------------------------------------------------- #
# calm_resource: documents
# --------------------------------------------------------------------------- #

def test_documents_without_scope_read_is_structured_write_is_an_error(calm):
    # Default test schema = unavailable (see conftest).
    out = calm(Ctx(), resource="documents", operation="list", project_id=PROJECT)
    assert out["status"] == "unavailable" and out["missing_scopes"] == ["calm-api.documents.read"]
    with pytest.raises(ValueError) as err:
        calm(Ctx(), resource="documents", operation="create", project_id=PROJECT, data={"title": "A"})
    assert "calm-api.documents.write" in str(err.value) and "calm-api.documents.read" in str(err.value)
    with pytest.raises(ValueError, match="calm-api.documents.delete"):
        calm(Ctx(), resource="documents", operation="delete", resource_id=DOC_UUID)


def test_documents_list_get_through_calm_resource(calm, with_schema):
    with patch.object(client, "_get_all", return_value=[_doc()]):
        rows = calm(Ctx(), resource="documents", operation="list", project_id=PROJECT)
    assert rows[0]["Title"] == "Solution design 1" and rows[0]["Status Code"] == "IN_PROGRESS"
    with patch.object(client, "_get_with_meta", return_value=(_doc(), None)):
        one = calm(Ctx(), resource="documents", operation="get", resource_id=DOC_UUID)
    assert one["Content"] == "Long text" and one["Version"] == 1


def test_document_create_fills_project_and_requires_title(calm, with_schema):
    with patch.object(client, "_write", return_value=_doc()) as w:
        out = calm(Ctx(), resource="documents", operation="create", project_id=PROJECT,
                   data={"title": "Solution design 1", "type": "SDD", "content": "<p>Text</p>"})
    assert w.call_args.args[3] == {"title": "Solution design 1", "typeCode": "SDD",
                                   "content": "<p>Text</p>", "projectId": PROJECT}
    assert out["ID"] == DOC_UUID
    with pytest.raises(ValueError, match="title"):
        calm(Ctx(), resource="documents", operation="create", project_id=PROJECT, data={"type": "SDD"})
    with pytest.raises(ValueError, match="project_id is required"):
        calm(Ctx(), resource="documents", operation="create", data={"title": "A"})


def test_document_writes_respect_the_write_switch(calm, with_schema, monkeypatch):
    monkeypatch.setenv("CALM_ENABLE_WRITES", "false")
    with patch.object(client, "_write") as w, pytest.raises(Exception, match="(?i)writ"):
        calm(Ctx(), resource="documents", operation="create", project_id=PROJECT, data={"title": "A"})
    w.assert_not_called()


def test_document_update_and_delete_by_display_id(calm, with_schema):
    with patch.object(client, "_get_all", return_value=[_doc()]), \
         patch.object(client, "_get_with_meta", return_value=(_doc(), 'W/"1"')), \
         patch.object(client, "_write", return_value=_doc(statusCode="RELEASED")) as w:
        out = calm(Ctx(), resource="documents", operation="update", project_id=PROJECT,
                   resource_id="7-101", data={"status": "RELEASED"})
    assert w.call_args.args[3] == {"statusCode": "RELEASED"} and out["Status Code"] == "RELEASED"
    with patch.object(client, "_get_with_meta", return_value=(_doc(), 'W/"1"')), \
         patch.object(client, "_delete") as dl:
        assert calm(Ctx(), resource="documents", operation="delete", resource_id=DOC_UUID) == {"deleted": DOC_UUID}
    assert dl.called


# --------------------------------------------------------------------------- #
# Features: SAP's real fields, get / update
# --------------------------------------------------------------------------- #

def _feature(**kw):
    f = {"uuid": FEAT_UUID, "displayId": "6-42", "title": "Payroll interface", "description": "<p>Desc</p>",
         "projectId": PROJECT, "statusCode": "IN_REALIZATION", "priorityCode": 20, "externalId": "EXT-1",
         "responsibleId": "3e4f5061-7283-4d94-aea5-b6c7d8e9f001", "modifiedAt": "2026-10-23T09:00:00Z"}
    f.update(kw)
    return f


def test_feature_rows_keep_the_old_columns_from_the_real_fields(with_schema):
    with patch.object(client, "_get_all", return_value=[_feature()]) as ga:
        rows = client.get_features(PROJECT, "tok", BASE)
    assert "$filter=" in ga.call_args.args[0]  # project filtered by SAP, not after
    r = rows[0]
    assert list(r)[:6] == ["ID", "Project ID", "Name", "Description", "Status", "External ID"]
    assert (r["ID"], r["Name"], r["Status"], r["Description"]) == (FEAT_UUID, "Payroll interface",
                                                                   "IN_REALIZATION", "Desc")
    assert r["Display ID"] == "6-42" and r["Priority Code"] == 20 and "Title" not in r


def test_feature_rows_still_read_the_old_field_names():
    with patch.object(client, "_get_all", return_value=[{"id": "F1", "projectId": "P1", "name": "A", "status": "OPEN"}]):
        r = client.get_features("P1", "tok", BASE)[0]
    assert (r["ID"], r["Name"], r["Status"]) == ("F1", "A", "OPEN")


def test_feature_create_uses_the_schema_name_field(with_schema):
    with patch.object(client, "_write", return_value=_feature()) as w:
        client.create_feature("tok", PROJECT, "Payroll interface", description="d",
                              extra_fields={"priority_code": 20}, base_url=BASE)
    assert w.call_args.args[3] == {"projectId": PROJECT, "title": "Payroll interface",
                                   "description": "d", "priorityCode": 20}


def test_feature_get_update_and_delete_through_calm_resource(calm, with_schema):
    with patch.object(client, "_get_with_meta", return_value=(_feature(), 'W/"4"')):
        one = calm(Ctx(), resource="features", operation="get", resource_id=FEAT_UUID)
    assert one["Name"] == "Payroll interface" and one["Description"] == "Desc"
    with patch.object(client, "_get_with_meta", return_value=(_feature(), 'W/"4"')), \
         patch.object(client, "_write", return_value=_feature(statusCode="DONE")) as w:
        out = calm(Ctx(), resource="features", operation="update", resource_id=FEAT_UUID,
                   data={"status": "DONE", "name": "Payroll interface v2"})
    assert w.call_args.args[3] == {"statusCode": "DONE", "title": "Payroll interface v2"}
    assert w.call_args.kwargs["if_match"] == 'W/"4"' and out["Status"] == "DONE"
    with pytest.raises(ValueError, match="no delete"):
        calm(Ctx(), resource="features", operation="delete", resource_id=FEAT_UUID)


def test_feature_update_without_scope_names_both_scopes(calm):
    with pytest.raises(ValueError) as err:
        calm(Ctx(), resource="features", operation="update", resource_id=FEAT_UUID, data={"status": "DONE"})
    assert "calm-api.features.write" in str(err.value) and "calm-api.features.read" in str(err.value)


# --------------------------------------------------------------------------- #
# Automated test cases, linked tasks on manual test cases
# --------------------------------------------------------------------------- #

def test_automated_test_cases_list_and_get(calm, with_schema):
    atc = {"uuid": "4f506172-8394-4ea5-b6c7-d8e9f0011223", "title": "Order to cash smoke", "projectId": PROJECT,
           "priorityCode": 20, "isPrepared": True, "datavariantName": "DE plant", "displayId": "8-2-17",
           "modifiedAt": "2026-10-20T08:00:00Z"}
    with patch.object(client, "_get_all", return_value=[atc]) as ga:
        rows = calm(Ctx(), resource="automated_test_cases", operation="list", project_id=PROJECT)
    assert "/api/calm-testmanagement/v1/AutomatedTestCases?$filter=" in ga.call_args.args[0]
    assert rows[0]["Priority"] == "High" and rows[0]["Datavariant Name"] == "DE plant"
    with patch.object(client, "_get_with_meta", return_value=(atc, None)):
        one = calm(Ctx(), resource="automated_test_cases", operation="get", resource_id=atc["uuid"])
    assert one["Display ID"] == "8-2-17"
    with pytest.raises(ValueError, match="read-only"):
        calm(Ctx(), resource="automated_test_cases", operation="create", data={"title": "x"})


def test_automated_test_cases_without_scope_name_testcases_read(calm):
    out = calm(Ctx(), resource="automated_test_cases", operation="list", project_id=PROJECT)
    assert out["missing_scopes"] == ["calm-api.testcases.read"]


def test_manual_test_case_detail_lists_linked_tasks():
    item = {"uuid": "tc", "title": "T", "toActivities": [], "toTaskAssignments": [
        {"uuid": "a1", "taskId": "t-1", "taskDisplayId": "3-55", "type": "CALMREQU"}]}
    out = client._format_test_case_detail(item)
    assert out["Linked Tasks"] == [{"Task ID": "t-1", "Task Display ID": "3-55", "Type": "CALMREQU"}]
    assert list(out)[-1] == "Linked Tasks"  # appended after every existing field


# --------------------------------------------------------------------------- #

def _dropped():
    import http.client

    import requests
    from urllib3.exceptions import ProtocolError
    return requests.exceptions.ConnectionError(ProtocolError(
        "Connection aborted.", http.client.RemoteDisconnected("Remote end closed connection without response")))


def _now_iso():
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
