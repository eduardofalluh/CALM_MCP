"""A document's body for SAP Cloud ALM, from what an agent or user has: text
(Markdown, HTML or plain) or a file (.docx, .md, .txt, .html).

CALM keeps a document's body as rich text (HTML). A Word file is a zip of XML,
read here with the standard library: headings, paragraphs, bold / italic,
bulleted and numbered lists, tables, links and code blocks are kept. Pictures
can't travel in the text; they are counted and reported, never dropped unseen.
A diagram written as Mermaid or draw.io source is kept as its source, with a
link that draws it.
"""

from __future__ import annotations

import base64
import binascii
import html
import io
import json
import re
import zipfile
import zlib
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET

# Reading a file by path is only safe when the MCP runs on the user's own machine
# (stdio). On the shared HTTP server a path would point at the server's disk, so
# server.py turns this off there.
LOCAL_FILES = False

FILE_TYPES = {".docx": "Word", ".md": "Markdown", ".markdown": "Markdown", ".txt": "Text",
              ".html": "HTML", ".htm": "HTML"}
MAX_FILE_BYTES = 25_000_000
MAX_XML_BYTES = 50_000_000  # one part of a .docx, uncompressed (zip-bomb guard)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_MONO = ("courier", "consolas", "menlo", "monaco", "lucida console", "source code")


def body(content: Any = None, file_path: Any = None, file_base64: Any = None,
         file_name: Any = None) -> tuple[str, dict, tuple[str, bytes] | None]:
    """(html, report, original file) from exactly one of: content text, a local
    file path, or a file sent as base64. The original file comes back so it can
    be attached to the CALM document as well."""
    out, report, original = _body(content, file_path, file_base64, file_name)
    out, count, redrawn = diagrams(out)
    if count:
        report["Diagrams"] = count
    if redrawn:
        report["Diagrams Redrawn From Pictures"] = redrawn  # by the agent: to be checked against the original
    return out, report, original


def _body(content: Any, file_path: Any, file_base64: Any,
          file_name: Any) -> tuple[str, dict, tuple[str, bytes] | None]:
    given = [k for k, v in (("content", content), ("file_path", file_path), ("file_base64", file_base64))
             if v not in (None, "")]
    if len(given) != 1:
        raise ValueError("Give the document's body as exactly one of: content (text, Markdown or HTML), "
                         f"file_path (a local .docx/.md/.txt/.html), or file_base64 + file_name (got {given or 'none'})")
    if content not in (None, ""):
        text = str(content)
        kind = "HTML" if _looks_html(text) else "Markdown / text"
        report: dict = {"Source": f"text ({kind})"}
        if pictures_in(text):
            report["Pictures Not In Text"] = pictures_in(text)
        return (_without_pictures(sanitize(text)) if kind == "HTML" else markdown_html(text)), report, None
    if file_path not in (None, ""):
        name, data = _read_local(str(file_path))
    else:
        name = str(file_name or "").strip()
        try:
            data = base64.b64decode(str(file_base64), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("file_base64 is not valid base64") from None
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"The file is {len(data):,} bytes; the limit is {MAX_FILE_BYTES:,}")
        if not name:
            name = "document.docx" if data[:2] == b"PK" else "document.txt"
    suffix = Path(name).suffix.lower()
    if suffix not in FILE_TYPES:
        raise ValueError(f"'{name}' is not a supported file. Supported: {', '.join(sorted(FILE_TYPES))}")
    report: dict = {"Source": f"{FILE_TYPES[suffix]} file '{Path(name).name}' ({len(data):,} bytes)"}
    if suffix == ".docx":
        out, pictures = docx_html(data)
        if pictures:
            report["Pictures Not In Text"] = pictures
    else:
        text = data.decode("utf-8-sig", errors="replace")
        out = _without_pictures(sanitize(text)) if FILE_TYPES[suffix] == "HTML" else (
            markdown_html(text) if FILE_TYPES[suffix] == "Markdown" else _plain_html(text))
        if FILE_TYPES[suffix] != "Text" and pictures_in(text):
            report["Pictures Not In Text"] = pictures_in(text)
    return out, report, (Path(name).name, data)


def _read_local(path: str) -> tuple[str, bytes]:
    if not LOCAL_FILES:
        raise ValueError("file_path works only when the MCP runs on your own machine. Here, send the "
                         "document's text as content (or a small file as file_base64 + file_name).")
    p = Path(path).expanduser()
    real = p.resolve()
    if real.suffix.lower() not in FILE_TYPES or p.suffix.lower() not in FILE_TYPES:
        raise ValueError(f"'{p.name}' is not a supported file. Supported: {', '.join(sorted(FILE_TYPES))}")
    if not real.is_file():
        raise ValueError(f"No file at '{path}'")
    size = real.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"The file is {size:,} bytes; the limit is {MAX_FILE_BYTES:,}")
    return p.name, real.read_bytes()


# --------------------------------------------------------------------------- #
# Word (.docx)
# --------------------------------------------------------------------------- #

def _part(z: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_XML_BYTES:
        raise ValueError(f"The Word file's {name} is too large to read safely")
    data = z.read(info)
    if b"<!DOCTYPE" in data[:2000].upper():
        raise ValueError("The Word file contains a DOCTYPE, which a real .docx never has")
    return ET.fromstring(data)


def docx_html(data: bytes) -> tuple[str, int]:
    """(html, picture count) for a .docx file."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("The file is not a valid Word (.docx) file") from None
    with z:
        doc = _part(z, "word/document.xml")
        if doc is None:
            raise ValueError("The file is not a valid Word (.docx) file (no word/document.xml)")
        styles = {s.get(f"{_W}styleId"): (s.find(f"{_W}name").get(f"{_W}val") if s.find(f"{_W}name") is not None else "")
                  for s in (_part(z, "word/styles.xml") or ET.Element("x")).iter(f"{_W}style")}
        links = {r.get("Id"): r.get("Target") for r in (_part(z, "word/_rels/document.xml.rels") or ET.Element("x"))
                 if "hyperlink" in (r.get("Type") or "")}
        ordered = _numbering(_part(z, "word/numbering.xml"))
    root = doc.find(f"{_W}body")
    out: list[str] = []
    state = {"pictures": 0, "lists": [], "code": []}
    for el in _blocks(root if root is not None else doc):
        if el.tag == f"{_W}tbl":
            _close(out, state)
            out.append(_table(el, links, state))
        else:
            _paragraph(el, styles, links, ordered, out, state)
    _close(out, state)
    return "\n".join(o for o in out if o), state["pictures"]


def _blocks(parent: ET.Element):
    """Paragraphs and tables in reading order, looking inside content controls."""
    for el in parent:
        if el.tag in (f"{_W}p", f"{_W}tbl"):
            yield el
        elif el.tag == f"{_W}sdt":
            content = el.find(f"{_W}sdtContent")
            if content is not None:
                yield from _blocks(content)


def _numbering(root: ET.Element | None) -> dict:
    """{(numId, level): True when numbered (1, 2, 3), False when bulleted}."""
    if root is None:
        return {}
    abstract = {}
    for a in root.iter(f"{_W}abstractNum"):
        levels = {}
        for lvl in a.iter(f"{_W}lvl"):
            fmt = lvl.find(f"{_W}numFmt")
            levels[lvl.get(f"{_W}ilvl")] = (fmt is not None and fmt.get(f"{_W}val") not in ("bullet", "none"))
        abstract[a.get(f"{_W}abstractNumId")] = levels
    out = {}
    for num in root.iter(f"{_W}num"):
        ref = num.find(f"{_W}abstractNumId")
        for lvl, numbered in abstract.get(ref.get(f"{_W}val") if ref is not None else None, {}).items():
            out[(num.get(f"{_W}numId"), lvl)] = numbered
    return out


def _runs(el: ET.Element, links: dict, state: dict) -> tuple[str, bool]:
    """(inline html, all text is monospace) for a paragraph or hyperlink."""
    parts: list[str] = []
    mono = []
    for child in el:
        if child.tag == f"{_W}hyperlink":
            inner, m = _runs(child, links, state)
            target = links.get(child.get(f"{_R}id"))
            parts.append(f'<a href="{html.escape(target)}">{inner}</a>' if _safe_url(target) else inner)
            mono.append(m)
        elif child.tag == f"{_W}r":
            text, m = _run(child, state)
            parts.append(text)
            if text.strip():
                mono.append(m)
        elif child.tag in (f"{_W}ins", f"{_W}smartTag", f"{_W}fldSimple"):
            inner, m = _runs(child, links, state)
            parts.append(inner)
            mono.append(m)
    return "".join(parts), bool(mono) and all(mono)


def _run(r: ET.Element, state: dict) -> tuple[str, bool]:
    props = r.find(f"{_W}rPr")
    text = []
    for c in r:
        if c.tag == f"{_W}t":
            text.append(html.escape(c.text or "", quote=False))
        elif c.tag == f"{_W}tab":
            text.append("\t")
        elif c.tag in (f"{_W}br", f"{_W}cr"):
            text.append("<br>")
        elif c.tag in (f"{_W}drawing", f"{_W}pict", f"{_W}object"):
            state["pictures"] += 1
            text.append(f"[Picture {state['pictures']}]")
    out = "".join(text)
    if props is not None and out.strip():
        if _on(props.find(f"{_W}b")):
            out = f"<strong>{out}</strong>"
        if _on(props.find(f"{_W}i")):
            out = f"<em>{out}</em>"
        if _on(props.find(f"{_W}u")):
            out = f"<u>{out}</u>"
    font = props.find(f"{_W}rFonts") if props is not None else None
    face = " ".join(font.get(f"{_W}{k}") or "" for k in ("ascii", "hAnsi")).lower() if font is not None else ""
    return out, any(m in face for m in _MONO)


def _on(el: ET.Element | None) -> bool:
    return el is not None and el.get(f"{_W}val") not in ("0", "false", "none")


def _paragraph(p: ET.Element, styles: dict, links: dict, ordered: dict, out: list, state: dict) -> None:
    props = p.find(f"{_W}pPr")
    style_el = props.find(f"{_W}pStyle") if props is not None else None
    style = (styles.get(style_el.get(f"{_W}val")) or style_el.get(f"{_W}val") or "").lower() if style_el is not None else ""
    num = props.find(f"{_W}numPr") if props is not None else None
    inner, mono = _runs(p, links, state)
    level = _heading(style)
    if (mono or re.search(r"code|preformatted|source|macro", style)) and not level and num is None:
        _close_lists(out, state)
        state["code"].append(re.sub(r"<[^>]+>", "", inner.replace("<br>", "\n")))
        return
    _close_code(out, state)
    if num is not None:
        lvl_el, id_el = num.find(f"{_W}ilvl"), num.find(f"{_W}numId")
        lvl = lvl_el.get(f"{_W}val") if lvl_el is not None else "0"
        tag = "ol" if ordered.get((id_el.get(f"{_W}val") if id_el is not None else None, lvl)) else "ul"
        depth = int(lvl) + 1 if str(lvl).isdigit() else 1
        lists = state["lists"]
        while len(lists) > depth:
            out.append(f"</{lists.pop()}>")
        if len(lists) == depth and lists[-1] != tag:
            out.append(f"</{lists.pop()}>")
        while len(lists) < depth:
            lists.append(tag)
            out.append(f"<{tag}>")
        out.append(f"<li>{inner}</li>")
        return
    _close_lists(out, state)
    if level:
        out.append(f"<h{level}>{inner}</h{level}>")
    elif inner.strip():
        out.append(f"<p>{inner}</p>")


def _heading(style: str) -> int:
    if style in ("title",):
        return 1
    m = re.match(r"(?:heading|überschrift|titre|título|titolo)\s*(\d)", style)
    return min(int(m.group(1)), 6) if m else 0


def _table(tbl: ET.Element, links: dict, state: dict) -> str:
    rows = []
    for tr in tbl.iter(f"{_W}tr"):
        cells = []
        for tc in tr.findall(f"{_W}tc"):
            texts = [_runs(p, links, state)[0] for p in tc.iter(f"{_W}p")]
            cells.append("<td>" + "<br>".join(t for t in texts if t.strip()) + "</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table>" + "".join(rows) + "</table>"


def _close_lists(out: list, state: dict) -> None:
    while state["lists"]:
        out.append(f"</{state['lists'].pop()}>")


def _close_code(out: list, state: dict) -> None:
    if state["code"]:
        out.append("<pre>" + "\n".join(state["code"]) + "</pre>")
        state["code"] = []


def _close(out: list, state: dict) -> None:
    _close_code(out, state)
    _close_lists(out, state)


# --------------------------------------------------------------------------- #
# Diagrams
# --------------------------------------------------------------------------- #
# CALM's editor can't draw a diagram, so a Mermaid / draw.io diagram stays as its
# source (editable in CALM) and gets a link that draws it in the browser. The
# source rides in the link's #fragment, which browsers never send to the site.

_MERMAID = re.compile(
    r"(flowchart|graph)(\s+(TB|TD|BT|RL|LR))?\s*;?\s*$|(sequenceDiagram|classDiagram(-v2)?|stateDiagram(-v2)?"
    r"|erDiagram|journey|gantt|pie|quadrantChart|requirementDiagram|gitGraph|C4Context|C4Container|C4Component"
    r"|C4Dynamic|C4Deployment|mindmap|timeline|zenuml|sankey-beta|xychart-beta|block-beta|packet-beta|kanban"
    r"|architecture-beta|radar-beta)\b")
_PRE = re.compile(r"<pre\b[^>]*>(.*?)</pre>", re.I | re.S)
# An agent marks a diagram it redrew from a picture with a Mermaid comment,
# "%% redrawn from Figure 1", so CALM shows it must be checked.
_REDRAWN = re.compile(r"^\s*%%\s*redrawn\b(?:\s+from\s+(.+))?", re.I | re.M)


def diagram_kind(source: str) -> str | None:
    """"Mermaid" or "draw.io" when a code block's text is a diagram's source."""
    text = source.strip()
    if re.match(r"(<\?xml[^>]*>\s*)?<(mxfile|mxGraphModel)\b", text):
        return "draw.io"
    lines = [x.strip() for x in text.split("\n")]
    if lines[0] == "---":  # Mermaid front matter (title / config)
        lines = lines[lines.index("---", 1) + 1:] if "---" in lines[1:] else []
    first = next((x for x in lines if x and not x.startswith("%%")), "")
    return "Mermaid" if _MERMAID.match(first) else None


def diagram_link(source: str, kind: str) -> str:
    """A link that opens the diagram drawn: mermaid.live for Mermaid, the
    draw.io app for draw.io (both decode the #fragment in the browser)."""
    if kind == "Mermaid":
        state = json.dumps({"code": source, "mermaid": json.dumps({"theme": "default"})})
        packed = base64.urlsafe_b64encode(zlib.compress(state.encode(), 9)).decode().rstrip("=")
        return "https://mermaid.live/view#pako:" + packed
    deflate = zlib.compressobj(9, zlib.DEFLATED, -15)  # draw.io: raw deflate of the URI-encoded XML
    packed = deflate.compress(quote(source, safe="-_.!~*'()").encode()) + deflate.flush()
    return "https://app.diagrams.net/#R" + quote(base64.b64encode(packed).decode(), safe="")


def diagrams(html_text: str) -> tuple[str, int, int]:
    """Each code block holding a Mermaid / draw.io diagram gets an "Open
    diagram N" link right after it, and a diagram marked as redrawn from a
    picture says so next to its link; returns the HTML, how many diagrams,
    and how many of them were redrawn."""
    count = redrawn = 0

    def link(m: re.Match) -> str:
        nonlocal count, redrawn
        source = re.sub(r"<br\s*/?>", "\n", m.group(1), flags=re.I)
        source = html.unescape(re.sub(r"<[^>]+>", "", source)).strip()
        kind = diagram_kind(source)
        if not kind:
            return m.group(0)
        count += 1
        note = ""
        if marked := _REDRAWN.search(source):
            redrawn += 1
            what = html.escape((marked.group(1) or "a picture").strip().rstrip(".:"), quote=False)
            note = f" — redrawn by AI from {what}: check it against the original"
        return (f'{m.group(0)}<p><a href="{html.escape(diagram_link(source, kind))}">'
                f"Open diagram {count} ({kind})</a>{note}</p>")

    return _PRE.sub(link, html_text), count, redrawn


# --------------------------------------------------------------------------- #
# Markdown / plain text / HTML
# --------------------------------------------------------------------------- #

def _looks_html(text: str) -> bool:
    return bool(re.match(r"\s*<(!doctype|html|body|div|p|h[1-6]|ul|ol|table|section|article)\b", text, re.I))


def _safe_url(url: Any) -> bool:
    return bool(url) and re.match(r"(https?:|mailto:)", str(url), re.I) is not None


# A picture in Markdown (pandoc writes ![](media/image1.png){width=...}) or HTML.
_MD_PICTURE = re.compile(r"!\[([^\]]*)\]\([^)]*\)(\{[^}]*\})?")
_HTML_PICTURE = re.compile(r"<img\b[^>]*>", re.I)
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!<>$|~\"'=&^%@])")
_HTML_BLOCK = re.compile(r"<(table|img|div|figure|p|ul|ol|pre|blockquote|h[1-6]|colgroup|thead|tbody|tr)\b", re.I)


def pictures_in(text: str) -> int:
    """Pictures a Markdown / HTML text refers to (they can't travel as text)."""
    return len(_MD_PICTURE.findall(text)) + len(_HTML_PICTURE.findall(text))


def _without_pictures(html_text: str) -> str:
    return _HTML_PICTURE.sub("[Picture]", html_text)


def _inline(text: str) -> str:
    text = _MD_PICTURE.sub(lambda m: f"[Picture{': ' + m.group(1) if m.group(1) else ''}]", text)
    text = re.sub(r"(\\|\s{2,})$", "", text)  # a hard line break marker; lines join with <br> anyway
    parts = re.split(r"(`[^`]+`)", text)  # escapes and emphasis never apply inside code
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1], quote=False)}</code>")
            continue
        piece = html.escape(_ESCAPED.sub(r"\1", part), quote=False)
        piece = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", piece)
        piece = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", piece)
        piece = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                       lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>' if _safe_url(m.group(2)) else m.group(0),
                       piece)
        out.append(piece)
    return "".join(out)


_LIST_ITEM = re.compile(r"(\s*)([-*+•]|\d+[.)])\s+(.*)")


def markdown_html(text: str) -> str:
    """Markdown (or plain text) -> HTML: headings, lists (loose or tight, nested by
    indentation), tables (pipe or raw HTML), code blocks, quotes, rules, bold /
    italic / code / links, and pandoc's escapes. Pictures become "[Picture]".
    Line breaks inside a paragraph are kept."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    lists: list[tuple[str, int]] = []  # (ul / ol, indentation)
    i = 0

    def flush() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()

    def close_lists(to_indent: int = -1) -> None:
        while lists and lists[-1][1] > to_indent:
            out.append(f"</{lists.pop()[0]}>")

    def next_text(j: int) -> str:
        while j < len(lines) and not lines[j].strip():
            j += 1
        return lines[j] if j < len(lines) else ""

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        item = _LIST_ITEM.match(line)
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush()
            close_lists()
            fence = stripped[:3]
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                block.append(lines[i])
                i += 1
            out.append("<pre>" + html.escape("\n".join(block), quote=False) + "</pre>")
        elif m := re.match(r"(#{1,6})\s+(.*)", stripped):
            flush()
            close_lists()
            title = re.sub(r"\s*\{[#.][^}]*\}\s*$", "", m.group(2)).rstrip("#").strip()
            out.append(f"<h{len(m.group(1))}>{_inline(title)}</h{len(m.group(1))}>")
        elif re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", stripped):
            flush()
            close_lists()
            out.append("<hr>")
        elif _HTML_BLOCK.match(stripped):
            flush()
            close_lists()
            block = []
            while i < len(lines) and lines[i].strip():
                block.append(lines[i])
                i += 1
            out.append(_without_pictures(sanitize("\n".join(block))))
            continue
        elif stripped.startswith("|") and stripped.count("|") >= 2:
            flush()
            close_lists()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("<table>" + "".join(rows) + "</table>")
            continue
        elif item:
            flush()
            indent = len(item.group(1).expandtabs(4))
            tag = "ol" if item.group(2)[0].isdigit() else "ul"
            close_lists(indent)
            if lists and lists[-1][1] == indent and lists[-1][0] != tag:
                out.append(f"</{lists.pop()[0]}>")
            if not lists or lists[-1][1] < indent:
                lists.append((tag, indent))
                out.append(f"<{tag}>")
            out.append(f"<li>{_inline(item.group(3))}</li>")
        elif stripped.startswith(">"):
            flush()
            close_lists()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" + "<br>".join(_inline(q) for q in quote if q) + "</blockquote>")
            continue
        elif not stripped:
            flush()
            # A blank line between items of the same list (pandoc's loose lists)
            # keeps the list open.
            following = next_text(i + 1)
            if not (lists and (_LIST_ITEM.match(following) or following.startswith(" " * (lists[-1][1] + 2)))):
                close_lists()
        elif lists and line.startswith(" ") and out and out[-1].endswith("</li>"):
            out[-1] = out[-1][:-5] + "<br>" + _inline(stripped) + "</li>"  # an item's continued text
        else:
            close_lists()
            para.append(stripped)
        i += 1
    flush()
    close_lists()
    return "\n".join(out)


def _plain_html(text: str) -> str:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    return "\n".join("<p>" + "<br>".join(html.escape(x, quote=False) for x in b.split("\n")) + "</p>"
                     for b in blocks if b.strip())


def sanitize(text: str) -> str:
    """HTML without scripts, styles, event handlers or javascript: links."""
    out = re.sub(r"<(script|style|iframe|object|embed)\b.*?</\1\s*>", "", text, flags=re.I | re.S)
    out = re.sub(r"<(script|style|iframe|object|embed)\b[^>]*>", "", out, flags=re.I)
    out = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", out, flags=re.I)
    return re.sub(r"(href|src)\s*=\s*([\"']?)\s*javascript:[^\"'\s>]*\2", r'\1="#"', out, flags=re.I)
