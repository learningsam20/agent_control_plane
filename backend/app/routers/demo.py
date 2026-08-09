"""Demo driver for the Zero-Trust Lab.

The browser cannot sign Ed25519 requests (private keys never leave their agents),
so the console runs the interactive demo server-side. Each step is a genuine
signed gateway request produced exactly as the Python SDK would build it.
"""

import json
import os
import time

import httpx

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import delegation as delegation_service
from .. import models, scenarios
from ..config import get_settings
from ..database import get_db
from ..hashchain import append_event
from ..models import tier_for_score
from ..schemas import ScenarioRef, ScenarioTransform
from ..security import canonical_json, sign
from ..seed import DEMO_AGENTS
from ..util import utcnow

router = APIRouter(prefix="/demo", tags=["demo"])
settings = get_settings()

CAMPAIGN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)"
REVENUE = "urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue,PROD)"
CHURN = "urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)"

MART_DEMOGRAPHICS = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_demographics,PROD)"
MART_BILLING = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_billing,PROD)"
RAW_PATIENTS = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.raw_patients,PROD)"

KEY_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "demo_agents")


def _private_key(agent_id: str) -> str:
    path = os.path.join(KEY_DIR, f"{agent_id}.pem")
    if not os.path.exists(path):
        raise HTTPException(status_code=500,
                            detail=f"demo key for {agent_id} missing — re-seed the database")
    with open(path) as fh:
        return fh.read()


def _rotate_identical_grants(db: Session, delegator_id: str, delegatee_id: str, scope: dict) -> int:
    """Retire every active, unexpired grant identical to the one about to be
    issued, keeping only the most recent.

    Delegations are capability tokens: each issuance is an independent token.
    The demo reruns (lab / scenario approve) would otherwise mint a fresh live
    token on every run, piling up identical-looking active grants. Rotating —
    revoking the prior identical grant before issuing the new token — keeps a
    single live grant per ``(delegator, delegatee, scope)`` while retaining the
    full token history in the audit trail.
    """
    scope_json = canonical_json(scope)
    now = utcnow()
    rows = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegator_id == delegator_id,
            models.Delegation.delegatee_id == delegatee_id,
            models.Delegation.scope == scope_json,
            models.Delegation.active.is_(True),
            models.Delegation.revoked_at.is_(None),
            (models.Delegation.expires_at.is_(None) | (models.Delegation.expires_at > now)),
        )
        .order_by(models.Delegation.issued_at.asc())
        .all()
    )
    retired = 0
    for d in rows:  # every existing grant is replaced by the new token
        delegation_service.revoke(db, d)
        append_event(db, "delegation.revoke", actor_id=delegator_id, subject=delegatee_id,
                     payload={"delegation_id": d.id, "reason": "rotated by demo rerun"},
                     decision="allow")
        retired += 1
    return retired


def _restore_demo_agents(db: Session) -> None:
    """Restore the seeded demo agents to their baseline state.

    The zero-trust lab deliberately triggers violations (denied reads/transforms)
    which, over repeated runs, auto-suspend the demo analyst. Re-running the
    scenario resets those agents so the demo is always reproducible, and the
    reset itself is audited.
    """
    for spec in DEMO_AGENTS:
        agent = db.get(models.Agent, spec["id"])
        if agent is None:
            continue
        if agent.status != "active" or agent.trust_score != spec["trust_score"]:
            reset = agent.status != "active"
            agent.status = "active"
            agent.trust_score = spec["trust_score"]
            agent.tier = tier_for_score(spec["trust_score"])
            agent.granted_domains = json.dumps(spec["domains"])
            db.query(models.Violation).filter(
                models.Violation.agent_id == agent.id
            ).delete(synchronize_session=False)
            if reset:
                append_event(db, "demo.agent_restore", actor_id="console",
                             subject=agent.id, payload={"reason": "zero-trust lab rerun"},
                             decision="allow")


def _step(agent_id: str, action: str, resource: str, token: str = "") -> dict:
    request_id = f"lab-{int(time.time_ns()) % 10**10}"
    body = {
        "agent_id": agent_id,
        "request_id": request_id,
        "action": {"type": action, "resource": resource},
        "target": None,
        "delegation_token": token,
    }
    signature = sign(_private_key(agent_id), canonical_json(body).encode())
    resp = httpx.post(f"{settings.self_url}/api/requests/gateway", json=body,
                      headers={"X-Agent-Signature": signature}, timeout=10)
    result = resp.json()
    return {
        "action": action,
        "resource": resource,
        "decision": result.get("decision"),
        "reason": result.get("reason"),
        "policy": result.get("policy_name"),
        "audit_seq": result.get("audit_seq"),
    }


def _delegate(db: Session, delegator_id: str, delegatee_id: str, scope: dict, max_depth: int) -> dict:
    _rotate_identical_grants(db, delegator_id, delegatee_id, scope)
    signed_payload = {
        "delegator_id": delegator_id,
        "delegatee_id": delegatee_id,
        "scope": scope,
        "max_depth": max_depth,
    }
    body = dict(signed_payload)
    body["ttl_hours"] = 6
    body["signature"] = sign(_private_key(delegator_id), canonical_json(signed_payload).encode())
    resp = httpx.post(f"{settings.self_url}/api/delegations", json=body, timeout=10)
    if resp.status_code >= 400:
        raise HTTPException(status_code=500, detail=resp.text)
    return resp.json()


def _agent_run_step(agent_id: str, objective: str) -> dict:
    """Run a governed agent through the real code path (planner → signed gateway).

    The planner is the LLM (Ollama) when LLM_MODEL is configured, otherwise the
    deterministic rule-based planner — either way the plan is executed as genuine
    Ed25519-signed gateway requests and the outcome is audited.
    """
    from agents.runner import execute_run

    result = execute_run(agent_id, objective, mode="inprocess")
    planner = result.get("plan_source", "rule")
    if planner == "llm":
        planner_label = f"LLM planner ({settings.llm_model})"
    else:
        planner_label = "rule-based planner (LLM_MODEL not configured)"
    return {
        "title": "Real agent run",
        "description": (
            f"kay-analyst is given an objective. {planner_label} drafts a plan, then "
            "the agent executes it as signed gateway requests — exactly the Agent Runs flow."
        ),
        "agent_run": {
            "objective": objective,
            "planner": planner,
            "model": settings.llm_model if planner == "llm" else None,
            "plan": result.get("plan", []),
            "results": result.get("results", []),
            "summary": result.get("summary", ""),
            "status": result.get("status", "failed"),
        },
    }


@router.get("/zero-trust")
def zero_trust_lab(db: Session = Depends(get_db)):
    _restore_demo_agents(db)
    db.commit()  # release the write lock before the loopback gateway calls below
    analyst = db.query(models.Agent).filter(models.Agent.id == "ag_analyst").first()
    engineer = db.query(models.Agent).filter(models.Agent.id == "ag_engineer").first()
    if analyst is None or engineer is None:
        raise HTTPException(status_code=500, detail="demo agents not seeded")

    steps = [
        {"title": "Baseline access",
         "description": "kay-analyst reads aggregated patient demographics from the healthcare mart.",
         **_step(analyst.id, "read", MART_DEMOGRAPHICS)},
        {"title": "Restricted data blocked",
         "description": "kay-analyst tries to read the restricted patient billing mart — denied: restricted data needs a privileged tier.",
         **_step(analyst.id, "read", MART_BILLING)},
        {"title": "Reputation gating",
         "description": "kay-analyst (standard) tries to transform raw PII patient records — reputation tier too low for transforms.",
         **_step(analyst.id, "transform", RAW_PATIENTS)},
    ]

    scope = {"actions": ["read", "query"], "datasets": [MART_BILLING], "domains": []}
    delegation = _delegate(db, engineer.id, analyst.id, scope, 1)
    token = delegation["token"]
    steps.append({
        "title": "Scoped delegation issued",
        "description": "priya-data-engineer (privileged) delegates read of the patient billing mart to kay-analyst, signed by the delegator.",
        "delegation_id": delegation["id"],
        "token": token,
        "decision": "allow",
        "reason": "delegation issued",
        "policy": "delegation.issue",
        "audit_seq": None,
    })

    steps.append({
        "title": "Delegated access works",
        "description": "kay-analyst reads the patient billing mart under the delegation — inherits the delegator's privileged authority within the exact scope.",
        **_step(analyst.id, "read", MART_BILLING, token),
    })

    steps.append({
        "title": "Scope is enforced",
        "description": "kay-analyst tries to write to the patient billing mart under the same delegation — outside the delegated actions.",
        **_step(analyst.id, "write", MART_BILLING, token),
    })

    steps.append(_agent_run_step(
        analyst.id,
        "Read the patient demographics mart and report on the patient population",
    ))

    append_event(db, "demo.zero_trust", actor_id="console", subject="zero-trust-lab",
                 payload={"steps": len(steps)}, decision="allow")
    db.commit()

    return {"steps": steps}


@router.post("/reset")
def reset_demo(db: Session = Depends(get_db)):
    """Restore the seeded demo agents to their baseline state (used when the
    zero-trust lab or example runs have auto-suspended an agent)."""
    _restore_demo_agents(db)
    db.commit()
    return {"reset": [a["id"] for a in DEMO_AGENTS]}


# ---------------------------------------------------------------------------
# Scenario engine: define -> transform -> preview -> approve -> enforce
# ---------------------------------------------------------------------------

@router.get("/scenarios")
def list_scenarios():
    """The bundled lab scenarios. Each is a natural-language situation the
    planner turns into agentic steps, policies and delegations."""
    return scenarios.list_predefined()


@router.post("/scenarios/transform")
def transform_scenario(body: ScenarioTransform, db: Session = Depends(get_db)):
    """Transform a scenario (predefined id or free-text objective) into a
    proposed blueprint: agents, agentic steps, generated policies, delegation.
    Nothing is persisted to the policy store until the user approves."""
    try:
        return scenarios.transform(db, scenario_id=body.scenario_id,
                                   objective=body.objective, agents_hint=body.agents)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/scenarios/preview")
def preview_scenario(body: ScenarioRef, db: Session = Depends(get_db)):
    """Simulate the proposed policies over the plan's steps in memory — no
    writes. Shows which generated policy would decide each step."""
    plan = db.get(models.ScenarioPlan, body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    result = scenarios.preview(db, plan)
    plan.status = "previewed"
    plan.previewed_at = utcnow()
    db.commit()
    return result


@router.post("/scenarios/approve")
def approve_scenario(body: ScenarioRef, db: Session = Depends(get_db)):
    """Apply an approved plan: persist the generated policies, issue the
    delegation, and enforce every step through the signed gateway service path
    (same identity → policy → audit → reputation flow the HTTP gateway runs)."""
    from agents.runner import _inprocess_gateway

    plan = db.get(models.ScenarioPlan, body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")

    blueprint = json.loads(plan.blueprint)
    _restore_demo_agents(db)
    created = scenarios.persist_policies(db, blueprint, plan.scenario_id)
    plan.status = "approved"
    plan.approved_at = utcnow()
    db.commit()  # release the write lock before the in-process gateway calls below

    delegation = None
    token = ""
    if blueprint.get("delegation"):
        spec = blueprint["delegation"]
        delegator = db.get(models.Agent, spec["delegator_id"])
        delegatee = db.get(models.Agent, spec["delegatee_id"])
        if delegator is None or delegatee is None:
            raise HTTPException(status_code=500, detail="delegation agents not found")
        _rotate_identical_grants(db, spec["delegator_id"], spec["delegatee_id"], spec["scope"])
        payload = {"delegator_id": spec["delegator_id"], "delegatee_id": spec["delegatee_id"],
                   "scope": spec["scope"], "max_depth": spec["max_depth"]}
        signature = sign(_private_key(spec["delegator_id"]), canonical_json(payload).encode())
        delegation = delegation_service.issue(
            db, delegator, delegatee, spec["scope"], spec["max_depth"],
            ttl_hours=6, signature=signature)
        token = delegation.token
        db.commit()

    executed = []
    for i, step in enumerate(blueprint.get("steps", [])):
        gateway_fn = _inprocess_gateway(_private_key(step["agent"]), step["agent"])
        resp = gateway_fn(step["action"], step["resource"],
                          delegation_token=token if step.get("delegation") else "")
        executed.append({
            "index": i,
            "agent": step["agent"],
            "action": step["action"],
            "resource": step["resource"],
            "note": step.get("note", ""),
            "expected": step.get("expect"),
            "delegation": bool(step.get("delegation")),
            "decision": resp.get("decision"),
            "reason": resp.get("reason"),
            "policy": resp.get("policy_name"),
            "audit_seq": resp.get("audit_seq"),
        })

    append_event(db, "scenario.approved", actor_id="console", subject=plan.id,
                 payload={"scenario": plan.scenario_id, "name": plan.name,
                          "steps": len(executed), "policies": created,
                          "delegation": bool(delegation)},
                 decision="allow")
    plan.status = "executed"
    db.commit()

    return {
        "plan_id": plan.id,
        "scenario_id": plan.scenario_id,
        "name": plan.name,
        "policies_created": created,
        "delegation": {"id": delegation.id, "token": delegation.token} if delegation else None,
        "steps": executed,
    }


@router.post("/scenarios/reject")
def reject_scenario(body: ScenarioRef, db: Session = Depends(get_db)):
    """Discard a proposed plan without applying anything."""
    plan = db.get(models.ScenarioPlan, body.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    plan.status = "rejected"
    append_event(db, "scenario.rejected", actor_id="console", subject=plan.id,
                 payload={"scenario": plan.scenario_id, "name": plan.name},
                 decision="allow")
    db.commit()
    return {"plan_id": plan.id, "status": plan.status}


@router.post("/scenarios/reset")
def reset_scenarios(db: Session = Depends(get_db)):
    """Remove every lab-generated policy and restore the demo agents."""
    return scenarios.reset_lab(db)
