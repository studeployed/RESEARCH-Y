import json
from urllib.parse import parse_qs

import pytest

from scripts import pubmed_metadata_recovery_validation as driver
from test_pubmed_metadata import response


def configured(stage, batches, *, count=3, translate=True):
    def search(request, timeout):
        form = parse_qs(request.data.decode())
        size = int(form["retmax"][0])
        term = form["term"][0]
        return json.dumps({"esearchresult": {
            "count": str(count), "retmax": str(size), "retstart": "0",
            "idlist": [str(111+number) for number in range(size)],
            "querytranslation": term if translate else '"ECMO"[MeSH Terms]'}}).encode()

    def fetch(request, timeout):
        pmids = parse_qs(request.data.decode())["id"][0].split(",")
        batches.append(pmids)
        return response(*pmids)

    client = driver.SampleClient(stage, email="fixture@example.org", transport=search, sleep=lambda _: None)
    return client, driver.SampleEFetch(client, transport=fetch)


def test_checked_or_and_durable_complete_sample(tmp_path):
    workspace = tmp_path / "runner"
    batches = []
    driver.start(workspace, *configured("start", batches))
    outcome = driver.resume(workspace, *configured("resume", batches))
    assert batches == [["111"], ["112", "113"]]
    assert outcome["metadata"] == outcome["identifiers"] == 3
    assert outcome["first_record_skipped_on_resume"] and outcome["checked_phrase_translation"]
    assert outcome["requests"] <= 10 and not outcome["source_retrieval_verified"]
    public = (workspace / driver.EVIDENCE).read_text()
    assert all(value not in public for value in ("fixture@example.org", "ventricular study", '"111"'))


@pytest.mark.parametrize("count,translate", [(21, True), (1, True), (3, False)])
def test_unverified_or_outside_budget_refuses_before_metadata(tmp_path, count, translate):
    batches = []
    with pytest.raises(ValueError):
        driver.start(tmp_path / "runner", *configured("start", batches, count=count, translate=translate))
    assert not batches and not (tmp_path / "runner" / driver.EVIDENCE).exists()
