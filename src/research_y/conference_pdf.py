"""Verify a researcher-selected abstract against text on one local PDF page."""
from hashlib import sha256
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit

from research_y.conference_jats import ConferenceInputError, _link


MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PAGE_CHARS = 100_000
METHOD = "pypdf-7.1.0-researcher-selected-page-text/1"


def read_page(payload, page):
    if (not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_PDF_BYTES
            or type(page) is not int or not 1 <= page <= 4096):
        raise ConferenceInputError("Select a local PDF up to 32 MiB and a page from 1 to 4096")
    try:
        from pypdf import PdfReader, apply_configuration
    except ImportError:
        raise ConferenceInputError("The optional PDF reader is unavailable") from None
    try:
        with apply_configuration(
            page_tree_maximum_entries=8192, page_tree_maximum_page_entries=100_000,
            page_tree_maximum_depth=64, maximum_declared_stream_length=8_000_000,
            array_based_stream_maximum_output_length=8_000_000, zlib_maximum_output_length=8_000_000,
            lzw_maximum_output_length=8_000_000, run_length_maximum_output_length=8_000_000,
            brotli_maximum_output_length=8_000_000, stream_decoding_work_maximum_length=32_000_000,
            stream_parsing_work_maximum_count=200_000, xform_maximum_invocations_per_extraction=128,
            jbig2dec_binary=None, disable_legacy_handling=True,
        ):
            reader = PdfReader(BytesIO(payload),strict=True)
            if reader.is_encrypted:
                raise ConferenceInputError("Password-protected PDF requires manual verification")
            total = len(reader.pages)
            if total > 4096 or page > total:
                raise ConferenceInputError("Page outside the supported document range")
            text = " ".join(reader.pages[page-1].extract_text().split())
            if len(text)>MAX_PAGE_CHARS:
                raise ConferenceInputError("Page text exceeds the review limit")
    except ConferenceInputError:
        raise
    except Exception:
        raise ConferenceInputError("PDF page could not be read within the supported limits") from None
    return dict(document_sha256=sha256(payload).hexdigest(), page=page, total_pages=total, text=text,
                status="text_available" if text else "no_extractable_text")


def select_block(view, *, title, excerpt, printed_page=None, pdf_url=None, authors=(), number=None):
    if view["status"] != "text_available":
        raise ConferenceInputError("This page has no extractable text")
    if not isinstance(title,str) or not isinstance(excerpt,str):
        raise ConferenceInputError("Select an abstract title and passage")
    title, excerpt = " ".join(title.split()), " ".join(excerpt.split())
    text = view["text"]
    start = text.find(excerpt)
    if (not title or len(title)>2048 or not excerpt or len(excerpt)>40_000 or title not in excerpt
            or start < 0 or text.find(excerpt,start+1) >= 0):
        raise ConferenceInputError("Select a unique contiguous passage containing its exact title")
    for field in (printed_page,number):
        if field is not None and (not isinstance(field,str) or not field.strip() or len(field)>128):
            raise ConferenceInputError("Invalid printed label or abstract number")
    if (not isinstance(authors,(list,tuple)) or len(authors)>128 or
            any(not isinstance(a,str) or not a.strip() or len(a)>500 or a not in excerpt for a in authors)):
        raise ConferenceInputError("Each selected author must appear in the verified passage")
    if pdf_url is not None and _link(pdf_url) is None:
        raise ConferenceInputError("Invalid supplement PDF URL")
    page = view["page"]
    end = start + len(excerpt)
    locator = f"pdf:page={page};text={start}-{end}"
    block = dict(locator=locator,title=title,text=excerpt,text_start=start,text_end=end,authors=list(authors),number=number,
                 printed_first_page=printed_page,printed_last_page=None,pdf_page=page,
                 pdf_page_url=urlunsplit(urlsplit(pdf_url)._replace(fragment=f"page={page}")) if pdf_url else None,
                 supplement_pdf_url=pdf_url,individual_dois=[],matched_terms=[],warnings=[])
    for name,value in (("printed_page",printed_page),("individual_doi",None)):
        if not value:
            block["warnings"].append("missing_"+name)
    return dict(source_sha256=view["document_sha256"], container={"pdf_file_pages":view["total_pages"]},
                abstracts=[block], unresolved=[])
