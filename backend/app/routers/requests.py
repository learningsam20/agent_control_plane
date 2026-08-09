import json
from ..util import utcnow

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import delegation as delegation_service
from .. import models, opa, policy
from ..config import get_settings
from ..database import get_db
from ..datahub import record_action
from ..hashchain import append_event
from ..reputation import apply_feedback, record_violation
from ..schemas import GatewayRequest, GatewayResponse, PolicyTest
from ..security import canonical_json, digest, verify
from ..telemetry import meter as _get_meter

router = APIRouter(tags=["gateway"])
settings = get_settings()

_decision_counter = None


def _record_decision(agent_id: str, decision: str, action_type: str,
                     policy: str, engine: str) -> None:
    global _decision_counter
    try:
        if _decision_counter is None:
            _decision_counter = _get_meter("gateway").create_counter(
                "gateway.decisions", unit="1", description="Gateway policy decisions"
            )
        _decision_counter.add(1, {
            "agent_id": agent_id, "decision": decision,
            "action": action_type, "policy": policy, "engine": engine,
        })
    except Exception:
        pass


def _resolve_entity(db: Session, resource: str) -> models.DataHubEntity | None:
    return db.get(models.DataHubEntity, resource)


def _dataset_scope_match(delegation: models.Delegation, resource: str) -> bool:
    """True when the requested dataset is explicitly listed in the delegation scope."""
    try:
        scope = json.loads(delegation.scope)
    except (TypeError, json.JSONDecodeError):
        return False
    datasets = scope.get("datasets", [])
    return bool(datasets) and resource in datasets


def _apply_delegator_feedback(db: Session, delegation: models.Delegation,
                              delta: float, reason: str) -> None:
    """Delegated actions reflect on the delegator (the party who vouched)."""
    delegator = db.get(models.Agent, delegation.delegator_id)
    if delegator is not None:
        apply_feedback(db, delegator, delta, reason)


def build_policy_input(
    db: Session,
    agent: models.Agent,
    action: dict,
    target: dict | None,
    delegation: models.Delegation | None,
    dataset_scope_match: bool = False,
) -> dict:
    """Build the normalized policy input.

    When the agent acts under a valid delegation the delegator vouches for the
    delegatee: the effective reputation tier becomes the delegator's tier and
    granted domains are extended with the delegation scope, all constrained to
    the delegated actions/datasets.
    """
    target = target or {}
    granted_domains = json.loads(agent.granted_domains or "[]")
    effective_tier = agent.tier

    delegator_id = ""
    if delegation:
        delegator = None
        if delegation.delegator_id:
            delegator = db.get(models.Agent, delegation.delegator_id)
        if delegator is not None:
            effective_tier = delegator.tier
            delegator_id = delegator.id
            try:
                scope = json.loads(delegation.scope)
            except (TypeError, json.JSONDecodeError):
                scope = {}
            granted_domains = list(dict.fromkeys(granted_domains + scope.get("domains", [])))

    action_in_scope = True
    if delegation:
        try:
            delegation_scope = json.loads(delegation.scope)
        except (TypeError, json.JSONDecodeError):
            delegation_scope = {}
        action_in_scope = action.get("type", "") in delegation_scope.get("actions", [])

    return {
        "agent": {
            "id": agent.id,
            "reputation_tier": effective_tier,
            "trust_score": agent.trust_score,
            "status": agent.status,
            "granted_domains": granted_domains,
        },
        "action": {
            "type": action.get("type", ""),
            "resource": action.get("resource", ""),
        },
        "target": {
            "entity_type": target.get("entity_type", "dataset"),
            "domain": target.get("domain", ""),
            "data_classification": target.get("data_classification", "public"),
            "owner_team": target.get("owner_team", ""),
        },
        "delegation": {
            "active": bool(delegation),
            "depth": delegation.depth if delegation else 0,
            "max_depth": delegation.max_depth if delegation else 0,
            "delegator_id": delegator_id,
            "dataset_scope_match": bool(dataset_scope_match),
            "action_in_scope": action_in_scope,
        },
    }


def _lineage_facts(db: Session, entity: models.DataHubEntity | None) -> dict:
    """Lineage-aware context derived from real catalog edges + criticality.

    These facts are merged into the policy input as ``extra`` (additive, under
    the ``lineage`` key) so policies can reference things like
    ``lineage.upstream_restricted`` or ``lineage.is_critical`` without changing
    the core request contract. Nothing here is simulated — it comes from the
    real lineage graph and the real criticality scoring.
    """
    if entity is None:
        return {"lineage": {}}
    facts: dict = {
        "upstream_restricted": False,
        "upstream_restricted_count": 0,
        "downstream_count": len(json.loads(entity.downstream_json or "[]")),
        "is_critical": False,
        "criticality": 0.0,
    }
    upstream = json.loads(entity.upstream_json or "[]")
    if upstream:
        rows = (
            db.query(models.DataHubEntity)
            .filter(models.DataHubEntity.urn.in_(upstream))
            .all()
        )
        restricted = [
            u for u in rows if u.data_classification in ("restricted", "sensitive")
        ]
        facts["upstream_restricted"] = bool(restricted)
        facts["upstream_restricted_count"] = len(restricted)
    try:
        from ..datahub import criticality

        report = criticality.criticality_report(db)
        for r in report["entities"]:
            if r["urn"] == entity.urn:
                facts["is_critical"] = r["criticality"] >= criticality.CRITICAL_THRESHOLD
                facts["criticality"] = r["criticality"]
                break
    except Exception:  # noqa: BLE001 — criticality is best-effort context
        pass
    return {"lineage": facts}


def _execute_allowed(db: Session, agent: models.Agent, action: dict,
                     entity: models.DataHubEntity | None, input_data: dict,
                     request_id: str = "") -> dict | None:
    """Carry out the allowed action: read/query return entity context from the
    DataHub catalog; write/transform/ingest record agent impact back to DataHub.
    """
    action_type = action.get("type", "")
    resource = action.get("resource", "")
    result = None

    if action_type in ("read", "query"):
        if entity:
            schema = json.loads(entity.schema_json or "[]")
            usage = json.loads(entity.usage_json or "{}")
            result = {
                "entity": {
                    "urn": entity.urn,
                    "name": entity.name,
                    "platform": entity.platform,
                    "domain": entity.domain,
                    "data_classification": entity.data_classification,
                    "owner_team": entity.owner_team,
                    "description": entity.description,
                    "schema": schema,
                    "usage": usage,
                },
                "upstream": json.loads(entity.upstream_json or "[]"),
                "downstream": json.loads(entity.downstream_json or "[]"),
            }
            record_action(db, agent.id, entity.urn, action_type,
                          metadata={"request_id": request_id})
    elif action_type in ("write", "transform", "ingest"):
        if entity:
            record_action(db, agent.id, entity.urn, action_type,
                          metadata={"request_id": request_id})
        result = {"resource": resource, "note": f"{action_type} recorded and contributed to DataHub"}
    elif action_type == "deploy":
        result = {"resource": resource, "note": "deployment validated"}

    return result


@router.post("/requests/gateway", response_model=GatewayResponse)
def gateway_request(body: GatewayRequest, request: Request, db: Session = Depends(get_db)):
    """Zero-trust action gateway.

    Every request is attributed to a registered agent (Ed25519-signed, so it
    cannot be repudiated), evaluated against policy, appended to the tamper-evident
    audit chain, and fed back into the agent's reputation.
    """
    signature = request.headers.get("X-Agent-Signature", "")
    return evaluate_signed(db, body, signature)


def evaluate_signed(db: Session, body: GatewayRequest, signature: str) -> GatewayResponse:
    """Service form of the gateway: evaluate a signed request and execute/deny it.

    Used by the HTTP endpoint above and by the in-process LangGraph agent runner,
    so agent runs use the exact same gateway path (identity, policy, audit,
    reputation) whether the action is signed over HTTP or inside the server.
    """
    agent = db.get(models.Agent, body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown agent")

    agent.last_seen = utcnow()
    action = body.action
    action_type = action.get("type", "")
    if action_type not in models.ACTION_TYPES:
        raise HTTPException(status_code=400, detail=f"unknown action type: {action_type}")

    resource = action.get("resource", "")
    request_id = body.request_id or "manual"

    # 1. Resolve delegation scope
    delegation = None
    dataset_scope_match = False
    if body.delegation_token:
        delegation = delegation_service.resolve(db, body.delegation_token, body.agent_id)
        if delegation is None:
            return _deny(db, agent, body, request_id, "delegation token is invalid, expired, or revoked",
                         input_data={}, delegation=None, policy_name="delegation.validation")
        dataset_scope_match = _dataset_scope_match(delegation, resource)
        if not delegation_service.scope_matches(delegation, action_type, resource,
                                                body.target.domain if body.target else ""):
            return _deny(db, agent, body, request_id,
                         f"action outside delegated scope: {action_type} on {resource}",
                         input_data={}, delegation=delegation, policy_name="delegation.scope")

    # 2. Verify the agent's Ed25519 signature over the canonical request body.
    #    Clients sign the exact JSON payload they submit; the server re-canonicalizes
    #    the received body and verifies, giving non-repudiation.
    signed_payload = body.model_dump()
    if not signature or not verify(agent.public_key, signature, canonical_json(signed_payload).encode()):
        return _deny(db, agent, body, request_id, "agent signature verification failed",
                     input_data={}, delegation=delegation, policy_name="identity.verification")

    # 3. Build input and evaluate policy
    entity = _resolve_entity(db, resource)
    target_data = body.target.model_dump() if body.target else {}
    if entity and body.target is None:
        target_data = {
            "entity_type": entity.type,
            "domain": entity.domain,
            "data_classification": entity.data_classification,
            "owner_team": entity.owner_team,
        }
    input_data = build_policy_input(db, agent, action, target_data, delegation, dataset_scope_match)
    input_data = {**input_data, **_lineage_facts(db, entity)}

    engine = opa.engine_choice()
    if engine == "opa":
        decision = opa.evaluate(opa.build_opa_input(input_data))
        if decision is None:
            decision = policy.evaluate(db, input_data)
            engine = "native"
    else:
        decision = policy.evaluate(db, input_data)
        engine = "native"

    if not decision.allow:
        return _deny(db, agent, body, request_id, decision.reason,
                     input_data=input_data, delegation=delegation, policy_name=decision.policy_name,
                     engine=engine)

    # 4. Allowed: record + audit + positive reputation
    _record_decision(agent.id, "allow", action_type, decision.policy_name, engine)
    result = _execute_allowed(db, agent, action, entity, input_data, request_id)
    event = append_event(
        db,
        event_type=f"request.{action_type}",
        actor_id=agent.id,
        subject=resource,
        payload={"request_id": request_id, "action": action, "decision": "allow",
                 "policy": decision.policy_name, "engine": engine},
        decision="allow",
    )
    db.add(models.PolicyDecision(
        id=f"dec-{request_id}", agent_id=agent.id, request_id=request_id,
        policy_input=canonical_json(input_data), decision="allow",
        reason=decision.reason, engine=engine, audit_event_id=event.id,
    ))
    apply_feedback(db, agent, settings.reputation_allow_delta,
                   f"allowed: {action_type} on {resource}")
    if delegation:
        _apply_delegator_feedback(db, delegation, settings.reputation_allow_delta, "delegated action allowed")
    db.commit()

    return GatewayResponse(
        request_id=request_id,
        decision="allow",
        reason=decision.reason,
        engine=engine,
        policy_name=decision.policy_name,
        agent_id=agent.id,
        event_id=event.id,
        audit_seq=event.seq,
        result=result,
    )


def _deny(db: Session, agent: models.Agent, body: GatewayRequest, request_id: str,
          reason: str, input_data: dict, delegation: models.Delegation | None,
          policy_name: str, engine: str = "native") -> GatewayResponse:
    action_type = body.action.get("type", "")
    resource = body.action.get("resource", "")
    _record_decision(agent.id, "deny", action_type, policy_name, engine)
    event = append_event(
        db,
        event_type=f"request.{action_type}.denied",
        actor_id=agent.id,
        subject=resource,
        payload={"request_id": request_id, "action": body.action, "decision": "deny",
                 "reason": reason, "policy": policy_name},
        decision="deny",
    )
    db.add(models.PolicyDecision(
        id=f"dec-{request_id}", agent_id=agent.id, request_id=request_id,
        policy_input=canonical_json(input_data) if input_data else "{}",
        decision="deny", reason=reason, engine=engine, audit_event_id=event.id,
    ))

    if input_data:  # identity/scope failures are not reputation violations
        apply_feedback(db, agent, settings.reputation_deny_delta, f"denied: {reason}")
        record_violation(db, agent, reason)
        if delegation and input_data.get("delegation", {}).get("delegator_id"):
            _apply_delegator_feedback(db, delegation, settings.reputation_deny_delta,
                                      f"delegated action denied: {reason}")

    db.commit()
    return GatewayResponse(
        request_id=request_id,
        decision="deny",
        reason=reason,
        engine=engine,
        policy_name=policy_name,
        agent_id=agent.id,
        event_id=event.id,
        audit_seq=event.seq,
    )


@router.post("/requests/test", response_model=GatewayResponse)
def test_request(body: PolicyTest, db: Session = Depends(get_db)):
    """Dry-run a policy decision without executing or applying reputation."""
    agent = db.get(models.Agent, body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="unknown agent")

    delegation = None
    dataset_scope_match = False
    if body.delegation_token:
        delegation = delegation_service.resolve(db, body.delegation_token, body.agent_id)
        if delegation is not None:
            dataset_scope_match = _dataset_scope_match(delegation, body.action.get("resource", ""))

    entity = _resolve_entity(db, body.action.get("resource", ""))
    target_data = body.target.model_dump() if body.target else {}
    if entity and body.target is None:
        target_data = {
            "entity_type": entity.type,
            "domain": entity.domain,
            "data_classification": entity.data_classification,
            "owner_team": entity.owner_team,
        }
    input_data = build_policy_input(db, agent, body.action, target_data, delegation, dataset_scope_match)
    input_data = {**input_data, **_lineage_facts(db, entity)}

    engine = opa.engine_choice()
    decision = opa.evaluate(opa.build_opa_input(input_data)) if engine == "opa" else None
    if decision is None:
        decision = policy.evaluate(db, input_data)
        engine = "native"

    return GatewayResponse(
        request_id="dry-run",
        decision="allow" if decision.allow else "deny",
        reason=decision.reason,
        engine=engine,
        policy_name=decision.policy_name,
        agent_id=agent.id,
        event_id="",
        audit_seq=0,
    )
