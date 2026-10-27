"""Bounded NCBI PubMed EFetch XML metadata and abstract acquisition.

A successful EFetch response establishes neither complete source retrieval nor
publication-level deduplication. Every requested PMID must be represented
exactly once; unknown/omitted records make the batch incomplete, not successful.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener
import xml.etree.ElementTree as ET

from research_y.pubmed_probe import PubMedESearchProbeClient, _RejectRedirects

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
MAX_BATCH_IDS = 20
MAX_EFETCH_BYTES = 8 * 1024 * 1024
MAX_XML_NODES = 200_000
_PMID = re.compile(r"[1-9][0-9]{0,31}\Z")


class PubMedMetadataError(ValueError):
    """EFetch metadata could not be safely accepted or reconciled."""


class PubMedMetadataTransportError(PubMedMetadataError):
    def __init__(self, message: str, *, retryable: bool = False, http_status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class PubMedRecord:
    """Parsed source fields, kept distinct from normalised publication values."""

    pmid: str
    title: str | None
    abstract_sections: tuple[dict[str, str | None], ...]
    abstract_status: str
    abstract_copyright: str | None
    authors: tuple[dict[str, object], ...]
    journal: dict[str, str | None]
    publication_dates: tuple[dict[str, str | None], ...]
    identifiers: dict[str, tuple[str, ...]]
    languages: tuple[str, ...]
    publication_types: tuple[str, ...]
    keywords: tuple[str, ...]
    mesh_headings: tuple[dict[str, object], ...]
    citation_status: str | None
    other_abstracts: tuple[dict[str, object], ...] = ()

    def source_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PubMedMetadataBatch:
    requested_pmids: tuple[str, ...]
    records: tuple[PubMedRecord, ...]
    response_sha256: str
    retrieved_at_utc: str
    source: str = "NCBI PubMed EFetch XML"
    source_retrieval_verified: bool = False


def validate_pmids(pmids: object, *, cap: int = MAX_BATCH_IDS) -> tuple[str, ...]:
    if not isinstance(pmids, (tuple, list)) or not 1 <= len(pmids) <= cap:
        raise ValueError("EFetch requires a bounded, nonempty PMID batch")
    if any(not isinstance(p, str) or not _PMID.fullmatch(p) for p in pmids):
        raise ValueError("EFetch requires canonical positive PMID strings")
    if len(set(pmids)) != len(pmids):
        raise ValueError("EFetch PMIDs must be unique")
    return tuple(pmids)


def _text(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    result = re.sub(r"\s+", " ", "".join(node.itertext())).strip()
    return result or None


def _path(node: ET.Element, path: str) -> str | None:
    return _text(node.find(path))


def _unique(values: list[str | None]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(v for v in values if v))


def _date(node: ET.Element, *, kind: str) -> dict[str, str | None]:
    return {
        "kind": kind,
        "year": _path(node, "Year"), "month": _path(node, "Month"),
        "day": _path(node, "Day"), "medline_date": _path(node, "MedlineDate"),
        "season": _path(node, "Season"),
    }


def _authors(article: ET.Element) -> tuple[dict[str, object], ...]:
    out: list[dict[str, object]] = []
    for n in article.findall("./AuthorList/Author"):
        ids = [{"source": x.get("Source"), "value": _text(x)} for x in n.findall("Identifier")]
        out.append({
            "last_name": _path(n, "LastName"), "fore_name": _path(n, "ForeName"),
            "initials": _path(n, "Initials"), "suffix": _path(n, "Suffix"),
            "collective_name": _path(n, "CollectiveName"),
            "affiliations": list(_unique([_text(x) for x in n.findall("./AffiliationInfo/Affiliation")])),
            "identifiers": ids,
            "valid": n.get("ValidYN"),
        })
    return tuple(out)


def _record(element: ET.Element) -> PubMedRecord:
    citation = element.find("MedlineCitation")
    if citation is None:
        raise PubMedMetadataError("PubMed record omitted MedlineCitation")
    pmid = _path(citation, "PMID")
    if pmid is None or not _PMID.fullmatch(pmid):
        raise PubMedMetadataError("PubMed record omitted a canonical PMID")
    article = citation.find("Article")
    if article is None:
        # A MEDLINE status is not enough to fabricate an article's metadata.
        raise PubMedMetadataError("PubMed record omitted Article metadata")
    journal = article.find("Journal")
    issue = journal.find("JournalIssue") if journal is not None else None
    identifiers: dict[str, list[str]] = {"pmid": [pmid]}
    for n in element.findall("./PubmedData/ArticleIdList/ArticleId"):
        kind, value = n.get("IdType"), _text(n)
        if kind == "pubmed" and value != pmid:
            raise PubMedMetadataError("Conflicting PubMed PMID identifiers")
        if kind and value:
            identifiers.setdefault(kind, []).append(value)
    for n in article.findall("ELocationID"):
        kind, value = n.get("EIdType"), _text(n)
        if kind and value:
            identifiers.setdefault(kind, []).append(value)
    abstracts: list[dict[str, str | None]] = []
    abstract = article.find("Abstract")
    if abstract is not None:
        for n in abstract.findall("AbstractText"):
            value = _text(n)
            if value:
                abstracts.append({"label": n.get("Label"), "category": n.get("NlmCategory"), "text": value})
    other_abstracts: list[dict[str, object]] = []
    for other in citation.findall("OtherAbstract"):
        sections = []
        for text_node in other.findall("AbstractText"):
            value = _text(text_node)
            if value:
                sections.append({"label": text_node.get("Label"),
                                 "category": text_node.get("NlmCategory"), "text": value})
        other_abstracts.append({
            "type": other.get("Type"), "language": other.get("Language"),
            "sections": sections,
            "copyright": _path(other, "CopyrightInformation"),
        })
    dates: list[dict[str, str | None]] = []
    if journal is not None:
        pub = journal.find("./JournalIssue/PubDate")
        if pub is not None:
            dates.append(_date(pub, kind="journal_pub_date"))
    for n in article.findall("ArticleDate"):
        dates.append(_date(n, kind=f"article_{n.get('DateType') or 'date'}"))
    for n in element.findall("./PubmedData/History/PubMedPubDate"):
        dates.append(_date(n, kind=f"pubmed_history_{n.get('PubStatus') or 'unknown'}"))
    headings: list[dict[str, object]] = []
    for n in citation.findall("./MeshHeadingList/MeshHeading"):
        d = n.find("DescriptorName")
        quals = n.findall("QualifierName")
        headings.append({
            "descriptor": _text(d), "descriptor_ui": d.get("UI") if d is not None else None,
            "major_topic": d.get("MajorTopicYN") if d is not None else None,
            "qualifiers": [{"name": _text(x), "ui": x.get("UI"),
                            "major_topic": x.get("MajorTopicYN")} for x in quals],
        })
    journal_data: dict[str, str | None] = {
        "title": _path(journal, "Title") if journal is not None else None,
        "iso_abbreviation": _path(journal, "ISOAbbreviation") if journal is not None else None,
        "issn": _path(journal, "ISSN") if journal is not None else None,
        "volume": _path(issue, "Volume") if issue is not None else None,
        "issue": _path(issue, "Issue") if issue is not None else None,
        "pages": _path(article, "./Pagination/MedlinePgn"),
        "article_identifier": _path(article, "./Pagination/StartPage"),
    }
    return PubMedRecord(
        pmid=pmid, title=_path(article, "ArticleTitle"),
        abstract_sections=tuple(abstracts),
        abstract_status="present" if abstracts or any(x["sections"] for x in other_abstracts) else "not_supplied_in_response",
        abstract_copyright=_path(abstract, "CopyrightInformation") if abstract is not None else None,
        authors=_authors(article), journal=journal_data, publication_dates=tuple(dates),
        identifiers={k: _unique(v) for k, v in identifiers.items()},
        languages=_unique([_text(x) for x in article.findall("Language")]),
        publication_types=_unique([_text(x) for x in article.findall("./PublicationTypeList/PublicationType")]),
        keywords=_unique([_text(x) for x in citation.findall("./KeywordList/Keyword")]),
        mesh_headings=tuple(headings), citation_status=citation.get("Status"),
        other_abstracts=tuple(other_abstracts),
    )


def parse_efetch_xml(payload: bytes, expected_pmids: tuple[str, ...] | list[str],
                     *, retrieved_at_utc: str) -> PubMedMetadataBatch:
    """Reject malformed, missing, duplicate, unexpected and unsafe XML content."""
    pmids = validate_pmids(expected_pmids)
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_EFETCH_BYTES:
        raise PubMedMetadataError("PubMed EFetch returned an invalid or oversized response")
    # Explicitly accept UTF-8 only. Byte-level scans are bypassed by UTF-16
    # null interleaving; verify declarations on decoded Unicode before parsing.
    try:
        document = payload.decode("utf-8-sig")
    except UnicodeError:
        raise PubMedMetadataError("PubMed EFetch XML requires UTF-8") from None
    if re.search(r"<\!\s*ENTITY\b|<\!DOCTYPE\b[^>]*\[", document, flags=re.I):
        raise PubMedMetadataError("PubMed EFetch XML contains unsafe declarations")
    try:
        root = ET.fromstring(document)
    except (ET.ParseError, ValueError):
        raise PubMedMetadataError("PubMed EFetch returned malformed XML") from None
    if root.tag != "PubmedArticleSet":
        raise PubMedMetadataError("PubMed EFetch returned an unexpected document type")
    if sum(1 for _ in root.iter()) > MAX_XML_NODES:
        raise PubMedMetadataError("PubMed EFetch XML exceeds the element limit")
    records: list[PubMedRecord] = []
    for child in root:
        if child.tag != "PubmedArticle":
            raise PubMedMetadataError("PubMed EFetch returned an unsupported record type")
        records.append(_record(child))
    actual = tuple(r.pmid for r in records)
    if len(actual) != len(set(actual)) or set(actual) != set(pmids) or len(actual) != len(pmids):
        raise PubMedMetadataError("PubMed EFetch IDs do not match the requested batch")
    return PubMedMetadataBatch(
        requested_pmids=pmids, records=tuple(records),
        response_sha256=sha256(payload).hexdigest(), retrieved_at_utc=retrieved_at_utc,
    )


def _fetch_http(request: Request, timeout: float) -> bytes:
    with build_opener(_RejectRedirects()).open(request, timeout=timeout) as response:
        return response.read(MAX_EFETCH_BYTES + 1)


class PubMedEFetchClient:
    """Use the existing ESearch client's contact, key and shared NCBI pacing."""

    def __init__(self, esearch_client: PubMedESearchProbeClient, *,
                 transport: Callable[[Request, float], bytes] | None = None):
        if not isinstance(esearch_client, PubMedESearchProbeClient):
            raise TypeError("An authenticated/configured PubMed ESearch client is required")
        if transport is not None and not callable(transport):
            raise TypeError("EFetch transport must be callable")
        self._client = esearch_client
        self._transport = transport or _fetch_http

    def fetch(self, pmids: tuple[str, ...] | list[str]) -> PubMedMetadataBatch:
        identifiers = validate_pmids(pmids)
        values = {
            "db": "pubmed", "id": ",".join(identifiers), "retmode": "xml",
            "tool": self._client._tool, "email": self._client._email,
        }
        if self._client._api_key:
            values["api_key"] = self._client._api_key
        request = Request(
            EFETCH_URL, data=urlencode(values).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "RESEARCHY/0.1"},
            method="POST",
        )
        self._client._pace()  # shared NCBI rate limiter across ESearch and EFetch
        try:
            payload = self._transport(request, self._client._timeout)
        except HTTPError as exc:
            raise PubMedMetadataTransportError(
                f"PubMed EFetch HTTP {exc.code}; metadata not verified",
                retryable=exc.code in (429, 500, 502, 503, 504),
                http_status=exc.code,
            ) from None
        except (URLError, TimeoutError, OSError):
            raise PubMedMetadataTransportError("PubMed EFetch network error; metadata not verified",
                                               retryable=True) from None
        return parse_efetch_xml(payload, identifiers,
                                retrieved_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
