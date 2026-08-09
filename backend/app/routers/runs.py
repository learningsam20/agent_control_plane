"""Agent run lifecycle.

POST /api/agents/{agent_id}/run (or POST /api/runs) creates a pending run. The
agents worker claims pending runs, executes the LangGraph agent over the gateway,
and writes the outcome back. Synchronous runs (``?sync=true``) execute in-process
for demos and tests.
"""

import json
import uuid
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException
from opentelemetry import trace as otel_trace
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..hashchain import append_event
from ..util import utcnow

router = APIRouter(tags=["runs"])


class RunCreate(BaseModel):
    agent_id: str
    objective: str = Field(min_length=1, max_length=2000)
    sync: bool = False


class RunComplete(BaseModel):
    status: str  # succeeded | denied | failed
    plan: list[dict] = []
    results: list[dict] = []
    summary: str = ""
    trace_id: str = ""


class RunClaim(BaseModel):
    worker: str = "default"


def _run_out(run: models.AgentRun) -> dict:
    return {
        "id": run.id,
        "agent_id": run.agent_id,
        "objective": run.objective,
        "status": run.status,
        "plan": json.loads(run.plan_json or "[]"),
        "results": json.loads(run.results_json or "[]"),
        "summary": run.summary,
        "trace_id": run.trace_id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _current_trace_id() -> str:
    ctx = otel_trace.get_current_span().get_span_context()
    if ctx.is_valid:
        return format(ctx.trace_id, "032x")
    return ""


def create_run(agent_id: str, objective: str, db: Session) -> models.AgentRun:
    agent = db.get(models.Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown agent")
    if agent.status != "active":
        raise HTTPException(status_code=400,
                            detail=f"agent is not active (status={agent.status})")

    run = models.AgentRun(
        id=f"run-{uuid.uuid4().hex[:12]}",
        agent_id=agent_id,
        objective=objective,
        status="pending",
        created_at=utcnow(),
    )
    db.add(run)
    db.flush()
    append_event(db, "agent.run.created", actor_id=agent_id,
                 subject=run.id, payload={"objective": objective}, decision="allow")
    db.commit()
    db.refresh(run)
    return run


@router.post("/runs", response_model=None)
def create(body: RunCreate, db: Session = Depends(get_db)):
    run = create_run(body.agent_id, body.objective, db)
    if not body.sync:
        return _run_out(run)

    from agents.runner import execute_run

    try:
        result = execute_run(body.agent_id, body.objective, run_id=run.id, mode="inprocess")
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.summary = f"run failed: {exc}"
        run.finished_at = utcnow()
        db.commit()
        db.refresh(run)
        return _run_out(run)

    run.status = "succeeded" if result["status"] == "succeeded" else (
        "denied" if result["status"] == "denied" else "failed")
    run.plan_json = json.dumps(result["plan"])
    run.results_json = json.dumps(result["results"])
    run.summary = result["summary"]
    run.started_at = run.started_at or utcnow()
    run.finished_at = utcnow()
    db.commit()
    db.refresh(run)
    return _run_out(run)


@router.post("/agents/{agent_id}/run", response_model=None)
def run_agent(agent_id: str, body: RunCreate, db: Session = Depends(get_db)):
    """Documented entrypoint: run an agent against an objective."""
    if body.agent_id != agent_id:
        raise HTTPException(status_code=400, detail="agent_id mismatch")
    return create(body, db)


@router.get("/runs", response_model=None)
def list_runs(agent_id: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(models.AgentRun)
    if agent_id:
        q = q.filter(models.AgentRun.agent_id == agent_id)
    rows = q.order_by(models.AgentRun.created_at.desc()).limit(limit).all()
    return [_run_out(r) for r in rows]


@router.get("/runs/pending", response_model=None)
def pending_runs(db: Session = Depends(get_db)):
    rows = (db.query(models.AgentRun)
            .filter(models.AgentRun.status == "pending")
            .order_by(models.AgentRun.created_at.asc()).limit(50).all())
    return [_run_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=None)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(models.AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _run_out(run)


@router.post("/runs/{run_id}/claim", response_model=None)
def claim_run(run_id: str, body: RunClaim, db: Session = Depends(get_db)):
    run = db.get(models.AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status != "pending":
        raise HTTPException(status_code=409, detail=f"run already claimed (status={run.status})")
    run.status = "running"
    run.started_at = run.started_at or utcnow()
    append_event(db, "agent.run.claimed", actor_id=run.agent_id,
                 subject=run.id, payload={"worker": body.worker}, decision="allow")
    db.commit()
    db.refresh(run)
    return _run_out(run)


@router.post("/runs/{run_id}/complete", response_model=None)
def complete_run(run_id: str, body: RunComplete, db: Session = Depends(get_db)):
    run = db.get(models.AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if body.status not in models.RUN_STATUSES:
        raise HTTPException(status_code=400, detail="invalid run status")
    run.status = body.status
    run.plan_json = json.dumps(body.plan)
    run.results_json = json.dumps(body.results)
    run.summary = body.summary
    run.trace_id = body.trace_id or run.trace_id or _current_trace_id()
    run.finished_at = utcnow()
    with suppress(Exception):
        append_event(db, f"agent.run.{body.status}", actor_id=run.agent_id,
                     subject=run.id,
                     payload={"objective": run.objective, "summary": body.summary,
                              "decisions": [r.get("decision") for r in body.results]},
                     decision="allow")
    db.commit()
    db.refresh(run)
    return _run_out(run)
