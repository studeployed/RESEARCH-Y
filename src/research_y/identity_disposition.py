"""Disposition of existing publication evidence when a researcher moves one original."""
from research_y import publication_identity as identity
from research_y.projects import _utc_now


def _specialist(source):
    raw=source["original_metadata"]
    roles=set()
    if source["source_name"]=="society" and raw.get("provider")=="manual_society_guidance":
        roles={(o["society_id"],role) for role,orgs in raw.get("society_roles",{}).items() for o in orgs}
    container=raw.get("container_id") if source["source_name"] in ("conference_jats","conference_pdf") else None
    return roles,{container} if container else set()


def describe(db,origin,target,rid,*,reverse=None):
    """Compute changes and fence both identities and all annotation rows behind the preview."""
    if origin.publication_id==target.publication_id:
        return None
    pid=origin.publication_id
    reviews=db.execute("SELECT * FROM classifications WHERE publication_id=? ORDER BY classification_id",(pid,)).fetchall()
    docs=db.execute("SELECT * FROM documents WHERE publication_id=? ORDER BY document_id",(pid,)).fetchall()
    roles=set(db.execute("SELECT organisation_id,role FROM publication_organisations WHERE publication_id=?",(pid,)))
    containers={r[0] for r in db.execute("SELECT container_id FROM publication_containers WHERE publication_id=?",(pid,))}
    source=next(s for s in origin.retrievals if s["retrieval_id"]==rid)
    moved_roles,moved_containers=_specialist(source)
    if moved_roles-roles or moved_containers-containers:
        raise identity.PublicationIntegrityError("Specialist source has lost its publication links")
    keep_roles,keep_containers=set(),set()
    old=(reverse or {}).get("disposition") or {}
    keep_roles.update(tuple(pair) for pair in old.get("existing_target_roles",[]))
    keep_containers.update(old.get("existing_target_containers",[]))
    for s in origin.retrievals:
        if s["retrieval_id"]!=rid:
            rs,cs=_specialist(s)
            keep_roles.update(rs)
            keep_containers.update(cs)
    fields={name:v["event_id"] for name,v in origin.chosen_fields.items() if v["provenance"]["retrieval_id"]==rid}
    # A prior move may have preserved a destination choice instead of applying
    # the original value. Return that recorded choice if its old slot is free.
    restore=old.get("skipped_fields",{})
    if not (reviews or docs or roles or containers or fields or restore):
        return None
    proposals={**restore,**fields}
    target_roles=set(db.execute("SELECT organisation_id,role FROM publication_organisations WHERE publication_id=?",
                                (target.publication_id,)))
    target_containers={r[0] for r in db.execute("SELECT container_id FROM publication_containers WHERE publication_id=?",
                                                (target.publication_id,))}
    state=dict(origin=pid,target=target.publication_id,retrieval_id=rid,sole_source=len(origin.retrievals)==1,
               classification_ids=[r[0] for r in reviews],document_ids=[r[0] for r in docs],
               clear_fields=fields,apply_fields={k:v for k,v in proposals.items() if k not in target.chosen_fields},
               skipped_fields={k:v for k,v in proposals.items() if k in target.chosen_fields},
               add_roles=sorted(moved_roles),remove_roles=sorted(moved_roles-keep_roles),
               existing_target_roles=sorted(target_roles&moved_roles),
               existing_target_containers=sorted(target_containers&moved_containers),
               add_containers=sorted(moved_containers),remove_containers=sorted(moved_containers-keep_containers),
               retained_roles=sorted(roles-(moved_roles-keep_roles)),
               retained_containers=sorted(containers-(moved_containers-keep_containers)))
    state["sha256"]=identity._hash([state,origin.revision,target.revision,reviews,docs])
    return state


def summary(plan):
    if plan is None:
        return None
    return dict(origin=plan["origin"],target=plan["target"],sha256=plan["sha256"],sole_source=plan["sole_source"],
                classifications=len(plan["classification_ids"]),documents=len(plan["document_ids"]),
                apply_fields=sorted(plan["apply_fields"]),keep_target_fields=sorted(plan["skipped_fields"]),
                roles=len(plan["add_roles"]),containers=len(plan["add_containers"]),
                retained_roles=len(plan["retained_roles"]),retained_containers=len(plan["retained_containers"]))


def _field_change(db,pid,name,original_id,action,actor,reason):
    original=identity._event(db,original_id,identity.FIELD_EVENT)
    row=db.execute("SELECT chosen_metadata_json FROM publications WHERE publication_id=?",(pid,)).fetchone()
    state=identity._field_state(db,pid,row[0])
    fields=dict(state["fields"])
    prior=fields.pop(name,None)
    if action=="clear" and prior!=original_id or action=="select" and prior is not None:
        raise identity.StalePublicationError("Chosen field changed during identity review")
    event=dict(version=1,at_utc=_utc_now(),action=action,method="reviewed-identity-disposition/1",publication_id=pid,
               field=name,actor=actor,reason=reason,previous_head_event_id=state["head_event_id"],
               previous_field_event_id=prior,after_fields=fields,original_choice_event_id=original_id)
    if action=="select":
        event.update({key:original[key] for key in ("retrieval_id","source_sha256","path")})
    eid=identity._audit(db,identity.FIELD_EVENT,event)
    if action=="select":
        fields[name]=eid
    db.execute("UPDATE publications SET chosen_metadata_json=? WHERE publication_id=?",
               (identity._json(dict(version=1,head_event_id=eid,fields=fields)),pid))


def apply(db,origin,target,rid,digest,actor,evidence,*,reverse=None):
    plan=describe(db,origin,target,rid,reverse=reverse)
    if not plan or plan["sha256"]!=digest:
        raise identity.StalePublicationError("Review the changed annotation disposition")
    donor,dest=plan["origin"],plan["target"]
    for name,eid in plan["clear_fields"].items():
        _field_change(db,donor,name,eid,"clear",actor,evidence)
    for name,eid in plan["apply_fields"].items():
        _field_change(db,dest,name,eid,"select",actor,evidence)
    for org,role in plan["add_roles"]:
        db.execute("INSERT OR IGNORE INTO publication_organisations VALUES(?,?,?)",(dest,org,role))
    for org,role in plan["remove_roles"]:
        db.execute("DELETE FROM publication_organisations WHERE publication_id=? AND organisation_id=? AND role=?",
                   (donor,org,role))
    for container in plan["add_containers"]:
        db.execute("INSERT OR IGNORE INTO publication_containers VALUES(?,?)",(dest,container))
    for container in plan["remove_containers"]:
        db.execute("DELETE FROM publication_containers WHERE publication_id=? AND container_id=?",(donor,container))
    return plan


def historical_annotations(db,snapshot):
    """Read original attribution for publication evidence explicitly retained on a former identity."""
    rows=[]
    seen=set()
    for source in snapshot.retrievals:
        eid=source["association_event_id"]
        while eid is not None:
            event=identity._event(db,eid,identity.IDENTITY_EVENT)
            if event["retrieval_id"]!=source["retrieval_id"]:
                raise identity.PublicationIntegrityError("Identity history changed")
            plan=event.get("disposition")
            if plan and plan["sole_source"] and plan["origin"]!=snapshot.publication_id and eid not in seen:
                seen.add(eid)
                reviews=[]
                for cid in plan["classification_ids"]:
                    row=db.execute("SELECT dimension,label,review_status FROM classifications WHERE classification_id=? "
                                   "AND publication_id=?",(cid,plan["origin"])).fetchone()
                    if not row:
                        raise identity.PublicationIntegrityError("Retained classification missing")
                    reviews.append(dict(dimension=row[0],label=row[1],status=row[2]))
                documents=[]
                for did in plan["document_ids"]:
                    row=db.execute("SELECT relative_path,external_url FROM documents WHERE document_id=? AND "
                                   "publication_id=?",(did,plan["origin"])).fetchone()
                    if not row:
                        raise identity.PublicationIntegrityError("Retained document missing")
                    documents.append(dict(document_id=did,relative_path=row[0],source_url=row[1]))
                rows.append(dict(event_id=eid,origin=plan["origin"],actor=event["actor"],reason=event["evidence"],
                                 classifications=reviews,documents=documents,prior_fields=list(plan["skipped_fields"]),
                                 retained_roles=plan["retained_roles"],retained_containers=plan["retained_containers"]))
            next_event=event.get("previous_event_id")
            if next_event is not None and identity._positive(next_event)>=eid:
                raise identity.PublicationIntegrityError("Nonchronological identity history")
            eid=next_event
    return rows
