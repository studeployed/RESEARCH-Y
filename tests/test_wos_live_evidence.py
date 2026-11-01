"""Historical aggregate evidence guards; no provider calls or record-level audit.

This freezes the reviewed report's scope and arithmetic. It does not recreate
licensed records, independently recompute their hashes, or replace live tests.
"""
from hashlib import sha256
import json
from pathlib import Path


SUMMARY = (Path(__file__).resolve().parents[1] / 'docs' / 'evidence'
           / 'wos-recovery-41306953908-summary.json')


def report():
    return json.loads(SUMMARY.read_text(encoding='utf-8'))


def test_retained_aggregate_audit_is_the_reviewed_report():
    # Normalise checkout line endings; original reviewed text uses LF.
    text = SUMMARY.read_text(encoding='utf-8')
    assert sha256(text.encode('utf-8')).hexdigest() == (
        '90ba97684c5bebe447697f3bc01d09aafee40adc1f560fcc7f32d4546c4b900f')
    audit = report()
    assert audit['artifact_id'] == 13083623977
    assert audit['artifact_zip_sha256'] == (
        'f41d86bc97a3a682b72dd1e83eaaccc74883a9a8ec43adec17d181da5c38549a')
    assert audit['evidence_file_sha256'] == (
        'cf113adbd7e60074400f69f4c6b871996d3c67c95761f1601792fb9e43be6aed')


def test_historical_run_source_and_commit_are_unambiguous():
    audit = report()
    result = audit['recorded_results']
    assert audit['run_id'] == 41306953908
    assert str(audit['run_id']) == result['github_run_id']
    assert audit['commit_sha'] == result['commit_sha'] == (
        'a4bb2b308aa96fe4076cde31efef668c23199173')
    assert audit['source_evidence_timestamp'] == result['checked_at_utc']
    assert result['source'] == 'Web of Science Starter'
    assert result['database'] == 'WOS'
    assert result['query'] == 'TS=("ECMO")'


def test_historical_page_and_record_counts_reconcile():
    result = report()['recorded_results']
    assert result['reported_matches'] == result['records_committed'] == 19584
    expected_pages = (result['reported_matches'] + 49) // 50
    assert expected_pages == 392
    assert result['pages_expected'] == result['pages_committed'] == expected_pages
    assert result['verification_pages'] == expected_pages


def test_historical_request_and_quota_accounting_reconcile():
    result = report()['recorded_results']
    assert result['request_purposes'] == {
        'acquire': 392, 'verify': 392, 'probe': 1, 'final': 1}
    assert sum(result['request_purposes'].values()) == 786
    assert result['requests_reserved'] == result['requests_confirmed_attempted'] == 786
    assert result['failures'] == result['requests_unknown'] == 0
    quota = result['quota']
    assert quota['valid'] is True
    assert quota['daily_limit'] == 5000
    assert quota['daily_remaining'] == 4214
    assert quota['daily_remaining'] + result['requests_confirmed_attempted'] == quota['daily_limit']


def test_controlled_restart_keeps_the_scoped_success_status():
    result = report()['recorded_results']
    assert result['first_page_unchanged'] is True
    assert result['acquisition_first_page_requests'] == 1
    assert result['durable_recovery_tested'] is True
    assert result['enumeration_reconciled'] is True
    assert result['stage_passed'] is True
    assert result['worker_active'] is False
    assert result['stage_executed'] == 'resume'
    assert result['stage'] == 'done'
    assert result['status'] == 'completed_with_warnings'
    assert result['reason_code'] == 'enumeration_reconciled_snapshot_unavailable'


def test_aggregate_audit_does_not_claim_unperformed_acceptance():
    audit = report()
    result = audit['recorded_results']
    for name in ('source_retrieval_verified', 'provider_snapshot_guaranteed',
                 'abstract_enrichment_complete', 'multi_day_live_tested',
                 'licensed_record_content_exported'):
        assert result[name] is False
    assert audit['checks_total'] == audit['checks_passed'] == len(audit['checks']) == 16
    assert all(value is True for value in audit['checks'].values())
    assert 'not independent recomputation' in audit['audit_scope']
    assert len(audit['limitations']) == 3
    assert 'cannot independently recompute' in audit['limitations'][0]
    # The summary intentionally omits even the aggregate artifact's page list.
    assert 'page_hashes' not in result
    assert 'response_json' not in result and 'records' not in result
