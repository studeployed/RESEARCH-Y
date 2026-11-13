"""Inspect explicit JATS meeting abstracts while preserving their container and XML boundaries."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree as ET

MAX_BYTES = 8 * 1024 * 1024
MAX_PREVIEW_BYTES = 16 * 1024 * 1024
MAX_MATCH_CHARACTERS = 32 * 1024 * 1024
XLINK = "{http://www.w3.org/1999/xlink}href"
ABSTRACT_TYPES = {"abstract", "meeting-abstract", "conference-abstract"}


class ConferenceInputError(ValueError):
    pass


class _BoundedTree(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.nodes = 0

    def start(self, tag, attrs):
        if len(tag) > 512 or any(len(key) > 512 for key in attrs):
            raise ConferenceInputError("XML name exceeds the supported size")
        self.depth += 1
        self.nodes += 1
        if self.depth > 96 or self.nodes > 120_000:
            raise ConferenceInputError("XML structure exceeds the supported size")
        return super().start(tag, attrs)

    def start_ns(self, prefix, uri):
        if len(uri) > 384 or len(prefix or "") > 128:
            raise ConferenceInputError("XML namespace exceeds the supported size")

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)

def _text(node, path):
    item = node.find(path)
    if item is None:
        return None
    return _body_text(item)


def _link(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme in {"https", "http"} and url.hostname and url.username is None and url.password is None:
            _ = url.port
            return value
    except ValueError:
        pass
    return None


def _ids(meta):
    return [{"type": node.get("pub-id-type"), "value": _text(node, ".")}
            for node in meta.findall("article-id") if _text(node, ".")]


def _authors(meta):
    result = []
    for author in meta.findall("contrib-group/contrib[@contrib-type='author']"):
        name = _text(author, "collab") or _text(author, "string-name")
        if not name:
            name = " ".join(v for v in (_text(author, "name/given-names"),
                                         _text(author, "name/surname")) if v)
        if name:
            result.append(name)
    return result


def _body_text(node):
    # Separate block boundaries, retain inline typography and every text/tail
    # (including unwrapped introductions, captions, table cells and lists).
    blocks = {"p", "sec", "title", "label", "list", "list-item", "table-wrap", "table", "tr",
              "th", "td", "caption", "fig", "disp-quote", "statement", "def-item", "def", "term"}
    parts = []
    def collect(element):
        if element.tag == "break":
            parts.append(" ")
            return
        if element.tag in blocks:
            parts.append("\n")
        if element.text:
            parts.append(re.sub(r"\s+", " ", element.text))
        for child in element:
            if child.tag not in {"sub-article", "response"}:
                collect(child)
            if child.tail:
                parts.append(re.sub(r"\s+", " ", child.tail))
        if element.tag in blocks:
            parts.append("\n")
    collect(node)
    return "\n".join(" ".join(line.split()) for line in "".join(parts).splitlines() if line.strip()) or None


def inspect_conference_jats(payload, *, terms=(), landing_url=None, pdf_url=None, pdf_pages=None):
    """Return a source-scoped preview. PDF page numbers are explicit one-based supplied mappings."""
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BYTES:
        raise ConferenceInputError("Invalid document size")
    try:
        xml = payload.decode("utf-8-sig")
        if "\0" in xml or re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", xml, re.I):
            raise ConferenceInputError("Unsupported XML declaration")
        root = ET.fromstring(xml, parser=ET.XMLParser(target=_BoundedTree()))
    except (ET.ParseError, UnicodeError) as exc:
        raise ConferenceInputError("Invalid UTF-8 JATS XML") from exc
    if root.tag != "article":
        raise ConferenceInputError("Expected a JATS article container")
    meta = root.find("front/article-meta")
    if meta is None:
        raise ConferenceInputError("Missing container metadata")
    if (landing_url is not None and not _link(landing_url)) or (pdf_url is not None and not _link(pdf_url)):
        raise ConferenceInputError("Invalid supplied document URL")
    if not isinstance(terms, (list, tuple)) or len(terms) > 512 or any(
        not isinstance(term, str) or not term.strip() or len(term) > 2048 for term in terms
    ):
        raise ConferenceInputError("Invalid atomic search terms")
    terms = list(dict.fromkeys(term.strip() for term in terms))
    patterns = [(term, re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.I)) for term in terms]
    pages = {} if pdf_pages is None else pdf_pages
    if (not isinstance(pages, dict) or any(type(key) is not str or type(value) is not int or value < 1
                                          for key, value in pages.items())):
        raise ConferenceInputError("Invalid PDF page mapping")
    container = dict(title=_text(meta, "title-group/article-title"),
                     journal=_text(root, "front/journal-meta/journal-title-group/journal-title"),
                     year=_text(meta, "pub-date/year"), volume=_text(meta, "volume"),
                     issue=_text(meta, "issue"), supplement=_text(meta, "supplement"),
                     identifiers=_ids(meta), landing_url=landing_url, pdf_url=pdf_url,
                     conference=_text(meta, "conference/conf-name"), conference_date=_text(meta, "conference/conf-date"))
    shared_dois = {i["value"].casefold() for i in container["identifiers"] if (i["type"] or "").casefold() == "doi"}
    children = root.findall("sub-article")
    if len(children) > 10_000:
        raise ConferenceInputError("Too many sub-articles for one preview")
    def size(value):
        return len(json.dumps(value, ensure_ascii=True, indent=2))
    # Account for every retained row, including repeated matched terms. Count
    # escaped JSON characters since the CLI emits ASCII. Leave headroom for
    # outer keys, separators and indentation. Reject a whole oversized
    # preview rather than silently truncating the scientific record.
    preview_bytes = size(container) + 1024
    if preview_bytes > MAX_PREVIEW_BYTES:
        raise ConferenceInputError("Preview exceeds supported output size")
    doi_blocks = Counter()
    for child in children:
        own_ids = child.findall("front-stub/article-id") + child.findall("front/article-meta/article-id")
        doi_blocks.update({v.casefold() for elem in own_ids
                           if elem.get("pub-id-type", "").casefold() == "doi" and (v := _text(elem, "."))})
    # In the supported profile individual abstracts are immediate sub-articles.
    # Never fold an unhandled nested article into a neighbouring result.
    ids = Counter(n.get("id") for n in root.iter() if n.get("id"))
    supported_ids = {n.get("id") for n in children if n.get("article-type") in ABSTRACT_TYPES}
    if any(key not in supported_ids or ids[key] != 1 for key in pages):
        raise ConferenceInputError("PDF mapping requires a unique abstract XML ID")
    result = []
    pending = []
    match_work = 0
    for pos, node in enumerate(children, 1):
        path = f"/article/sub-article[{pos}]"
        if node.get("article-type") not in ABSTRACT_TYPES:
            pending.append({"locator": path, "reason": "unclassified_sub_article"})
            continue
        front = node.find("front-stub")
        if front is None:
            front = node.find("front/article-meta")
        if front is None:
            front = ET.Element("front-stub")
        if node.findall(".//sub-article"):
            pending.append({"locator": path, "reason": "nested_sub_articles_require_review"})
            continue
        title = _text(front, "title-group/article-title")
        blocks = front.findall("abstract") + node.findall("body")
        body = "\n".join(value for block in blocks if (value := _body_text(block))) or None
        identifier = node.get("id")
        page = pages.get(identifier)
        pdf_link = None
        if page and pdf_url:
            parsed = urlsplit(pdf_url)
            pdf_link = urlunsplit(parsed._replace(fragment=f"page={page}"))
        original_ids = _ids(front)
        source_dois = [item["value"] for item in original_ids if (item["type"] or "").casefold() == "doi"]
        individual_doi = [v for v in source_dois if v.casefold() not in shared_dois and doi_blocks[v.casefold()] == 1]
        direct = front.find("self-uri")
        direct_url = _link(direct.get(XLINK)) if direct is not None else None
        warnings = []
        if not ((identifier and ids[identifier] == 1) or individual_doi):
            warnings.append("unresolved_individual_identity")
        if any(v.casefold() in shared_dois for v in source_dois):
            warnings.append("doi_shared_with_container")
        if any(doi_blocks[v.casefold()] > 1 for v in source_dois):
            warnings.append("doi_shared_across_sub_articles")
        for field, value in (("title", title), ("text", body), ("printed_page", _text(front, "fpage")),
                             ("pdf_page", page), ("individual_link", direct_url)):
            if not value:
                warnings.append("missing_" + field)
        searchable = [v for v in (title, body) if v]
        match_work += len(patterns) * sum(map(len, searchable))
        if match_work > MAX_MATCH_CHARACTERS:
            raise ConferenceInputError("Term matching exceeds the supported work budget")
        item = dict(locator=path, xml_id=identifier, title=title, text=body, authors=_authors(front),
                           source_identifiers=original_ids, individual_dois=individual_doi,
                           number=_text(front, "elocation-id"), printed_first_page=_text(front, "fpage"),
                           printed_last_page=_text(front, "lpage"), pdf_page=page, pdf_page_url=pdf_link,
                           individual_url=direct_url, conference=_text(front, "conference/conf-name"),
                           conference_date=_text(front, "conference/conf-date"),
                           matched_terms=[term for term, pattern in patterns if any(pattern.search(v) for v in searchable)],
                           warnings=warnings)
        preview_bytes += size(item) + 256
        if preview_bytes > MAX_PREVIEW_BYTES:
            raise ConferenceInputError("Preview exceeds supported output size")
        result.append(item)
    if not children:
        pending.append({"locator": "/article", "reason": "no_explicit_sub_articles"})
    preview = dict(source_sha256=sha256(payload).hexdigest(), container=container,
                   abstracts=result, unresolved=pending)
    if size(preview) > MAX_PREVIEW_BYTES:
        raise ConferenceInputError("Preview exceeds supported output size")
    return preview
