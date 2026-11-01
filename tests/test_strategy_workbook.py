"""Offline immutable-report and real XLSX rendering tests; synthetic data only."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import BytesIO
import json
from uuid import UUID
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pytest
from research_y import strategy_report as report
from research_y import strategy_workbook as renderer

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
STAMP = "2026-11-01T20:00:00+00:00"
P, R, S, Q = [str(UUID(int=i)) for i in range(1, 5)]


def payload():
    source = dict(source_name="pubmed", query_ids=[Q], reported_matches=None,
                  reported_count_status="unknown", retrieved_source_records=2,
                  metadata_source_records=1, identifiers_without_metadata=1,
                  numeric_reconciliation="unknown", retrieved_minus_reported=None,
                  source_retrieval_verified=False)
    counts = dict(project_id=P, run_id=R, strategy_version_id=S, stored_run_status="incomplete",
                  revision="a" * 64, status="incomplete", verified_complete=False,
                  deduplication_complete=False, source_retrieval_verified=False,
                  candidate_discovery_complete=False, historical_snapshot=False,
                  full_checkpoint_validation_performed=False, export_permissions_verified=False,
                  queries=[dict(query_id=Q, retrieved_source_records=2, metadata_source_records=1,
                                warnings=["identifiers_without_metadata"])],
                  groups=[dict(group_id="g", label="Group", sources=[source], publication_identities=1,
                               group_unique_publications=None, unmaterialised_retrievals=0)],
                  sources=[dict(source_name="pubmed", source_unique_records=2, metadata_source_records=1,
                                identifiers_without_metadata=1, queryless_source_records=0,
                                abstract_status_counts={"present": 1})],
                  totals=dict(global_publication_identities=1, group_publication_identity_sum=1,
                              global_unique_publications=None, extracted_individual_abstracts=None),
                  reviews={"current_confirmed_matches": 0}, warnings=["source_acceptance_not_established"])
    strategy = dict(format_version=1, theme="Synthetic theme", logic="OR", approved_by="Fixture",
                    groups=[dict(group_id="g", label="Group", group_order=0, terms=[
                        dict(text="ECMO", origin="researcher", rationale="", approved=True, enabled=True)])])
    return dict(format_version=1, method=report.REPORT_METHOD, software_version="0.1.0.dev0",
                captured_at_utc=STAMP, scope="whole_run_strategy_and_counts", status="incomplete",
                project={"project_id": P, "name": "Synthetic fixture"},
                run=dict(run_id=R, strategy_version_id=S, created_at_utc=STAMP, status="incomplete", completed_at_utc=None),
                strategy=dict(version_number=1, approved_at_utc=STAMP, snapshot=strategy, group_index=[["g", "Group", 0]]),
                counts=counts, queries=[dict(query_id=Q, group_id="g", source_name="pubmed", exact_query='"ECMO"[All Fields]',
                    parameters={}, reported_matches=None, status="pending", executed_at_utc=None,
                    execution_evidence="timestamp_not_recorded")], partitions=[], warnings=counts["warnings"])


def make(data=None):
    return report.StrategyReport(report.canonical(payload() if data is None else data))


def parts(content):
    with ZipFile(BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def cells(content, sheet=1):
    root = ET.fromstring(parts(content)[f"xl/worksheets/sheet{sheet}.xml"])
    result = {}
    for c in root.findall(".//s:c", NS):
        text = "".join(c.itertext())
        result[c.attrib["r"]] = (c.attrib.get("t"), text)
    return result


def test_genuine_zip_workbook_expected_sheets_and_safe_content():
    data = renderer.render_strategy_workbook(make())
    archive = parts(data)
    assert data[:4] == b"PK\x03\x04"
    workbook = ET.fromstring(archive["xl/workbook.xml"])
    names = [s.attrib["name"] for s in workbook.findall("s:sheets/s:sheet", NS)]
    assert names == ["Search Summary", "Source Totals", "Publication Counts", "Run Totals", "Search Terms",
                     "Executed Queries", "Query Partitions", "Warnings", "Methods", "Report Snapshot"]
    assert all("vba" not in n.lower() and "externallink" not in n.lower() for n in archive)
    for name, raw in archive.items():
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
            root = ET.fromstring(raw)
            assert root.find(".//s:f", NS) is None
            assert root.find(".//s:pane", NS).attrib["topLeftCell"] == "A5"
            assert root.find("s:autoFilter", NS) is not None
            assert "INCOMPLETE" in raw.decode()
        if name.endswith(".rels"):
            assert 'TargetMode="External"' not in raw.decode()


def test_unknown_zero_and_large_integer_exactness():
    data = payload()
    data["counts"]["groups"][0]["sources"][0]["reported_matches"] = 0
    data["counts"]["groups"][0]["sources"][0]["retrieved_source_records"] = 2**63 - 1
    x = cells(renderer.render_strategy_workbook(make(data)))
    assert x["D5"] == ("n", "0")
    assert x["F5"] == ("inlineStr", str(2**63 - 1))
    assert x["J5"] == ("inlineStr", "Unknown")
    assert x["G5"] == ("n", "1")


@pytest.mark.parametrize("literal", ["=1+1", "+SUM(A1:A2)", "-1+2", "@SUM(A1:A2)",
    "\t=HYPERLINK(\"https://invalid.example\")", "\n=1+1", "#DIV/0!", "https://invalid.example",
    "'=ordinary", "<xml>&\"text\"", "μg café 漢字 🧬"], ids=["equals", "plus", "minus", "at", "tab", "newline",
    "error-text", "url", "quote", "xml", "unicode"])
def test_user_values_are_exact_literal_text(literal):
    data = payload()
    data["queries"][0]["exact_query"] = literal
    actual = cells(renderer.render_strategy_workbook(make(data)), 6)["D5"]
    assert actual == ("inlineStr", literal)


def test_approved_and_disabled_terms_remain_visible():
    data = payload()
    terms = data["strategy"]["snapshot"]["groups"][0]["terms"]
    terms.append(dict(text="veno-venous", origin="deterministic", rationale="spelling variant", approved=True, enabled=False))
    x = cells(renderer.render_strategy_workbook(make(data)), 5)
    assert x["D6"][1] == "veno-venous"
    assert x["G6"] == ("b", "0")
    assert x["H6"][1] == "spelling variant"


def test_long_query_lossless_continuations_and_snapshot():
    data = payload()
    query = "=OR(" + "🧬alpha OR " * 7000 + ")"
    data["queries"][0]["exact_query"] = query
    frozen = make(data)
    content = renderer.render_strategy_workbook(frozen)
    assert cells(content, 6)["D5"][1] == "[Continued in Text Continuations: Executed Queries!D5]"
    archive = parts(content)
    continuations = ET.fromstring(archive["xl/worksheets/sheet11.xml"])
    rows = continuations.findall("s:sheetData/s:row", NS)[4:]
    joined = ""
    for row in rows:
        values = ["".join(c.itertext()) for c in row.findall("s:c", NS)]
        assert values[0] == "Executed Queries!D5"
        joined += values[3]
        assert values[4] == report.digest(query)
        assert len(values[3].encode("utf-16-le")) // 2 <= renderer.TEXT_UNITS
    assert joined == query
    snapcells = cells(content, 10)
    restored = "".join(snapcells[f"D{i}"][1] for i in range(5, 5 + len(renderer.text_parts(frozen.payload_json))))
    assert restored == frozen.payload_json
    assert report.digest(restored) == frozen.sha256


@pytest.mark.parametrize("length", [0, 1, 29999, 30000, 30001, 60000], ids=lambda n: f"chars-{n}")
def test_chunk_boundaries(length):
    value = "x" * length
    chunks = renderer.text_parts(value)
    assert "".join(chunks) == value
    assert all(len(p) <= renderer.TEXT_UNITS for p in chunks)


@pytest.mark.parametrize("char", ["\x00", "\x01", "\x0b", "\ud800", "\ufffe", "\uffff"],
                         ids=["null", "soh", "vertical-tab", "surrogate", "fffe", "ffff"])
def test_invalid_xml_text_refused_without_sanitising(char):
    with pytest.raises(renderer.WorkbookTextError):
        renderer.text_parts("prefix" + char)


def test_report_is_deeply_immutable_and_copies_are_independent():
    r = make()
    with pytest.raises(FrozenInstanceError):
        r.payload_json = "{}"
    copied = r.as_dict()
    copied["project"]["name"] = "CHANGED"
    assert r.as_dict()["project"]["name"] == "Synthetic fixture"


@pytest.mark.parametrize("mutation", ["run", "project", "strategy", "verified", "dedup", "scope", "status",
    "unapproved", "index", "logic", "duplicate-term", "bad-date", "naive-date", "version"], ids=str)
def test_inconsistent_or_overclaiming_snapshot_is_rejected(mutation):
    data = payload()
    if mutation in ("run", "project", "strategy"):
        key = {"run":"run_id", "project":"project_id", "strategy":"strategy_version_id"}[mutation]
        data["counts"][key] = str(UUID(int=999))
    elif mutation == "verified": data["counts"]["verified_complete"] = True
    elif mutation == "dedup": data["counts"]["deduplication_complete"] = True
    elif mutation == "scope": data["scope"] = "filtered"
    elif mutation == "status": data["status"] = "completed_verified"
    elif mutation == "unapproved": data["strategy"]["snapshot"]["groups"][0]["terms"][0]["approved"] = False
    elif mutation == "index": data["strategy"]["group_index"][0][1] = "Wrong group"
    elif mutation == "logic": data["strategy"]["snapshot"]["logic"] = "AND"
    elif mutation == "duplicate-term": data["strategy"]["snapshot"]["groups"][0]["terms"] *= 2
    elif mutation == "bad-date": data["captured_at_utc"] = "not a date"
    elif mutation == "naive-date": data["captured_at_utc"] = "2026-11-01T20:00:00"
    elif mutation == "version": data["format_version"] = True
    with pytest.raises(report.ReportIntegrityError): make(data)


def test_duplicate_keys_and_noncanonical_encoding_rejected():
    with pytest.raises(report.ReportIntegrityError): report.decode('{"a":1,"a":2}')
    with pytest.raises(report.ReportIntegrityError): report.StrategyReport(json.dumps(payload()))


def test_oversized_input_and_sheet_limits_refuse_output(monkeypatch):
    monkeypatch.setattr(report, "MAX_REPORT_BYTES", 10)
    with pytest.raises(report.ReportIntegrityError): make()
    monkeypatch.undo()
    monkeypatch.setattr(renderer, "ROW_LIMIT", 8)
    with pytest.raises(renderer.WorkbookLimitError): renderer.render_strategy_workbook(make())
    monkeypatch.undo()
    monkeypatch.setattr(renderer, "COLUMN_LIMIT", 1)
    with pytest.raises(renderer.WorkbookLimitError): renderer.render_strategy_workbook(make())


def test_wrong_object_and_cell_types_rejected():
    with pytest.raises(TypeError): renderer.render_strategy_workbook({})
    data = payload()
    data["counts"]["totals"]["bad"] = 1.2
    with pytest.raises(TypeError): renderer.render_strategy_workbook(make(data))


def test_optional_backend_missing_is_explicit(monkeypatch):
    import builtins
    original = builtins.__import__
    def importing(name, *a, **kw):
        if name == "openpyxl": raise ImportError("test only")
        return original(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", importing)
    with pytest.raises(RuntimeError, match="optional Excel"):
        renderer.render_strategy_workbook(make())


def test_render_does_not_write_user_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = renderer.render_strategy_workbook(make())
    assert content and list(tmp_path.iterdir()) == []


def test_frozen_capture_bytes_survive_later_input_changes():
    data = payload()
    frozen = make(data)
    data["queries"][0]["exact_query"] = "CHANGED"
    assert cells(renderer.render_strategy_workbook(frozen), 6)["D5"][1] == '"ECMO"[All Fields]'
