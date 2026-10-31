"""Offline Web of Science Starter contract/safety cases; no provider contact."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import pytest

from research_y.wos_starter import (MAX_RESPONSE_BYTES, WoSStarterError, WoSQuota,
    parse_document_page, parse_quota, validate_page_sequence, validate_request)
from research_y.wos_starter_client import (DOCUMENTS_URL, WoSHTTPResponse,
    WoSStarterClient, _RejectRedirects, _retry_after)

QUERY = 'TS=("ECMO")'
KEY = 'SYNTHETIC-ONLY-KEY'
STAMP = '2026-10-31T20:00:00+00:00'
HEADERS = {'X-RateLimit-Limit-Day': '5000', 'X-RateLimit-Remaining-Day': '4999',
           'X-RateLimit-Limit-Second': '5'}


def payload(total=103, page=1, limit=50, *, warning=False):
    records = [{"uid": f"WOS:{i+1:015d}", "title": f"Synthetic item {i+1}",
                "source": {"publishYear": 2026}, "identifiers": {"doi": f"10.0000/{i+1}"},
                "newSourceField": {"preserve": True}}
               for i in range((page-1)*limit, min(total, page*limit))]
    body = {"metadata": {"total": total, "page": page, "limit": limit}, "hits": records}
    if warning:
        body['warnings'] = ['Unexpected provider behavior']
    return body


def parse(body=None, *, page=1, limit=50, headers=HEADERS):
    data = json.dumps(payload(page=page, limit=limit) if body is None else body).encode()
    return parse_document_page(data, exact_query=QUERY, database='WOS', requested_page=page,
                               requested_limit=limit, retrieved_at_utc=STAMP, headers=headers)


class Clock:
    def __init__(self): self.value = 0.0; self.sleeps = []
    def now(self): return self.value
    def sleep(self, duration): self.sleeps.append(duration); self.value += duration


class Provider:
    def __init__(self, *, headers=HEADERS, total=103):
        self.headers = headers; self.total = total; self.requests = []
    def __call__(self, request, timeout):
        self.requests.append(request)
        q = parse_qs(urlsplit(request.full_url).query)
        return WoSHTTPResponse(200, self.headers,
            json.dumps(payload(self.total, int(q['page'][0]), int(q['limit'][0]))).encode())


def client(provider=None, *, key=KEY, budget=3):
    clock = Clock()
    obj = WoSStarterClient(api_key=key, transport=provider or Provider(),
        request_budget=budget, clock=clock.now, sleep=clock.sleep,
        utc_now=lambda: datetime.fromisoformat(STAMP))
    return obj, clock


@pytest.mark.parametrize('query', ['TS=("ECMO")', 'TS=("right ventricle" OR "shock")',
    'TS=("AND" OR "patient (adult)")', 'TS=("évaluation")'])
def test_only_literal_topic_or_queries(query):
    validate_request(query, 'WOS', 1, 50)


@pytest.mark.parametrize('query', ['TS=(ECMO)', 'TI=("ECMO")', 'TS=("a" AND "b")',
    'TS=("a") NOT TS=("b")', 'TS=("*")', 'TS=("?")', 'TS=("$a")',
    'TS=("a\\b")', 'TS=("")', 'TS=("a\n")', ' TS=("a")', None, 4])
def test_reject_unapproved_query_syntax(query):
    with pytest.raises(WoSStarterError): validate_request(query, 'WOS', 1, 50)


@pytest.mark.parametrize(('page','limit'), [(0,50),(True,50),(1,51),(1,0),(1,True),(-1,1),(1.1,50)])
def test_invalid_bounds_do_not_become_different_queries(page,limit):
    with pytest.raises(WoSStarterError): validate_request(QUERY, 'WOS', page, limit)


def test_fifty_plus_fifty_plus_three_strict_contiguous_pages():
    pages = [parse(page=n) for n in (1,2,3)]
    ids = validate_page_sequence(pages)
    assert len(ids) == len(set(ids)) == 103
    assert pages[0].estimated_total_pages == 3
    assert pages[-1].records[-1].uid.endswith('103')
    assert not any(p.source_retrieval_verified for p in pages)
    assert pages[0].accepted_translation is None
    assert pages[0].translation_status == 'not_exposed_by_starter_contract'


def test_all_fields_preserved_independent_copy_missing_abstract_not_no_abstract():
    page = parse()
    record = page.records[0]
    first = record.as_dict()
    assert first['newSourceField'] == {'preserve': True}
    first['newSourceField']['preserve'] = False
    assert record.as_dict()['newSourceField']['preserve'] is True
    assert record.abstract_status == 'not_returned_by_source'
    assert record.rights_status == 'licence_review_required'
    assert len(page.response_sha256) == 64
    assert 'Synthetic item' not in repr(page)
    assert 'Synthetic item' not in repr(record)


def test_zero_is_distinct_from_failure():
    page = parse(payload(total=0))
    assert page.reported_matches == 0 and page.records == ()
    assert not page.source_retrieval_verified
    with pytest.raises(WoSStarterError): parse({'error': 'No access'})


@pytest.mark.parametrize('mutation', [
    lambda x: x['metadata'].update(total=True),
    lambda x: x['metadata'].update(total='103'),
    lambda x: x['metadata'].update(total=-1),
    lambda x: x['metadata'].update(page=2),
    lambda x: x['metadata'].update(limit=49),
    lambda x: x['hits'].pop(),
    lambda x: x['hits'].append(x['hits'][0]),
    lambda x: x['hits'][0].pop('uid'),
    lambda x: x['hits'][0].update(uid='WOS:bad\n'),
    lambda x: x['hits'][0].update(uid='MEDLINE:123'),
    lambda x: x['hits'][1].update(uid=x['hits'][0]['uid']),
    lambda x: x.update(error={'details': 'PRIVATE'}),
    lambda x: x.update(warnings=['partial response']),
    lambda x: x.update(metadata=None),
])
def test_malformed_truncated_duplicate_error_pages_fail_closed(mutation):
    data = payload(); mutation(data)
    with pytest.raises(WoSStarterError): parse(data)


@pytest.mark.parametrize('data', [b'{', b'[]', b'{"metadata":{},"metadata":{}}',
    b'{"metadata":{"total":NaN}}', b'\xff', b'x'*(MAX_RESPONSE_BYTES+1)],
    # pytest includes parameter IDs in PYTEST_CURRENT_TEST and error headings.
    # Never turn a multi-megabyte hostile payload into a test/environment name.
    ids=('truncated-json', 'wrong-root', 'duplicate-keys', 'nonfinite-number',
         'invalid-utf8', 'oversized-response'))
def test_invalid_json_and_size(data):
    with pytest.raises(WoSStarterError):
        parse_document_page(data, exact_query=QUERY, database='WOS', requested_page=1,
                            requested_limit=50, retrieved_at_utc=STAMP, headers=HEADERS)


def test_count_drift_gap_query_and_duplicate_rejected():
    one, two = parse(), parse(page=2)
    for altered in (replace(two, page=3), replace(two, reported_matches=104),
                    replace(two, exact_query='TS=("other")'),
                    replace(two, database='WOK'), replace(two, records=one.records)):
        with pytest.raises(WoSStarterError): validate_page_sequence([one,altered])


@pytest.mark.parametrize(('headers','status','continue_ok'), [
    ({}, 'unverified', False),
    ({'x-ratelimit-limit-day':'50','x-ratelimit-remaining-day':'49'},'below_required_institutional_allowance',False),
    ({'X-RateLimit-Remaining-Day':'4999'},'unverified',False),
    (HEADERS,'institutional_allowance_observed',True),
    ({**HEADERS,'X-RateLimit-Remaining-Day':'0'},'institutional_allowance_observed',False),
    ({**HEADERS,'X-RateLimit-Limit-Day':'20000'},'institutional_allowance_observed',True),
    ({'x-ratelimit-limit-year':'50000'},'unverified',False),
    ({**HEADERS,'X-RateLimit-Remaining-Day':'99999'},'unverified',False),
    ({**HEADERS,'X-RateLimit-Remaining-Day':'bad'},'unverified',False),
    ({**HEADERS,'x-ratelimit-limit-day':'50'},'unverified',False),
])
def test_entitlement_uses_actual_daily_limits(headers,status,continue_ok):
    observed = parse_quota(headers)
    assert observed.entitlement_status == status
    assert observed.can_continue is continue_ok


def test_key_header_only_fixed_origin_query_encoded_and_calls_paced():
    provider = Provider(); c, clock = client(provider)
    c.fetch_page('TS=("a + b" OR "c&d")',limit=1)
    c.fetch_page(QUERY,page=1,limit=50)
    c.fetch_page(QUERY,page=2,limit=50)
    assert c.requests_made == 3
    assert len(clock.sleeps) == 2 and all(t >= 1 for t in clock.sleeps)
    req = provider.requests[0]
    assert req.full_url.startswith(DOCUMENTS_URL+'?') and req.method == 'GET'
    assert req.get_header('X-apikey') == KEY
    assert KEY not in req.full_url
    form = parse_qs(urlsplit(req.full_url).query)
    assert form['q'] == ['TS=("a + b" OR "c&d")']
    assert set(form) == {'q','db','page','limit','sortField'}
    assert form['sortField'] == ['LD+A']
    with pytest.raises(WoSStarterError,match='budget'): c.fetch_page(QUERY)
    assert len(provider.requests) == 3


@pytest.mark.parametrize('headers', [{}, {'X-RateLimit-Limit-Day':'50'},
                                      {**HEADERS,'X-RateLimit-Remaining-Day':'0'}])
def test_access_probe_preserved_but_unverified_or_empty_quota_blocks_more(headers):
    provider = Provider(headers=headers); c, _ = client(provider)
    first = c.fetch_page(QUERY,limit=1)
    assert first.reported_matches == 103
    with pytest.raises(WoSStarterError,match='quota_or_entitlement'): c.fetch_page(QUERY)
    assert len(provider.requests) == 1


@pytest.mark.parametrize('status',[301,302,303,307,308,400,401,403,404,429,500,502,503,504])
def test_http_errors_static_and_no_implicit_retry(status):
    calls=[]
    def backend(req,timeout):
        calls.append(req)
        return WoSHTTPResponse(status,{**HEADERS,'Retry-After':'120'},b'SECRET PROVIDER ERROR')
    c, clock = client(backend)
    with pytest.raises(WoSStarterError) as err: c.fetch_page(QUERY)
    assert err.value.http_status == status
    assert err.value.retry_after_seconds == 120
    assert 'SECRET PROVIDER ERROR' not in str(err.value)
    with pytest.raises(WoSStarterError,match='retry_not_due'): c.fetch_page(QUERY)
    clock.value += 121
    with pytest.raises(WoSStarterError,match='revalidation'): c.fetch_page(QUERY)
    assert len(calls) == 1


def test_real_http_error_exception_and_network_error_are_sanitised():
    for error in (HTTPError(DOCUMENTS_URL,403,KEY,{},BytesIO()), URLError(KEY),
                  TimeoutError(KEY), OSError(KEY), ValueError(KEY)):
        def backend(req,timeout): raise error
        c, _ = client(backend)
        with pytest.raises(WoSStarterError) as failure: c.fetch_page(QUERY)
        assert KEY not in str(failure.value)
        assert c.requests_made == 1


def test_redirect_handler_never_sends_credentials_to_other_origin():
    assert _RejectRedirects().redirect_request(None,None,302,'',{},'http://evil.invalid') is None


@pytest.mark.parametrize('key', ['',None,'bad key','abc\nsecret','é','x'*4097],
    ids=('empty-key', 'missing-key', 'space-in-key', 'newline-in-key',
         'non-ascii-key', 'oversized-key'))
def test_invalid_keys_do_not_attempt_transport(key):
    with pytest.raises(WoSStarterError,match='api_key'): client(key=key)


@pytest.mark.parametrize('key', [KEY, 'key"quoted\\safe'])
def test_provider_credential_echo_never_returns_payload(key):
    def backend(req,timeout):
        body=payload();body['hits'][0]['newField']={'secret':key}
        return WoSHTTPResponse(200,HEADERS,json.dumps(body,ensure_ascii=True).encode())
    c,_=client(backend,key=key)
    with pytest.raises(WoSStarterError,match='credential_echo'): c.fetch_page(QUERY)


def test_retry_after_http_date_and_invalid_cases():
    now = datetime(2026,10,31,20,0,tzinfo=timezone.utc)
    assert _retry_after({'Retry-After':'Sat, 31 Oct 2026 20:01:00 GMT'},now)==60
    assert _retry_after({'retry-after':'abc'},now) is None
    assert _retry_after({'retry-after':'-1'},now) is None


def test_retry_after_on_success_still_delays_next_request():
    c, clock = client(Provider(headers={**HEADERS,'Retry-After':'30'}))
    c.fetch_page(QUERY,limit=1)
    with pytest.raises(WoSStarterError,match='retry_not_due'): c.fetch_page(QUERY)
    assert c.requests_made==1


@pytest.mark.parametrize('headers',[None,[],{'limit':123}])
def test_malformed_header_container_is_not_entitlement(headers):
    assert parse_quota(headers).entitlement_status=='unverified'


def test_response_type_failure_is_sanitised():
    for response in (None,WoSHTTPResponse(True,HEADERS,b''),WoSHTTPResponse(200,None,b'')):
        c,_=client(lambda request,timeout:response)
        with pytest.raises(WoSStarterError,match='transport_response'): c.fetch_page(QUERY)


def test_starter_collected_node_ids_are_bounded(request):
    """Keep raw test payloads out of Windows environment values and reports."""
    lengths = [len(item.nodeid) for item in request.session.items
               if item.path == request.node.path]
    # Check the identifiers pytest actually collected, not an alternate formatter.
    # Only lengths appear in a failure, never a hostile payload or giant name.
    assert lengths and max(lengths) <= 256, (
        f"Starter test identifiers must be compact; longest length: {max(lengths, default=0)}"
    )
