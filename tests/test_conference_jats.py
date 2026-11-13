from hashlib import sha256
import json

import pytest

from research_y.conference_jats import ConferenceInputError, inspect_conference_jats
from scripts.inspect_conference_jats import main


XML = b"""<article xmlns:xlink="http://www.w3.org/1999/xlink">
<front><journal-meta><journal-title-group><journal-title>Demo Journal</journal-title></journal-title-group></journal-meta>
<article-meta><article-id pub-id-type="doi">10.1234/supp</article-id>
<title-group><article-title>Demo proceedings</article-title></title-group>
<pub-date><year>2025</year></pub-date><volume>9</volume><issue>2</issue><supplement>A</supplement>
<conference><conf-name>Demo meeting</conf-name><conf-date>February 2025</conf-date></conference>
</article-meta></front>
<sub-article article-type="meeting-abstract" id="a"><front-stub>
<article-id pub-id-type="doi">10.1234/supp</article-id><title-group><article-title>Short abstract</article-title></title-group>
<contrib-group><contrib contrib-type="author"><name><surname>Doe</surname><given-names>R.</given-names></name></contrib></contrib-group>
<fpage>S3</fpage><lpage>S4</lpage><elocation-id>P12</elocation-id>
<self-uri xlink:href="https://example.test/abstract/P12"/>
<abstract><p>Right <italic>ventricle</italic> assessment.</p><p>Rehabilitation.</p></abstract></front-stub></sub-article>
<sub-article article-type="conference-abstract" id="b"><front-stub>
<article-id pub-id-type="doi">10.1234/report</article-id>
<title-group><article-title>Short abstract</article-title></title-group></front-stub>
<body><p>ECMO activity.</p></body></sub-article>
<sub-article article-type="editorial" id="ed"><body><p>ECMO right ventricle</p></body></sub-article>
</article>"""


def test_separate_original_abstracts_with_local_matches_source_ids_and_independent_page_locators():
    output = inspect_conference_jats(XML, terms=["right ventricle", "ECMO", "ventricle ECMO", "EC"],
                                     landing_url="https://example.test/proceedings",
                                     pdf_url="https://example.test/proceedings.pdf#old", pdf_pages={"a": 8})
    assert output["source_sha256"] == sha256(XML).hexdigest()
    assert output["container"]["identifiers"] == [{"type": "doi", "value": "10.1234/supp"}]
    assert output["container"]["journal"] == "Demo Journal" and output["container"]["supplement"] == "A"
    a, b = output["abstracts"]
    assert a["matched_terms"] == ["right ventricle"] and b["matched_terms"] == ["ECMO"]
    assert a["title"] == b["title"] and a["locator"] != b["locator"]
    assert a["individual_dois"] == [] and "doi_shared_with_container" in a["warnings"]
    assert b["individual_dois"] == ["10.1234/report"]
    assert a["text"] == "Right ventricle assessment.\nRehabilitation." and b["text"] == "ECMO activity."
    assert a["authors"] == ["R. Doe"] and a["number"] == "P12"
    assert a["printed_first_page"] == "S3" and a["printed_last_page"] == "S4" and a["pdf_page"] == 8
    assert a["individual_url"] == "https://example.test/abstract/P12"
    assert a["pdf_page_url"] == "https://example.test/proceedings.pdf#page=8"
    assert b["pdf_page_url"] is None and "missing_pdf_page" in b["warnings"]
    assert b["conference"] == "Demo meeting" and b["conference_date"] == "February 2025"
    assert output["unresolved"] == [{"locator": "/article/sub-article[3]", "reason": "unclassified_sub_article"}]


def test_missing_metadata_and_duplicate_ids_require_review_without_guessing_a_page():
    xml = XML.replace(b'id="b"', b'id="a"')
    a, b = inspect_conference_jats(xml)["abstracts"]
    assert "unresolved_individual_identity" in a["warnings"]
    assert a["pdf_page"] is None and a["printed_first_page"] == "S3"
    with pytest.raises(ConferenceInputError, match="unique abstract"):
        inspect_conference_jats(xml, pdf_pages={"a": 5})
    empty = inspect_conference_jats(b"<article><front><article-meta/></front></article>")
    assert empty["abstracts"] == [] and empty["unresolved"][0]["reason"] == "no_explicit_sub_articles"


def test_nested_boundaries_are_reported_without_claiming_the_nested_item_text():
    xml = XML.replace(b'<p>ECMO activity.</p>', b'<sub-article><body><p>ECMO</p></body></sub-article>')
    output = inspect_conference_jats(xml, terms=["ECMO"])
    assert len(output["abstracts"]) == 1 and output["abstracts"][0]["matched_terms"] == []
    assert {"locator": "/article/sub-article[2]", "reason": "nested_sub_articles_require_review"} in output["unresolved"]


def test_mixed_text_table_and_list_stay_with_their_original_abstract():
    xml = XML.replace(b"<p>ECMO activity.</p>",
                      b"Lead <italic>in</italic>.<p>Introduction.</p><table-wrap><caption>Results</caption>"
                      b"<table><tr><td>ECMO</td><td>12</td></tr></table></table-wrap>"
                      b"<list><list-item>Recovery</list-item></list>Following text.")
    a, b = inspect_conference_jats(xml, terms=["ECMO", "Recovery"])["abstracts"]
    assert b["text"].splitlines() == ["Lead in.", "Introduction.", "Results", "ECMO", "12", "Recovery", "Following text."]
    assert b["matched_terms"] == ["ECMO", "Recovery"] and a["matched_terms"] == []


def test_front_abstract_and_body_are_both_retained_inside_subarticle():
    xml = XML.replace(b"</title-group></front-stub>", b"</title-group><abstract><p>Preliminary findings.</p></abstract></front-stub>")
    a, b = inspect_conference_jats(xml, terms=["ECMO", "Preliminary findings"])["abstracts"]
    assert b["text"] == "Preliminary findings.\nECMO activity."
    assert b["matched_terms"] == ["ECMO", "Preliminary findings"] and a["matched_terms"] == []


def test_indentation_in_inline_markup_does_not_break_phrase_matching():
    xml = XML.replace(b"<italic>ventricle", b"<italic>\n  ventricle")
    first = inspect_conference_jats(xml, terms=["right ventricle"])["abstracts"][0]
    assert first["text"] == "Right ventricle assessment.\nRehabilitation."
    assert first["matched_terms"] == ["right ventricle"]


def test_explicit_break_preserves_words_in_titles_and_abstracts():
    xml = XML.replace(b"Right <italic>ventricle</italic>", b"Right<break/>ventricle")
    xml = xml.replace(b"Short abstract", b"Short<break/>abstract")
    a, b = inspect_conference_jats(xml, terms=["Right ventricle", "Short abstract"])["abstracts"]
    assert a["title"] == b["title"] == "Short abstract"
    assert a["text"].startswith("Right ventricle") and a["matched_terms"] == ["Right ventricle", "Short abstract"]


def test_repeated_child_doi_is_ambiguous_even_if_missing_from_parent():
    xml = XML.replace(b'<article-id pub-id-type="doi">10.1234/supp</article-id>', b'', 1)
    xml = xml.replace(b'10.1234/report', b'10.1234/SUPP').replace(b' id="a"', b'').replace(b' id="b"', b'')
    a, b = inspect_conference_jats(xml)["abstracts"]
    for item in (a, b):
        assert not item["individual_dois"] and item["source_identifiers"][0]["value"].lower() == "10.1234/supp"
        assert {"unresolved_individual_identity", "doi_shared_across_sub_articles"} <= set(item["warnings"])


@pytest.mark.parametrize("url", ["file:///c:/a.pdf", "javascript:alert(1)", "https://x@y.test/",
                                 "https://example.test/\r\nx", "https://example.test:broken/"])
def test_untrusted_locator_schemes_credentials_and_controls_are_refused(url):
    with pytest.raises(ConferenceInputError, match="URL"):
        inspect_conference_jats(XML, pdf_url=url)


def test_invalid_documents_are_rejected_before_producing_any_abstract():
    for xml in (b'<article>', b'<sec/>', XML.decode().encode('utf-16'),
                b'<!DOCTYPE x [<!ENTITY s "data">]><article/>',
                b'<article>' + b'<s>' * 120 + b'</s>' * 120 + b'</article>'):
        with pytest.raises(ConferenceInputError):
            inspect_conference_jats(xml)


def test_local_preview_requires_unambiguous_supplied_page(tmp_path, capsys):
    source = tmp_path / "supp.xml"
    source.write_bytes(XML)
    main([str(source), "--term", "ECMO", "--pdf-page", "b", "9"])
    view = json.loads(capsys.readouterr().out)
    assert view["abstracts"][1]["pdf_page"] == 9 and view["abstracts"][1]["printed_first_page"] is None
    with pytest.raises(SystemExit):
        main([str(source), "--pdf-page", "b", "9", "--pdf-page", "b", "10"])
