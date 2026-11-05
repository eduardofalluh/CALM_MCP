"""Loading a document (a Word file or text) into SAP Cloud ALM as a document,
linked wherever the user wants (2026-11-04).

Covers the body conversion (Word / Markdown / HTML / text), the guards on
reading files, and the documents create / update flow against a synthetic
Documents schema: type and status by name, links to requirements / tasks,
solution processes and URLs, the attached original, and that nothing a link
or the attachment can't do is dropped silently. The schema mirrors the live
tenant's (2026-11-05); the live run is ~/calm_mcp_live_tests/live_document_full.py.
"""

from __future__ import annotations

import asyncio
import base64
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.calm import doc_content, odata_service  # noqa: E402

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _docx(body: str) -> bytes:
    styles = (f'<w:styles {W}><w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
              f'<w:style w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>'
              f'<w:style w:styleId="Title"><w:name w:val="Title"/></w:style></w:styles>')
    numbering = (f'<w:numbering {W}>'
                 '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl>'
                 '<w:lvl w:ilvl="1"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
                 '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>'
                 '</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
                 '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>')
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            'Target="https://help.sap.com/docs" TargetMode="External"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
        z.writestr("word/styles.xml", styles)
        z.writestr("word/numbering.xml", numbering)
        z.writestr("word/_rels/document.xml.rels", rels)
    return buf.getvalue()


def _p(text, style=None, num=None, bold=False, mono=False):
    ppr = ""
    if style or num:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + (
            f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>' if num else "") + "</w:pPr>"
    rpr = ("<w:rPr>" + ("<w:b/>" if bold else "")
           + ('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>' if mono else "") + "</w:rPr>")
    return f"<w:p>{ppr}<w:r>{rpr}<w:t>{text}</w:t></w:r></w:p>"


GUIDE = _docx(
    _p("Enable SAP Cloud ALM API Connectivity", style="Title")
    + _p("1. Purpose", style="Heading1")
    + _p("This guide explains how to &lt;expose&gt; the API.")
    + _p("Access to the BTP cockpit", num=("1", "0"))
    + _p("Administrator rights", num=("1", "1"))
    + _p("Open the subaccount", num=("2", "0"))
    + _p("Create the instance", num=("2", "0"))
    + '<w:p><w:r><w:drawing/></w:r></w:p>'
    + _p('{', mono=True) + _p('  "xsappname": "client-cloudalm-agent-api"', mono=True) + _p('}', mono=True)
    + _p("Important", bold=True)
    + '<w:p><w:hyperlink r:id="rId9"><w:r><w:t>SAP Help</w:t></w:r></w:hyperlink></w:p>'
    + '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Scope</w:t></w:r></w:p></w:tc>'
      '<w:tc><w:p><w:r><w:t>Grants</w:t></w:r></w:p></w:tc></w:tr>'
      '<w:tr><w:tc><w:p><w:r><w:t>documents.write</w:t></w:r></w:p></w:tc>'
      '<w:tc><w:p><w:r><w:t>create</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    + '<w:p><w:r><w:pict/></w:r></w:p>'
)


# --------------------------------------------------------------------------- #
# Body conversion
# --------------------------------------------------------------------------- #

def test_word_file_keeps_structure_and_counts_pictures():
    out, pictures = doc_content.docx_html(GUIDE)
    assert "<h1>Enable SAP Cloud ALM API Connectivity</h1>" in out
    assert "<h1>1. Purpose</h1>" in out
    assert "how to &lt;expose&gt; the API" in out  # text is escaped, never markup
    assert "<ul>\n<li>Access to the BTP cockpit</li>\n<ul>\n<li>Administrator rights</li>\n</ul>\n</ul>" in out
    assert "<ol>\n<li>Open the subaccount</li>\n<li>Create the instance</li>\n</ol>" in out
    assert '<pre>{\n  "xsappname": "client-cloudalm-agent-api"\n}</pre>' in out
    assert "<strong>Important</strong>" in out
    assert '<a href="https://help.sap.com/docs">SAP Help</a>' in out
    assert "<table><tr><td>Scope</td><td>Grants</td></tr><tr><td>documents.write</td><td>create</td></tr></table>" in out
    assert pictures == 2 and "[Picture 1]" in out and "[Picture 2]" in out


def test_markdown_text_becomes_rich_text():
    md = ("# 8. Create API Instance\n\nUpdate the following:\n\n```\n{\"xs-security\": {}}\n```\n\n"
          "- one\n  - nested\n1. first\n\n| Scope | Use |\n|---|---|\n| read | list |\n\n"
          "See [help](https://help.sap.com) and [bad](javascript:alert(1)), **bold** and *it*.")
    out = doc_content.markdown_html(md)
    assert "<h1>8. Create API Instance</h1>" in out and '<pre>{"xs-security": {}}</pre>' in out
    assert "<ul>\n<li>one</li>\n<ul>\n<li>nested</li>\n</ul>\n</ul>\n<ol>\n<li>first</li>\n</ol>" in out
    assert "<table><tr><td>Scope</td><td>Use</td></tr><tr><td>read</td><td>list</td></tr></table>" in out
    assert '<a href="https://help.sap.com">help</a>' in out
    assert "[bad](javascript:alert(1))" in out  # an unsafe link stays plain text
    assert "<strong>bold</strong>" in out and "<em>it</em>" in out


def test_html_is_cleaned():
    out = doc_content.sanitize('<p onclick="x()">Hi</p><script>bad()</script><a href="javascript:x">l</a>')
    assert out == '<p>Hi</p><a href="#">l</a>'


def test_exactly_one_source():
    with pytest.raises(ValueError, match="exactly one"):
        doc_content.body()
    with pytest.raises(ValueError, match="exactly one"):
        doc_content.body(content="x", file_base64="eA==")


def test_files_are_read_only_where_safe(tmp_path, monkeypatch):
    spec = tmp_path / "spec.docx"
    spec.write_bytes(GUIDE)
    monkeypatch.setattr(doc_content, "LOCAL_FILES", False)  # the shared HTTP server
    with pytest.raises(ValueError, match="own machine"):
        doc_content.body(file_path=str(spec))
    monkeypatch.setattr(doc_content, "LOCAL_FILES", True)   # a local (stdio) MCP
    out, report, original = doc_content.body(file_path=str(spec))
    assert "<h1>1. Purpose</h1>" in out and report["Pictures Not In Text"] == 2
    assert original == ("spec.docx", GUIDE)
    secret = tmp_path / ".env"
    secret.write_text("CALM_CLIENT_SECRET=x")
    (tmp_path / "notes.md").symlink_to(secret)
    with pytest.raises(ValueError, match="not a supported file"):
        doc_content.body(file_path=str(tmp_path / "notes.md"))  # a link can't smuggle another file in
    with pytest.raises(ValueError, match="not a supported file"):
        doc_content.body(file_path=str(secret))


def test_base64_files_and_their_limits(monkeypatch):
    out, report, original = doc_content.body(file_base64=base64.b64encode(GUIDE).decode(), file_name="g.docx")
    assert "Purpose" in out and original[0] == "g.docx"
    with pytest.raises(ValueError, match="not valid base64"):
        doc_content.body(file_base64="%%%")
    monkeypatch.setattr(doc_content, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="limit"):
        doc_content.body(file_base64=base64.b64encode(GUIDE).decode(), file_name="g.docx")


def test_a_fake_word_file_is_refused():
    with pytest.raises(ValueError, match="not a valid Word"):
        doc_content.docx_html(b"not a zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "b">]><x/>')
    with pytest.raises(ValueError, match="DOCTYPE"):
        doc_content.docx_html(buf.getvalue())


# --------------------------------------------------------------------------- #
# documents create / update through calm_resource
# --------------------------------------------------------------------------- #

class Ctx:
    """No request_context — credentials come from env."""


DOC_UUID = "0b1c2d3e-4f50-4a61-8b72-9c83d4e5f601"
TASK_UUID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
CSDL = (
    '<edmx:Edmx Version="4.0"><edmx:DataServices><Schema Namespace="S"><EntityContainer Name="C">'
    '<EntitySet Name="Documents" EntityType="S.Documents"/>'
    '<EntitySet Name="DocumentTypes" EntityType="S.DocumentTypes"/>'
    '<EntitySet Name="DocumentStatus" EntityType="S.DocumentStatus"/></EntityContainer>'
    '<EntityType Name="Documents"><Key><PropertyRef Name="uuid"/></Key>'
    '<Property Name="uuid" Type="Edm.Guid"/><Property Name="displayId" Type="Edm.String"/>'
    '<Property Name="title" Type="Edm.String"/><Property Name="content" Type="Edm.String"/>'
    '<Property Name="projectId" Type="Edm.String"/><Property Name="documentTypeCode" Type="Edm.String"/>'
    '<Property Name="statusCode" Type="Edm.Int32"/>'
    '<NavigationProperty Name="toTaskAssignments" Type="Collection(S.TaskAssignments)"/>'
    '<NavigationProperty Name="toSolutionProcessAssignments" Type="Collection(S.SolutionProcessAssignments)"/>'
    '<NavigationProperty Name="toURLReferences" Type="Collection(S.URLReferences)"/></EntityType>'
    '<EntityType Name="TaskAssignments"><Key><PropertyRef Name="uuid"/></Key>'
    '<Property Name="uuid" Type="Edm.Guid"/><Property Name="parent_uuid" Type="Edm.Guid"/>'
    '<Property Name="id" Type="Edm.String"/><Property Name="type" Type="Edm.String"/></EntityType>'
    '<EntityType Name="SolutionProcessAssignments"><Key><PropertyRef Name="uuid"/></Key>'
    '<Property Name="uuid" Type="Edm.Guid"/><Property Name="solutionProcessId" Type="Edm.String"/></EntityType>'
    '<EntityType Name="URLReferences"><Key><PropertyRef Name="uuid"/></Key>'
    '<Property Name="uuid" Type="Edm.Guid"/><Property Name="url" Type="Edm.String"/>'
    '<Property Name="name" Type="Edm.String"/></EntityType>'
    '<EntityType Name="DocumentTypes"><Key><PropertyRef Name="code"/></Key>'
    '<Property Name="code" Type="Edm.String"/><Property Name="name" Type="Edm.String"/></EntityType>'
    '<EntityType Name="DocumentStatus"><Key><PropertyRef Name="code"/></Key>'
    '<Property Name="code" Type="Edm.Int32"/><Property Name="name" Type="Edm.String"/></EntityType>'
    '</Schema></edmx:DataServices></edmx:Edmx>'
)
# The schema and code lists as the live tenant has them (read 2026-11-05):
# FS is "Fact Sheet", a Functional Specification is FU; statuses are numbers.
CODES = {"DocumentTypes": [{"code": "FS", "name": "Fact Sheet"}, {"code": "FU", "name": "Functional Specification"},
                           {"code": "SD", "name": "Solution Design Document"}],
         "DocumentStatus": [{"code": 10, "name": "In Progress"}, {"code": 20, "name": "In Review"},
                            {"code": 30, "name": "Released"}]}


@pytest.fixture
def calm(monkeypatch):
    monkeypatch.setenv("CALM_TOKEN", "tok")
    monkeypatch.setenv("CALM_BASE_URL", "https://x.alm.cloud.sap")
    monkeypatch.setenv("CALM_ENABLE_WRITES", "true")
    monkeypatch.delenv("CALM_CLIENT_ID", raising=False)
    monkeypatch.delenv("CALM_CLIENT_SECRET", raising=False)
    from fastmcp import FastMCP

    from src.calm.tools.unified import register

    mcp = FastMCP("t")
    register(mcp)
    return asyncio.run(mcp.get_tool("calm_resource")).fn


@pytest.fixture
def sap(monkeypatch):
    """The Documents service: schema, code lists, and every write captured."""
    sets = odata_service.parse_metadata(CSDL)
    calls = {"create": [], "link": [], "upload": [], "update": []}
    monkeypatch.setattr(odata_service, "schema", lambda *a, **k: sets)
    monkeypatch.setattr(odata_service, "list_raw", lambda service, name, *a, **k: CODES.get(name, []))

    def create(service, set_name, token, body, base_url=None, user_email=None):
        calls["create"].append(body)
        return {"uuid": DOC_UUID, "displayId": "7-301", **body}, None

    monkeypatch.setattr(odata_service, "create", create)
    # SAP's read-back after saving: what was stored, with status / type names.
    monkeypatch.setattr(odata_service, "get_raw", lambda *a, **k: (
        {"uuid": DOC_UUID, "displayId": "7-301", **(calls["create"][-1] if calls["create"] else {}),
         "stateCode": "ACT", "toStatus": {"code": 10, "name": "In Progress"}}, None))
    monkeypatch.setattr(odata_service, "add_link",
                        lambda service, es, token, uuid, nav, body, *a, **k: calls["link"].append((uuid, nav, body)))
    monkeypatch.setattr(odata_service, "upload_file",
                        lambda service, es, token, uuid, name, data, *a, **k: calls["upload"].append((uuid, name, len(data))))
    task = {"ID": TASK_UUID, "Display ID": "3-61724", "Type": "Requirement", "Title": "Customs form"}
    monkeypatch.setattr("src.calm.client.get_task", lambda token, ident, *a, **k: task)
    return calls


def test_a_spec_lands_with_its_type_and_every_link(calm, sap):
    out = calm(Ctx(), resource="documents", operation="create", project_id="P1", data={
        "title": "Enable SAP Cloud ALM API Connectivity for an Agent",
        "type": "functional specification", "status": "In Review",
        "content": "# 1. Purpose\n\nThis guide explains how to expose the API.",
        "requirement": "3-61724", "solution_process": "Order to Cash",
        "url": "https://sharepoint.example/sites/x/Guide.docx", "url_name": "Original Word file"})
    body = sap["create"][0]
    assert body["documentTypeCode"] == "FU" and body["statusCode"] == 20 and body["projectId"] == "P1"
    assert body["content"] == "<h1>1. Purpose</h1>\n<p>This guide explains how to expose the API.</p>"
    assert sap["link"] == [
        (DOC_UUID, "toTaskAssignments", {"id": TASK_UUID, "type": "CALMREQU"}),
        (DOC_UUID, "toURLReferences", {"url": "https://sharepoint.example/sites/x/Guide.docx",
                                       "name": "Original Word file"}),
    ]
    assert out["Content"] == {"Source": "text (Markdown / text)"}
    assert [x.get("Display ID") or x.get("URL") for x in out["Linked"]] == [
        "3-61724", "https://sharepoint.example/sites/x/Guide.docx"]
    # A solution process is linked inside a project scope in CALM: reported, never written wrong.
    assert list(out["Not Linked"]) == ["Order to Cash"] and "link it in CALM" in out["Not Linked"]["Order to Cash"]
    assert "Not Written" not in out and sap["upload"] == []


def test_a_word_file_is_converted_and_its_original_attached(calm, sap):
    out = calm(Ctx(), resource="documents", operation="create", project_id="P1", data={
        "title": "Guide", "type": "FU", "file_base64": base64.b64encode(GUIDE).decode(), "file_name": "Guide.docx"})
    assert "<h1>1. Purpose</h1>" in sap["create"][0]["content"] and sap["create"][0]["documentTypeCode"] == "FU"
    assert sap["upload"] == [(DOC_UUID, "Guide.docx", len(GUIDE))]
    assert out["File Attached"] == "Guide.docx" and out["Content"]["Pictures Not In Text"] == 2


def test_what_sap_refuses_is_reported_and_the_document_stays(calm, sap, monkeypatch):
    def refuse(*a, **k):
        raise RuntimeError("CALM API error: HTTP 400 Bad Request — DMS not configured")
    monkeypatch.setattr(odata_service, "upload_file", refuse)
    monkeypatch.setattr(odata_service, "add_link", refuse)
    out = calm(Ctx(), resource="documents", operation="create", project_id="P1", data={
        "title": "Guide", "file_base64": base64.b64encode(GUIDE).decode(), "file_name": "Guide.docx",
        "requirement": "3-61724", "url": "ftp://nope"})
    assert out["ID"] == DOC_UUID  # saved
    assert "DMS not configured" in out["Not Linked"]["3-61724"]
    assert "http" in out["Not Linked"]["ftp://nope"]
    assert "Document Management Service" in out["Not Written"]["file"]


def test_an_unknown_type_is_refused_with_the_real_ones(calm, sap):
    with pytest.raises(ValueError, match="Functional Specification \\(FU\\)"):
        calm(Ctx(), resource="documents", operation="create", project_id="P1",
             data={"title": "x", "type": "Spec of things", "content": "x"})
    assert sap["create"] == []  # nothing sent


def test_a_file_path_on_the_shared_server_is_refused_before_anything_is_sent(calm, sap, monkeypatch):
    monkeypatch.setattr(doc_content, "LOCAL_FILES", False)
    with pytest.raises(ValueError, match="own machine"):
        calm(Ctx(), resource="documents", operation="create", project_id="P1",
             data={"title": "x", "file_path": "/etc/hosts.docx"})
    assert sap["create"] == []


def test_update_can_only_add_links(calm, sap, monkeypatch):
    monkeypatch.setattr(odata_service, "resolve_uuid", lambda *a, **k: DOC_UUID)
    monkeypatch.setattr(odata_service, "get_raw", lambda *a, **k: ({"uuid": DOC_UUID, "projectId": "P1"}, None))
    monkeypatch.setattr(odata_service, "update", lambda *a, **k: sap["update"].append(a) or {})
    out = calm(Ctx(), resource="documents", operation="update", resource_id="7-301",
               data={"requirement": ["3-61724"]})
    assert sap["update"] == [] and sap["link"][0][1] == "toTaskAssignments"
    assert out["Linked"][0]["Display ID"] == "3-61724"


def test_sap_refusing_any_change_to_a_saved_document_is_reported_and_links_still_go_on(calm, sap, monkeypatch):
    """Live: SAP's Documents API answers every PATCH with 405 (its schema: a saved
    document only takes links, tags and its file)."""
    monkeypatch.setattr(odata_service, "resolve_uuid", lambda *a, **k: DOC_UUID)
    monkeypatch.setattr(odata_service, "get_raw", lambda *a, **k: ({"uuid": DOC_UUID, "projectId": "P1"}, None))

    def refuse(*a, **k):
        raise RuntimeError('CALM API error: HTTP 405 Method Not Allowed at https://x/Documents/1 — response: {"status":405}')
    monkeypatch.setattr(odata_service, "update", refuse)
    out = calm(Ctx(), resource="documents", operation="update", resource_id="7-301",
               data={"status": "Released", "content": "# New", "requirement": "3-61724"})
    assert set(out["Not Written"]) == {"status", "content"} and "change it in CALM" in out["Not Written"]["status"]
    assert out["Linked"][0]["Display ID"] == "3-61724" and sap["link"][0][1] == "toTaskAssignments"


# What `pandoc -t gfm` makes of a Word guide like the connectivity guide: the
# route Cowork takes with the hosted MCP (it converts the .docx, the MCP stores it).
PANDOC_GFM = """# Enable SAP Cloud ALM API Connectivity for an Agent

S/4 Public Cloud Practice — Setup Guide Version 1.4

## 3. Naming Convention

Throughout this guide the API application name is written as
\\<client\\>-cloudalm-agent-api.

<img src="media/image1.png" style="width:6.5in;height:3.2in" />

![](media/image2.png)

Update the following:

{\\
"xs-security": {\\
"authorities": \\[\\]\\
}\\
}

-   Note the exact scope name(s) from the error message.

-   Open the existing instance and choose **Update**.

    -   Keep every existing entry.

1.  First step

2.  Second step

<table>
<thead><tr class="header"><th>Scope</th><th>Unlocks</th></tr></thead>
<tbody><tr class="odd"><td>documents.read</td><td>list and read</td></tr></tbody>
</table>

> **Note:** the existing key stays valid.

------------------------------------------------------------------------
"""


def test_pandoc_markdown_of_a_word_guide_converts_cleanly():
    out = doc_content.markdown_html(PANDOC_GFM)
    assert "&lt;client&gt;-cloudalm-agent-api" in out and "\\\\" not in out  # escapes undone
    assert out.count("[Picture") == 2 and doc_content.pictures_in(PANDOC_GFM) == 2
    assert '<p>{<br>"xs-security": {<br>"authorities": []<br>}<br>}</p>' in out
    assert ("<ul>\n<li>Note the exact scope name(s) from the error message.</li>\n"
            "<li>Open the existing instance and choose <strong>Update</strong>.</li>\n"
            "<ul>\n<li>Keep every existing entry.</li>\n</ul>\n</ul>") in out  # one list, nested once
    assert "<ol>\n<li>First step</li>\n<li>Second step</li>\n</ol>" in out
    assert "<th>Scope</th><th>Unlocks</th>" in out and "&lt;table" not in out  # HTML table kept as a table
    assert "<blockquote><strong>Note:</strong> the existing key stays valid.</blockquote>" in out
    assert out.endswith("<hr>")


def test_pandoc_markdown_through_calm_resource(calm, sap):
    out = calm(Ctx(), resource="documents", operation="create", project_id="P1",
               data={"title": "Guide", "type": "Functional Specification", "content": PANDOC_GFM,
                     "url": "https://mysyntax-my.sharepoint.com/personal/x/Documents/Guide.docx"})
    assert out["Content"] == {"Source": "text (Markdown / text)", "Pictures Not In Text": 2}
    assert "<h2>3. Naming Convention</h2>" in sap["create"][0]["content"]
    assert sap["link"][0][1] == "toURLReferences"


# --- Diagrams: kept as Mermaid / draw.io source, with a link that draws them ---

MERMAID = """---
title: Order to cash
---
%% redrawn from Figure 2
flowchart LR
  A[Sales order] --> B{Credit check}
  B -->|ok| C[Delivery & billing]
  B -->|blocked| D["Credit release (FSCM)"]"""
DRAWIO = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
          '<mxCell id="2" value="Sales order &amp; quote" vertex="1" parent="1">'
          '<mxGeometry x="40" y="40" width="120" height="60" as="geometry"/></mxCell></root></mxGraphModel>')


def _drawn(link: str) -> str:
    """What the site's own code reads from the link (mermaid.live: base64url ->
    inflate -> JSON; draw.io: decodeURIComponent -> atob -> inflateRaw ->
    decodeURIComponent)."""
    import html as _html
    import json
    import zlib
    from urllib.parse import unquote
    link = _html.unescape(link)
    if "#pako:" in link:
        data = link.split("#pako:", 1)[1]
        state = json.loads(zlib.decompress(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))))
        assert json.loads(state["mermaid"]) == {"theme": "default"}
        return state["code"]
    data = base64.b64decode(unquote(link.split("#R", 1)[1]))
    return unquote(zlib.decompressobj(-15).decompress(data).decode())


def _links(out: str) -> list[str]:
    import re
    return re.findall(r'<a href="([^"]+)">Open diagram', out)


def test_markdown_diagrams_keep_their_source_and_get_a_link_that_draws_them():
    text = (f"# Process\n\nThe flow:\n\n```mermaid\n{MERMAID}\n```\n\n```drawio\n{DRAWIO}\n```\n\n"
            "```\nSELECT * FROM vbak\n```\n\n![](media/screenshot.png)")
    out, report, _ = doc_content.body(content=text)
    assert report == {"Source": "text (Markdown / text)", "Pictures Not In Text": 1, "Diagrams": 2,
                      "Diagrams Redrawn From Pictures": 1}  # MERMAID is marked "%% redrawn from Figure 2"
    links = _links(out)
    assert [_drawn(x) for x in links] == [MERMAID, DRAWIO]  # exactly the source, special characters included
    assert links[0].startswith("https://mermaid.live/view#pako:")
    assert links[1].startswith("https://app.diagrams.net/#R")
    assert "Open diagram 1 (Mermaid)" in out and "Open diagram 2 (draw.io)" in out
    assert "<pre>SELECT * FROM vbak</pre>\n" in out  # an ordinary code block gets no link
    assert "flowchart LR" in out  # the source stays in CALM, editable


def test_diagrams_in_html_and_word_get_links_too():
    out, report, _ = doc_content.body(
        content='<p>Flow</p><pre><code class="language-mermaid">graph TD<br>A--&gt;B</code></pre>')
    assert report["Diagrams"] == 1 and _drawn(_links(out)[0]) == "graph TD\nA-->B"
    word = _docx(_p("Flow") + _p("sequenceDiagram", mono=True) + _p("Buyer-&gt;&gt;SAP: PO", mono=True))
    out, report, _ = doc_content.body(file_base64=base64.b64encode(word).decode(), file_name="Spec.docx")
    assert report["Diagrams"] == 1 and _drawn(_links(out)[0]) == "sequenceDiagram\nBuyer->>SAP: PO"


def test_only_diagram_sources_count_as_diagrams():
    for text in ("graph theory notes", "piecewise", "<mxCellish/>", "", "flowchart is a word here"):
        assert doc_content.diagram_kind(text) is None, text
    for text in ("graph", "flowchart TD;", "%%{init: {}}%%\nerDiagram", "pie title Pets", "stateDiagram-v2",
                 '<?xml version="1.0"?>\n<mxfile host="app.diagrams.net"></mxfile>'):
        assert doc_content.diagram_kind(text), text


def test_a_spec_with_diagrams_through_calm_resource(calm, sap):
    out = calm(Ctx(), resource="documents", operation="create", project_id="P1",
               data={"title": "Spec", "type": "Functional Specification",
                     "content": f"## Flow\n\n```mermaid\n{MERMAID}\n```"})
    assert out["Content"] == {"Source": "text (Markdown / text)", "Diagrams": 1, "Diagrams Redrawn From Pictures": 1}
    assert _drawn(_links(sap["create"][0]["content"])[0]) == MERMAID


def test_a_diagram_redrawn_from_a_picture_is_marked_in_calm_and_counted():
    text = ("## Flow\n\n```mermaid\n%% redrawn from Figure 1\nflowchart LR\n  A[Sales order] --> B[Billing]\n```\n\n"
            "```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n\n![Figure 2: SAP screen](picture)")
    out, report, _ = doc_content.body(content=text)
    assert report == {"Source": "text (Markdown / text)", "Pictures Not In Text": 1, "Diagrams": 2,
                      "Diagrams Redrawn From Pictures": 1}
    assert "Open diagram 1 (Mermaid)</a> — redrawn by AI from Figure 1: check it against the original</p>" in out
    assert "Open diagram 2 (Mermaid)</a></p>" in out  # written as Mermaid in the spec: no note
    assert "[Picture: Figure 2: SAP screen]" in out  # a picture the agent couldn't see stays, counted


def test_the_answer_is_what_sap_stored_read_back(calm, sap):
    out = calm(Ctx(), resource="documents", operation="create", project_id="P1",
               data={"title": "Spec", "type": "Functional Specification", "content": "# Hi"})
    assert out["Status"] == {"Code": 10, "Name": "In Progress"}  # the status, never the state "ACT"
    assert out["Display ID"] == "7-301" and "Read Back" not in out


def test_a_failed_read_back_is_reported_and_the_document_stays(calm, sap, monkeypatch):
    def down(*a, **k):
        raise RuntimeError("CALM API error: HTTP 503")
    monkeypatch.setattr(odata_service, "get_raw", down)
    out = calm(Ctx(), resource="documents", operation="create", project_id="P1",
               data={"title": "Spec", "content": "# Hi"})
    assert out["ID"] == DOC_UUID and "HTTP 503" in out["Read Back"]


def test_a_figure_whose_picture_was_left_out_is_named_never_silent():
    """GenAI Studio (2026-11-05): the agent had only the Word text and passed the
    caption without the picture; nothing said Figure 1 was gone."""
    text = ("## 3. Process Flow\n\nFigure 1 shows the credit check flow.\n\nFigure 1: Credit check flow\n\n"
            "![](media/image2.png)\n\n*Figure 2: Order screen*\n\n"
            "```mermaid\n%% redrawn from Figure 3\nflowchart LR\n  A --> B\n```\n\nFigure 3: Release flow")
    _, report, _ = doc_content.body(content=text)
    assert report["Figures Without A Picture"] == ["Figure 1: Credit check flow"]  # 2 counted, 3 redrawn
    assert doc_content.figures_without_a_picture("<p>Figure 1 shows the flow.</p>") == []  # a mention, not a caption
    # a picture only counts for the caption right next to it, not one a list away
    _, report, _ = doc_content.body(content="![Figure 3](a.png)\n\n## Open\n\n1. x\n2. y\n\nFigure 9: Landscape")
    assert report["Figures Without A Picture"] == ["Figure 9: Landscape"]
