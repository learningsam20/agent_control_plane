import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings
from ..database import get_db
from ..datahub import (
    DataHubError,
    agent_impact,
    entity_impact,
    get_client,
    impact_matrix,
    record_action,
    sync_from_datahub,
)
from ..datahub import criticality
from ..datahub import experiments
from ..datahub import impact_analysis
from ..datahub import monitor
from ..datahub import policy_gaps
from ..hashchain import append_event
from ..schemas import (
    AnalyticsQuestion,
    CustomExperiment,
    DataHubActionIn,
    WatchlistAdd,
    WhatIfSimulation,
)
from ..security import digest
from ..util import utcnow

router = APIRouter(prefix="/datahub", tags=["datahub"])
settings = get_settings()


def _entity_out(e: models.DataHubEntity) -> dict:
    return {
        "urn": e.urn,
        "name": e.name,
        "type": e.type,
        "platform": e.platform,
        "domain": e.domain,
        "data_classification": e.data_classification,
        "owner_team": e.owner_team,
        "description": e.description,
        "schema": json.loads(e.schema_json or "[]"),
        "upstream": json.loads(e.upstream_json or "[]"),
        "downstream": json.loads(e.downstream_json or "[]"),
        "usage": json.loads(e.usage_json or "{}"),
        "source": e.source,
    }


@router.get("/status")
def status():
    client = get_client()
    return {
        "endpoint": client.endpoint or "",
        "connected": client.enabled,
        "catalog_source": "datahub" if client.enabled else "reference",
        "providers": {
            "datahub_read": "mcp" if settings.use_datahub_mcp else "graphql",
            "analytics": "analytics-agent" if settings.use_analytics_agent else "builtin",
            "mcp_url": settings.datahub_mcp_url or settings.datahub_mcp_command,
            "analytics_agent_url": settings.analytics_agent_url,
        },
    }


@router.post("/analytics")
def analytics(body: AnalyticsQuestion, db: Session = Depends(get_db)):
    """Answer a natural-language analytics question.

    With ``USE_ANALYTICS_AGENT=true`` the question is delegated to a running
    ``datahub-analytics-agent`` service (``ANALYTICS_AGENT_URL``); otherwise the
    built-in catalog search answers from the synced reference catalog.
    """
    if settings.use_analytics_agent:
        try:
            from ..datahub.analytics_agent import AnalyticsAgentClient

            client = AnalyticsAgentClient()
            if client.enabled:
                result = client.ask(body.question, body.engine or None)
                return {"provider": "analytics-agent", **result}
        except Exception as exc:  # noqa: BLE001  degrade to built-in answer
            import logging

            logging.getLogger("datahub").warning(
                "analytics agent unavailable, using builtin: %s", exc)

    terms = [t for t in (body.question or "").lower().split() if len(t) > 2]
    rows = db.query(models.DataHubEntity).all()
    matches = []
    for e in rows:
        hay = " ".join([e.name, e.domain, e.description or ""]).lower()
        if any(t in hay for t in terms):
            matches.append({"urn": e.urn, "name": e.name, "domain": e.domain,
                            "data_classification": e.data_classification,
                            "description": e.description})
    matches = matches[:25]
    if matches:
        answer = f"Found {len(matches)} catalog entit{'y' if len(matches) == 1 else 'ies'} matching your question."
    else:
        answer = "No catalog entities matched that question. Try dataset, domain, or business terms from the catalog."
    return {"provider": "builtin", "answer": answer, "results": matches}


@router.post("/sync")
def sync(db: Session = Depends(get_db)):
    client = get_client()
    if not client.enabled:
        raise HTTPException(status_code=400,
                            detail="DATAHUB_ENDPOINT is not configured; catalog runs on the reference dataset")
    try:
        count = sync_from_datahub(db)
    except DataHubError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    db.commit()
    return {"synced": count}


@router.get("/entities")
def list_entities(
    db: Session = Depends(get_db),
    domain: str | None = None,
    classification: str | None = None,
    type: str | None = None,
):
    q = db.query(models.DataHubEntity)
    if domain:
        q = q.filter(models.DataHubEntity.domain == domain)
    if classification:
        q = q.filter(models.DataHubEntity.data_classification == classification)
    if type:
        q = q.filter(models.DataHubEntity.type == type)
    rows = q.order_by(models.DataHubEntity.name.asc()).all()
    return [_entity_out(e) for e in rows]


@router.get("/entities/{urn}")
def get_entity(urn: str, db: Session = Depends(get_db)):
    e = db.get(models.DataHubEntity, urn)
    if e is None:
        raise HTTPException(status_code=404, detail="entity not found")
    return _entity_out(e)


@router.post("/actions")
def record_datahub_action(body: DataHubActionIn, db: Session = Depends(get_db)):
    agent = db.get(models.Agent, body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    entity = db.get(models.DataHubEntity, body.entity_urn)
    if entity is None:
        raise HTTPException(status_code=404, detail="entity not found")
    if agent.status != "active":
        raise HTTPException(status_code=403, detail="agent is not active")

    action = record_action(db, agent.id, entity.urn, body.action_type, body.metadata)
    append_event(
        db,
        event_type=f"datahub.{body.action_type}",
        actor_id=agent.id,
        subject=entity.urn,
        payload={"action_type": body.action_type, "impact": action.impact_weight,
                 "entity": entity.name, "domain": entity.domain},
        decision="allow",
    )
    db.commit()
    return {
        "id": action.id,
        "agent_id": action.agent_id,
        "entity_urn": action.entity_urn,
        "action_type": action.action_type,
        "impact_weight": action.impact_weight,
        "ts": action.ts.isoformat(),
        "contributed": bool(settings.datahub_endpoint),
    }


@router.get("/actions/{action_id}/trace")
def datahub_action_trace(action_id: str, db: Session = Depends(get_db)):
    """Full drill-down for a recorded DataHubAction: the action row, the agent,
    its hash-chain audit event, the entity's lineage context, and every impact
    analysis (experiment) that covered the entity."""
    trace = impact_analysis.action_trace(db, action_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="datahub action not found")
    return trace


@router.get("/impact")
def impact(db: Session = Depends(get_db)):
    matrix = impact_matrix(db)
    return {
        "matrix": matrix["agents"],
        "counts": matrix["counts"],
        "weights": {"read": 1.0, "query": 2.0, "transform": 3.0, "write": 4.0, "ingest": 2.5},
    }


@router.get("/impact/agent/{agent_id}")
def impact_for_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.get(models.Agent, agent_id)
    rows = agent_impact(db, agent_id)
    return {
        "agent": {"agent_id": agent_id,
                  "name": agent.name if agent else agent_id,
                  "tier": agent.tier if agent else "unknown",
                  "status": agent.status if agent else "unknown"},
        "total": len(rows),
        "actions": [
            {"id": a.id, "entity_urn": a.entity_urn, "action_type": a.action_type,
             "impact_weight": a.impact_weight, "ts": a.ts.isoformat()}
            for a in rows
        ],
    }


@router.get("/impact/entity/{entity_urn}")
def impact_for_entity(entity_urn: str, db: Session = Depends(get_db)):
    entity = db.get(models.DataHubEntity, entity_urn)
    rows = entity_impact(db, entity_urn)
    return {
        "entity": _entity_out(entity) if entity else None,
        "total": len(rows),
        "actions": [
            {"id": a.id, "agent_id": a.agent_id, "action_type": a.action_type,
             "impact_weight": a.impact_weight, "ts": a.ts.isoformat()}
            for a in rows
        ],
    }


def _experiment_out(e: models.DataHubExperiment) -> dict:
    return {
        "id": e.id,
        "kind": e.kind,
        "name": e.name or "",
        "root_urn": e.root_urn,
        "root_name": e.root_name,
        "params": json.loads(e.params_json or "{}"),
        "summary": json.loads(e.summary_json or "{}"),
        "risk": e.risk,
        "status": e.status,
        "created_at": e.created_at.isoformat(),
    }


@router.get("/impact/blast/{urn}")
def blast_radius_for(urn: str, depth: int = 3, db: Session = Depends(get_db)):
    if db.get(models.DataHubEntity, urn) is None:
        raise HTTPException(status_code=404, detail="entity not found")
    return impact_analysis.blast_radius(db, urn, max_depth=max(1, min(depth, 5)))


@router.get("/impact/agent/{agent_id}/blast")
def agent_blast_radius_for(agent_id: str, db: Session = Depends(get_db)):
    if db.get(models.Agent, agent_id) is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    return impact_analysis.agent_blast_radius(db, agent_id)


@router.post("/impact/what-if")
def run_what_if(body: WhatIfSimulation, db: Session = Depends(get_db)):
    if db.get(models.DataHubEntity, body.root_urn) is None:
        raise HTTPException(status_code=404, detail="entity not found")
    try:
        result = impact_analysis.simulate(db, body.root_urn, body.kind, body.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    exp = models.DataHubExperiment(
        id=f"exp-{digest(f'{body.root_urn}:{body.kind}'.encode())[:12]}"
        + f"-{digest(f'{utcnow().timestamp()}'.encode())[:6]}",
        kind=body.kind,
        root_urn=body.root_urn,
        root_name=result["summary"]["root_name"],
        params_json=json.dumps(body.params or {}),
        result_json=json.dumps(result, default=str),
        summary_json=json.dumps(result["summary"]),
        risk=result["summary"]["risk"],
        status="completed",
    )
    db.add(exp)
    append_event(
        db,
        event_type=f"datahub.experiment.{body.kind}",
        actor_id="control-plane",
        subject=body.root_urn,
        payload={"experiment": exp.id, "risk": exp.risk,
                 "impacted_datasets": result["summary"]["impacted_datasets"],
                 "denied_agents": result["summary"]["denied_agents"]},
        decision="allow",
    )
    db.commit()
    return {**result, "experiment_id": exp.id}


@router.get("/experiments")
def list_experiments(db: Session = Depends(get_db)):
    rows = (
        db.query(models.DataHubExperiment)
        .order_by(models.DataHubExperiment.created_at.desc())
        .all()
    )
    return [_experiment_out(e) for e in rows]


@router.get("/experiments/{exp_id}")
def get_experiment(exp_id: str, db: Session = Depends(get_db)):
    e = db.get(models.DataHubExperiment, exp_id)
    if e is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    out = _experiment_out(e)
    out["result"] = json.loads(e.result_json)
    return out


@router.post("/experiments/custom")
def run_custom_experiment(body: CustomExperiment, db: Session = Depends(get_db)):
    try:
        result = experiments.run_custom(
            db, body.name, [s.model_dump() for s in body.blueprint])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    exp = models.DataHubExperiment(
        id=f"exp-custom-{digest(f'{body.name}:{utcnow().timestamp()}'.encode())[:12]}",
        kind="custom",
        name=body.name,
        root_urn=result["root_urn"],
        root_name=result["root_name"],
        params_json=json.dumps(result["params"], default=str),
        result_json=json.dumps(result, default=str),
        summary_json=json.dumps(result["summary"]),
        risk=result["summary"]["risk"],
        status="completed",
    )
    db.add(exp)
    append_event(
        db,
        event_type="datahub.experiment.custom",
        actor_id="control-plane",
        subject=result["root_urn"],
        payload={"experiment": exp.id, "name": result["name"],
                 "steps": result["summary"]["steps"], "risk": exp.risk,
                 "denied_agents": result["summary"]["denied_agents"]},
        decision="allow",
    )
    db.commit()
    return {**result, "experiment_id": exp.id}


@router.get("/criticality")
def criticality_scores(db: Session = Depends(get_db)):
    return criticality.criticality_report(db)


def _watchlist_entry_out(e: models.WatchlistEntry) -> dict:
    return {
        "id": e.id,
        "urn": e.urn,
        "threshold": e.threshold,
        "created_at": e.created_at.isoformat(),
    }


@router.get("/watchlist")
def list_watchlist(db: Session = Depends(get_db)):
    report = criticality.criticality_report(db)
    current = {r["urn"]: r for r in report["entities"]}
    entries = db.query(models.WatchlistEntry).order_by(
        models.WatchlistEntry.created_at.asc()
    ).all()
    return {
        "entries": [
            {
                **_watchlist_entry_out(e),
                "name": current[e.urn]["name"] if e.urn in current else e.urn,
                "domain": current[e.urn]["domain"] if e.urn in current else "",
                "classification": (current[e.urn]["data_classification"]
                                   if e.urn in current else ""),
                "current": current[e.urn]["criticality"] if e.urn in current else 0.0,
                "breached": (e.urn in current
                             and current[e.urn]["criticality"] >= e.threshold),
            }
            for e in entries
        ],
        "report": report,
    }


@router.post("/watchlist")
def add_watchlist(body: WatchlistAdd, db: Session = Depends(get_db)):
    if db.get(models.DataHubEntity, body.urn) is None:
        raise HTTPException(status_code=404, detail="entity not found")
    existing = (db.query(models.WatchlistEntry)
                .filter(models.WatchlistEntry.urn == body.urn).first())
    if existing:
        existing.threshold = body.threshold
        entry = existing
    else:
        entry = models.WatchlistEntry(urn=body.urn, threshold=body.threshold)
        db.add(entry)
    append_event(
        db,
        event_type="datahub.watchlist.add",
        actor_id="control-plane",
        subject=body.urn,
        payload={"threshold": body.threshold, "watchlist_id": entry.id},
        decision="allow",
    )
    db.commit()
    db.refresh(entry)
    return _watchlist_entry_out(entry)


@router.delete("/watchlist/{entry_id}")
def remove_watchlist(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(models.WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="watchlist entry not found")
    urn = entry.urn
    append_event(
        db,
        event_type="datahub.watchlist.remove",
        actor_id="control-plane",
        subject=urn,
        payload={"watchlist_id": entry.id},
        decision="allow",
    )
    db.delete(entry)
    db.commit()
    return {"removed": entry_id, "urn": urn}


@router.get("/watchlist/alerts")
def watchlist_alerts(db: Session = Depends(get_db)):
    """Any watchlisted entity whose current criticality crosses its threshold."""
    alerts = monitor.watchlist_alerts(db)
    return {"count": len(alerts), "alerts": alerts}


@router.post("/watchlist/breaches")
def watchlist_breach_action(db: Session = Depends(get_db)):
    """The action on watchlist breaches: each newly-crossed (or worsening)
    crossing is appended to the audit chain as a tamper-evident event, deduped
    against previously recorded breaches."""
    res = monitor.record_watchlist_breaches(db)
    db.commit()
    return {"recorded": len(res["recorded"]),
            "alerts": [{"urn": a["urn"], "name": a["name"],
                        "current": a["current"], "threshold": a["threshold"]}
                       for a in res["alerts"]]}


@router.post("/monitor/scan")
def run_scan(db: Session = Depends(get_db)):
    """Run the guardian agent (``ag_monitor``) as a governed monitor scan."""
    return monitor.run_monitor_scan(db)


@router.get("/monitor/scans")
def list_scans(db: Session = Depends(get_db)):
    return monitor.list_scans(db)


@router.get("/monitor/scans/{scan_id}")
def get_scan(scan_id: str, db: Session = Depends(get_db)):
    scan = db.get(models.MonitorScan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    return monitor.scan_out(db, scan)


@router.get("/policy-gaps")
def policy_gaps_scan(db: Session = Depends(get_db)):
    return policy_gaps.scan_policy_gaps(db)


@router.get("/policy-gaps/{gap_id}/preview")
def policy_gap_preview(gap_id: str, db: Session = Depends(get_db)):
    try:
        return policy_gaps.preview_gap(db, gap_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"gap not found: {gap_id}")


@router.post("/policy-gaps/{gap_id}/apply")
def policy_gap_apply(gap_id: str, db: Session = Depends(get_db)):
    try:
        rule = policy_gaps.apply_gap(db, gap_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"gap not found: {gap_id}")
    append_event(
        db,
        event_type="datahub.policygap.apply",
        actor_id="control-plane",
        subject=rule.name,
        payload={"gap_id": gap_id, "effect": rule.effect,
                 "order": rule.order, "actions": json.loads(rule.actions or "[]")},
        decision="allow",
    )
    db.commit()
    return {
        "id": rule.id,
        "name": rule.name,
        "effect": rule.effect,
        "actions": json.loads(rule.actions or "[]"),
        "conditions": json.loads(rule.conditions or "[]"),
        "order": rule.order,
        "enabled": rule.enabled,
        "created_at": rule.created_at.isoformat(),
    }
