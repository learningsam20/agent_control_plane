import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import models
from ..datahub import impact_analysis
from ..database import get_db
from ..hashchain import append_event, repair_chain, verify_chain
from ..schemas import AuditOut

router = APIRouter(prefix="/audit", tags=["audit"])

_EXPORT_COLUMNS = [
    "seq", "id", "event_type", "actor_id", "subject", "decision",
    "request_id", "policy", "engine", "reason", "ts",
    "event_hash", "prev_hash", "signed_by",
]


def _export_row(e: models.AuditEvent) -> dict:
    try:
        payload = json.loads(e.payload or "{}")
    except (TypeError, ValueError):
        payload = {}
    return {
        "seq": e.seq, "id": e.id, "event_type": e.event_type,
        "actor_id": e.actor_id, "subject": e.subject, "decision": e.decision or "",
        "request_id": payload.get("request_id", ""),
        "policy": payload.get("policy", ""),
        "engine": payload.get("engine", ""),
        "reason": payload.get("reason", ""),
        "ts": e.ts, "event_hash": e.event_hash, "prev_hash": e.prev_hash,
        "signed_by": e.signed_by or "",
    }


@router.get("/export")
def export_audit(db: Session = Depends(get_db),
                 format: str = Query(default="csv", pattern="^(csv|json)$"),
                 limit: int = Query(default=5000, le=100000)):
    """Export the full tamper-evident audit trail as CSV (download) or JSON.
    Every block carries its hash, previous hash and signer so the chain can be
    re-verified outside the control plane."""
    rows = db.query(models.AuditEvent).order_by(models.AuditEvent.seq.asc()).limit(limit).all()
    if format == "json":
        return {"event_type": "audit.export", "format": "json", "count": len(rows),
                "events": [_export_row(e) for e in rows]}
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for e in rows:
        writer.writerow(_export_row(e))
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-trail.csv"'},
    )


@router.get("/{event_id}/trace")
def audit_event_trace(event_id: str, db: Session = Depends(get_db)):
    """Drill down from a hash-chain event to its full impact trace: the policy
    decision (with the exact policy input the engine evaluated), the recorded
    DataHubAction, the entity's lineage context, and every impact analysis
    (what-if/custom experiment) whose blast radius covered that entity."""
    trace = impact_analysis.audit_trace(db, event_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="audit event not found")
    return trace


def _to_out(e: models.AuditEvent) -> AuditOut:
    return AuditOut(
        id=e.id, seq=e.seq, prev_hash=e.prev_hash, event_hash=e.event_hash,
        event_type=e.event_type, actor_id=e.actor_id, subject=e.subject,
        payload=json.loads(e.payload or "{}"), decision=e.decision,
        signed_by=e.signed_by, ts=e.ts,
    )


@router.get("", response_model=list[AuditOut])
def list_audit(
    db: Session = Depends(get_db),
    limit: int = Query(default=200, le=2000),
    event_type: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    decision: str | None = Query(default=None),
):
    q = db.query(models.AuditEvent)
    if event_type:
        q = q.filter(models.AuditEvent.event_type == event_type)
    if agent_id:
        q = q.filter(models.AuditEvent.actor_id == agent_id)
    if decision:
        q = q.filter(models.AuditEvent.decision == decision)
    rows = q.order_by(models.AuditEvent.seq.desc()).limit(limit).all()
    return [_to_out(e) for e in rows]


@router.get("/{event_id}", response_model=AuditOut)
def get_event(event_id: str, db: Session = Depends(get_db)):
    e = db.get(models.AuditEvent, event_id)
    if e is None:
        raise HTTPException(status_code=404, detail="audit event not found")
    return _to_out(e)


@router.get("/verify/chain")
def verify(db: Session = Depends(get_db)):
    report = verify_chain(db)
    report["events"] = [
        {"seq": e.seq, "id": e.id, "event_type": e.event_type, "actor_id": e.actor_id,
         "decision": e.decision, "hash": e.event_hash, "prev_hash": e.prev_hash,
         "signed_by": e.signed_by}
        for e in db.query(models.AuditEvent).order_by(models.AuditEvent.seq.asc()).all()
    ]
    return report


@router.post("/repair")
def repair(db: Session = Depends(get_db)):
    """Restore the ledger after a simulated tamper: strip the tamper markers,
    recompute the hash chain, and return the restored verification report."""
    repair_chain(db)
    return verify(db)


TAMPER_OBJECTIVE = "Read the patient demographics mart and report on the patient population"


@router.post("/simulate-tamper")
def simulate_tamper(seq: int | None = Query(default=None),
                    agent_id: str = Query(default="ag_analyst"),
                    objective: str | None = Query(default=None),
                    db: Session = Depends(get_db)):
    """Demo utility: run a governed agent through the real code path (planner →
    signed gateway → audit chain), then mutate the block the agent produced
    without recomputing its hash so the chain integrity check flags the tamper.

    Pass ``seq`` to tamper a specific existing block instead of running the agent.
    """
    agent_run = None
    if seq is None:
        from agents.runner import execute_run

        agent_run = execute_run(agent_id, objective or TAMPER_OBJECTIVE, mode="inprocess")
        seqs = [r.get("audit_seq") for r in agent_run.get("results", [])
                if r.get("audit_seq") is not None]
        if not seqs:
            raise HTTPException(status_code=500, detail="agent run produced no audit events to tamper with")
        seq = seqs[-1]

    e = db.query(models.AuditEvent).filter(models.AuditEvent.seq == seq).first()
    if e is None:
        raise HTTPException(status_code=404, detail="event not found")
    payload = json.loads(e.payload or "{}")
    payload["_tampered"] = True
    payload["note"] = "modified by simulate-tamper"
    e.payload = json.dumps(payload)
    db.commit()
    return {"seq": seq, "tampered": True, "hash": e.event_hash, "agent_run": agent_run}
