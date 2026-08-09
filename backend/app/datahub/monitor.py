"""Guardian monitor scans.

A monitor scan is a governed run of the guardian agent (``ag_monitor``) over
the DataHub posture: dataset criticality, a policy-gap re-scan of every recorded
action, and watchlist breaches. The findings come from real data (catalog,
lineage, ``DataHubAction`` rows, the real policy engine); the run is executed
through the exact governed workflow the other agents use, and the scan itself is
persisted as a ``MonitorScan`` and appended to the audit chain.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .. import models
from ..hashchain import append_event
from ..util import utcnow

_RISK_WEIGHTS = {"low": 0, "medium": 1, "high": 2}


def watchlist_alerts(db: Session) -> list[dict]:
    """Any watchlisted entity whose current criticality crosses its threshold."""
    from . import criticality

    report = criticality.criticality_report(db)
    current = {r["urn"]: r for r in report["entities"]}
    entries = db.query(models.WatchlistEntry).all()
    alerts = []
    for e in entries:
        if e.urn not in current:
            continue
        score = current[e.urn]["criticality"]
        if score >= e.threshold:
            alerts.append({
                "watchlist_id": e.id,
                "urn": e.urn,
                "name": current[e.urn]["name"],
                "domain": current[e.urn]["domain"],
                "threshold": e.threshold,
                "current": score,
                "delta": round(score - e.threshold, 3),
                "classification": current[e.urn]["data_classification"],
            })
    alerts.sort(key=lambda a: a["delta"], reverse=True)
    return alerts


def record_watchlist_breaches(db: Session, alerts: list[dict] | None = None) -> dict:
    """The action on a watchlist breach: an audited, tamper-evident event is
    appended for every newly-crossed (or worsening) threshold crossing, and the
    crossing remains an active alert. Prior breaches for the same watch entry
    are deduped so repeated scans do not spam the chain — only an actual
    worsening (higher current criticality) appends a new block."""
    if alerts is None:
        alerts = watchlist_alerts(db)
    recorded = []
    for a in alerts:
        prior = (
            db.query(models.AuditEvent)
            .filter(
                models.AuditEvent.event_type == "datahub.watchlist.breach",
                models.AuditEvent.subject == a["urn"],
            )
            .order_by(models.AuditEvent.seq.desc())
            .limit(1)
            .all()
        )
        prev_current = -1.0
        if prior:
            try:
                prev_current = float(json.loads(prior[0].payload or "{}").get("current", -1))
            except (TypeError, ValueError):
                prev_current = -1.0
        if prev_current >= a["current"]:
            continue
        append_event(
            db,
            event_type="datahub.watchlist.breach",
            actor_id="ag_monitor",
            subject=a["urn"],
            payload={
                "watchlist_id": a["watchlist_id"],
                "name": a["name"],
                "domain": a["domain"],
                "classification": a["classification"],
                "threshold": a["threshold"],
                "current": a["current"],
                "delta": a["delta"],
                "action": "alert + audited breach + monitor priority",
            },
            decision="allow",
        )
        recorded.append(a)
    return {"recorded": recorded, "alerts": alerts}


def run_monitor_scan(db: Session) -> dict:
    """Execute a governed guardian run and persist the resulting scan."""
    from agents.runner import execute_run

    run = execute_run("ag_monitor", "Monitor scan", mode="inprocess")

    findings = []
    for step in run.get("results", []):
        if step.get("decision") != "allow":
            findings.append({
                "kind": step["action"], "status": "failed",
                "detail": step.get("reason", "governance tool unavailable"),
                "severity": "medium",
            })
            continue
        payload = step.get("result") or {}
        if step["action"] == "criticality":
            critical = [r for r in payload if r.get("critical")]
            findings.append({
                "kind": "criticality", "status": "ok",
                "detail": f"{len(critical)} critical dataset(s) at or above threshold",
                "severity": "high" if critical else "low",
                "items": [{"name": r["name"], "criticality": r["criticality"]} for r in critical],
            })
        elif step["action"] == "policy_gaps":
            gaps = list(payload)
            high = sum(1 for g in gaps if g.get("severity") == "high")
            findings.append({
                "kind": "policy_gaps", "status": "ok",
                "detail": f"{len(gaps)} gap(s) in enforced policy for recorded actions"
                          + (f" ({high} high)" if high else ""),
                "severity": "high" if high else ("medium" if gaps else "low"),
                "items": [
                    {"agent": g["agent"], "action": g["action_type"],
                     "severity": g["severity"], "reason": g["reason"]}
                    for g in gaps
                ],
            })
        elif step["action"] == "watchlist_alerts":
            alerts = list(payload)
            findings.append({
                "kind": "watchlist", "status": "ok",
                "detail": f"{len(alerts)} watchlist alert(s)",
                "severity": "high" if alerts else "low",
                "items": [
                    {"name": a["name"], "urn": a["urn"], "current": a["current"],
                     "threshold": a["threshold"], "delta": a["delta"]}
                    for a in alerts
                ],
            })
            record_watchlist_breaches(db, alerts)

    severity = max((_RISK_WEIGHTS.get(f.get("severity", "low"), 0) for f in findings), default=0)
    risk = "low" if severity <= 0 else ("medium" if severity == 1 else "high")

    summary = {
        "agent": "ag_monitor",
        "run_id": run.get("thread_id", ""),
        "status": run.get("status", "failed"),
        "planner": run.get("plan_source", "rule"),
        "risk": risk,
        "critical_datasets": next((len(f["items"]) for f in findings
                                   if f["kind"] == "criticality"), 0),
        "policy_gaps": next((len(f["items"]) for f in findings
                             if f["kind"] == "policy_gaps"), 0),
        "watchlist_alerts": next((len(f["items"]) for f in findings
                                  if f["kind"] == "watchlist"), 0),
        "findings": len(findings),
        "governed_run": {
            "plan": run.get("plan", []),
            "summary": run.get("summary", ""),
        },
    }

    scan = models.MonitorScan(
        id=f"scan-{int(utcnow().timestamp())}-{len(run.get('thread_id', '')) % 1000}",
        summary_json=json.dumps(summary, default=str),
        findings_json=json.dumps(findings, default=str),
        risk=risk,
        status="completed",
        created_at=utcnow(),
    )
    db.add(scan)
    db.flush()
    append_event(
        db,
        event_type="datahub.monitor.scan",
        actor_id="ag_monitor",
        subject="control-plane",
        payload={
            "scan_id": scan.id,
            "risk": risk,
            "policy_gaps": summary["policy_gaps"],
            "watchlist_alerts": summary["watchlist_alerts"],
            "critical_datasets": summary["critical_datasets"],
        },
        decision="allow",
    )
    db.commit()
    return {
        "id": scan.id,
        "risk": risk,
        "status": "completed",
        "summary": summary,
        "findings": findings,
        "created_at": scan.created_at.isoformat(),
    }


def scan_out(db: Session, scan: models.MonitorScan) -> dict:
    return {
        "id": scan.id,
        "risk": scan.risk,
        "status": scan.status,
        "summary": json.loads(scan.summary_json or "{}"),
        "findings": json.loads(scan.findings_json or "[]"),
        "created_at": scan.created_at.isoformat(),
    }


def list_scans(db: Session, limit: int = 10) -> list[dict]:
    rows = (
        db.query(models.MonitorScan)
        .order_by(models.MonitorScan.created_at.desc())
        .limit(limit)
        .all()
    )
    return [scan_out(db, s) for s in rows]
