"""Compare two retained run inventories without modifying either run or inferring withdrawals."""
from research_y import publication_identity as identity
from research_y import study_classification
from research_y.application_inspection import _read
from research_y.publication_candidates import _source_key
from research_y.projects import _utc_now,_validated_project_connection

NOTE = "researcher_publication_note_v1"
UPDATE_METHOD = "search_update_method_v1"


def latest_update_method(db, run_id):
    row = db.execute("SELECT event_id,details_json FROM audit_events WHERE event_type=? "
                     "AND json_extract(details_json,'$.run_id')=? ORDER BY event_id DESC LIMIT 1",
                     (UPDATE_METHOD,run_id)).fetchone()
    return dict(identity._object(row[1]),event_id=row[0]) if row else None


def record_update_method(project, run_id, *, earlier_run, method, actor, expected_event):
    identity._identifier(run_id)
    identity._text(method,4000)
    identity._text(actor,200)
    if earlier_run is not None:
        identity._identifier(earlier_run)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT created_at_utc FROM search_runs WHERE run_id=?", (run_id,)).fetchone()
        if not current:
            raise ValueError("Select a run")
        if earlier_run is not None and (earlier_run == run_id or not db.execute(
                "SELECT 1 FROM search_runs WHERE run_id=? AND created_at_utc<=?",
                (earlier_run,current[0])).fetchone()):
            raise ValueError("Select an earlier run from this project")
        prior = latest_update_method(db,run_id)
        fields = dict(run_id=run_id,earlier_run=earlier_run,actor=actor,method=method)
        if prior and all(prior[k]==v for k,v in fields.items()):
            return prior
        if (prior and prior["event_id"]) != expected_event:
            raise ValueError("The recorded update method changed. Reopen the run.")
        event = dict(fields,at_utc=_utc_now(),prior_event_id=expected_event)
        return dict(event,event_id=identity._audit(db,UPDATE_METHOD,event))


def _notes(db,project_source):
    key=identity._json(_source_key(project_source))
    return [dict(event_id=eid,**identity._object(raw)) for eid,raw in db.execute(
        "SELECT event_id,details_json FROM audit_events WHERE event_type=? AND json_extract(details_json,'$.key')=? "
        "ORDER BY event_id",(NOTE,key))]


def append_note(project,retrieval_id,*,actor,text,expected_event=None):
    identity._text(actor,200)
    identity._text(text,4000)
    with _validated_project_connection(project) as db:
        db.execute("BEGIN IMMEDIATE")
        source=identity._source(db,identity._identifier(retrieval_id))
        notes=_notes(db,source)
        previous=notes[-1] if notes else None
        if previous and (previous["actor"],previous["text"],previous["original_retrieval_id"])==(actor,text,retrieval_id):
            return previous["event_id"]
        if (previous and previous["event_id"])!=expected_event:
            raise ValueError("Note history has changed. Reopen the source record.")
        return identity._audit(db,NOTE,dict(version=1,at_utc=_utc_now(),actor=actor,text=text,
                      key=identity._json(_source_key(source)),original_retrieval_id=retrieval_id,
                      original_run_id=source["run_id"],original_source_sha256=source["source_sha256"]))


def _inventory(db,run):
    row=db.execute("SELECT s.status,v.version_number FROM search_runs s JOIN strategy_versions v "
                   "ON v.strategy_version_id=s.strategy_version_id WHERE s.run_id=?",(identity._identifier(run),)).fetchone()
    if not row:
        raise ValueError("Unknown comparison run")
    records={}
    for raw in db.execute("SELECT r.retrieval_id,r.run_id,r.source_name,r.source_record_id,r.retrieved_at_utc,"
                          "r.original_metadata_json,l.publication_id,l.decision_provenance_json,"
                          "a.event_id,a.event_type,a.occurred_at_utc,a.details_json FROM source_retrievals r "
                          "LEFT JOIN publication_retrievals l ON l.retrieval_id=r.retrieval_id "
                          "LEFT JOIN audit_events a ON a.event_id=json_extract(l.decision_provenance_json,'$.event_id') "
                          "WHERE r.run_id=? ORDER BY r.retrieval_id",(run,)):
        source=identity._source_from_row(raw[:6],row[0])
        key=tuple(_source_key(source))
        if key in records:
            raise ValueError("Repeated original source identifier in one run")
        if raw[6]:
            identity._link_from_evidence(source,raw[6],raw[7],raw[8:])
        payload=source["original_metadata"]
        record=payload.get("record",payload)
        fields={k:identity._hash(v) for k,v in record.items()}
        records[key]=dict(retrieval_id=raw[0],publication_id=raw[6],fields=fields)
    return dict(run_id=run,status=row[0],strategy_version=row[1]),records


def validate_carried_decision(db, publication_id, dimension, labels, evidence):
    if not isinstance(evidence,dict) or set(evidence)!={"previous_retrieval","current_retrieval","previous_publication",
                                                        "previous_revision","event_id"}:
        raise ValueError("Select one earlier classification and its two source records")
    previous = identity._source(db,identity._identifier(evidence["previous_retrieval"]))
    current = identity._source(db,identity._identifier(evidence["current_retrieval"]))
    old_link = identity._link(db,previous["retrieval_id"])
    new_link = identity._link(db,current["retrieval_id"])
    if (not old_link or not new_link or new_link[0]!=publication_id or old_link[0]==new_link[0]
            or old_link[0]!=evidence["previous_publication"] or _source_key(previous)!=_source_key(current)
            or previous["run_id"]==current["run_id"] or db.execute(
                "SELECT (SELECT created_at_utc FROM search_runs WHERE run_id=?) > "
                "(SELECT created_at_utc FROM search_runs WHERE run_id=?)",
                (previous["run_id"],current["run_id"])).fetchone()[0]):
        raise identity.StalePublicationError("The compared sources or publication associations changed")
    prior = study_classification._view(db,old_link[0])
    decision = prior["decisions"].get(dimension)
    if (not decision or prior["revision"]!=evidence["previous_revision"] or
            decision["event_id"]!=evidence["event_id"] or decision["labels"]!=labels):
        raise identity.StalePublicationError("Reopen the earlier classification before carrying it forward")


def _review_history(db, previous, current, cached):
    old_id = previous and previous["publication_id"]
    if not old_id or not db.execute("SELECT 1 FROM classifications WHERE publication_id=? LIMIT 1",(old_id,)).fetchone():
        return {}
    def view(pid):
        if pid not in cached:
            cached[pid] = study_classification._view(db,pid)
        return cached[pid]
    earlier = view(old_id)
    new_id = current and current["publication_id"]
    later = view(new_id) if new_id else None
    return dict(previous_revision=earlier["revision"],previous_decisions=earlier["decisions"],
                current_revision=later["revision"] if later else None,current_decisions=later["decisions"] if later else {},
                current_proposals=later["proposed"] if later else {})


def _publication_correspondence(old, new):
    earlier = {item["publication_id"] for item in old.values() if item["publication_id"]}
    later = {item["publication_id"] for item in new.values() if item["publication_id"]}
    forward = {pid:set() for pid in earlier}
    backward = {pid:set() for pid in later}
    for pid in earlier & later:
        forward[pid].add(pid)
        backward[pid].add(pid)
    missing_identity = set()
    for key in old.keys() & new.keys():
        left,right = old[key]["publication_id"],new[key]["publication_id"]
        if left and right:
            forward[left].add(right)
            backward[right].add(left)
        else:
            missing_identity.update(pid for pid in (left,right) if pid)
    old_only = sum(not peers and pid not in missing_identity for pid,peers in forward.items())
    new_only = sum(not peers and pid not in missing_identity for pid,peers in backward.items())
    shared = repeated = 0
    for pid,peers in forward.items():
        if len(peers)==1 and pid not in missing_identity:
            peer = next(iter(peers))
            if len(backward[peer])==1 and peer not in missing_identity:
                shared += pid==peer
                repeated += pid!=peer
    return dict(earlier_only=old_only,later_only=new_only,shared_publication_id=shared,
                distinct_ids_with_recurring_source=repeated,
                earlier_unresolved=len(earlier)-old_only-shared-repeated,
                later_unresolved=len(later)-new_only-shared-repeated)


def compare_runs(project, earlier, later, *, category="all",offset=0,page_size=25):
    if (earlier==later or category not in {"all","new","retained","absent","metadata_changed"} or
            type(offset) is not int or offset<0 or type(page_size) is not int or not 1<=page_size<=100):
        raise ValueError("Choose two distinct runs and a valid comparison page")
    with _read(project) as db:
        left,old=_inventory(db,earlier)
        right,new=_inventory(db,later)
        if db.execute("SELECT (SELECT created_at_utc FROM search_runs WHERE run_id=?) > "
                      "(SELECT created_at_utc FROM search_runs WHERE run_id=?)",(earlier,later)).fetchone()[0]:
            raise ValueError("Choose the earlier search run first")
        rows=[]
        reviewed={}
        counts=dict(new=0,retained=0,absent=0,metadata_changed=0)
        matched=0
        for key in sorted(old.keys()|new.keys()):
            previous,current=old.get(key),new.get(key)
            status="retained" if previous and current else "new" if current else "absent"
            counts[status]+=1
            changed=[]
            if previous and current:
                changed=sorted(k for k in previous["fields"].keys()|current["fields"].keys()
                               if previous["fields"].get(k)!=current["fields"].get(k))
                counts["metadata_changed"]+=bool(changed)
            if category not in ("all",status) and not (category=="metadata_changed" and changed):
                continue
            if offset<=matched<offset+page_size:
                linked = current or previous
                notes = _notes(db,identity._source(db,linked["retrieval_id"]))
                rows.append(dict(source=key[0],namespace=key[1],source_record_id=key[2],status=status,notes=notes,
                    changed_fields=changed,previous_retrieval=previous and previous["retrieval_id"],
                    classifications=_review_history(db,previous,current,reviewed),
                    current_retrieval=current and current["retrieval_id"],
                    previous_publication=previous and previous["publication_id"],
                    current_publication=current and current["publication_id"]))
            matched+=1
        old_pubs={v["publication_id"] for v in old.values() if v["publication_id"]}
        new_pubs={v["publication_id"] for v in new.values() if v["publication_id"]}
        return dict(earlier=left,later=right,category=category,offset=offset,matching=matched,page_size=page_size,
                    source_counts=counts,rows=rows,publication_identities=dict(new=len(new_pubs-old_pubs),
                    retained=len(new_pubs&old_pubs),absent=len(old_pubs-new_pubs)),
                    publication_correspondence=_publication_correspondence(old,new),
                    unlinked_sources=dict(earlier=sum(r["publication_id"] is None for r in old.values()),
                                          later=sum(r["publication_id"] is None for r in new.values())))
