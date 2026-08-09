"""Policy-gap analysis.

The scan re-evaluates every *recorded* (agent, action, entity) pair — real
``DataHubAction`` rows from gateway traffic — through the real policy engine
under the *current* policy set. When current policy would deny an action the
agent demonstrably performs, that is a governance gap: policy has drifted from
reality (a domain grant was removed, reputation dropped, an entity was
reclassified, a deny rule now matches).

Each gap carries a concrete patch — a targeted new ``lab-`` policy rule scoped
to the exact agent, domain(s) and classification(s) involved — that can be
previewed through the real engine (rule transiently added, then rolled back)
and applied (persisted + audited). No authority judgment is baked in: the scan
only reports the contradiction and lets the operator preview/apply the fix.
"""

import json

from sqlalchemy.orm import Session

from .. import models, policy


def _target_for(entity: models.DataHubEntity) -> dict:
    return {
        "entity_type": entity.type,
        "resource": entity.urn,
        "domain": entity.domain,
        "data_classification": entity.data_classification,
        "owner_team": entity.owner_team,
    }


def _build_input(db: Session, agent, action_type: str, entity):
    from ..routers.requests import build_policy_input

    return build_policy_input(
        db, agent, {"type": action_type, "resource": entity.urn},
        _target_for(entity), None, False)


def _denied_by(db: Session, decision: "policy.Decision") -> int | None:
    """Order slot for the rule that denied, so a patch can sit just above it."""
    if decision.policy_name == "default-deny":
        return None
    rule = (db.query(models.Policy)
            .filter(models.Policy.name == decision.policy_name).first())
    return rule.order if rule else None


def _patch_for(agent, action_type: str, denied: list[dict], denied_by: int | None) -> dict:
    """A targeted lab allow-rule that reinstates exactly the drifted access."""
    domains = sorted({d["domain"] for d in denied})
    classifications = sorted({d["classification"] for d in denied})
    conditions: list[dict] = [{"path": "agent.id", "op": "eq", "value": agent.id}]
    conditions.append(
        {"path": "target.domain", "op": "eq", "value": domains[0]}
        if len(domains) == 1
        else {"path": "target.domain", "op": "in", "value": domains})
    conditions.append(
        {"path": "target.data_classification", "op": "eq", "value": classifications[0]}
        if len(classifications) == 1
        else {"path": "target.data_classification", "op": "in", "value": classifications})
    order = (denied_by - 5) if denied_by is not None else 999
    order = max(1, min(order, 998))
    name = f"lab-reinstate-{agent.id}-{action_type}"
    return {
        "name": name,
        "effect": "allow",
        "actions": [action_type],
        "conditions": conditions,
        "order": order,
        "summary": (
            f"Allow {agent.name} to {action_type} data in "
            f"{', '.join(domains)} ({', '.join(classifications)}) via a targeted "
            f"rule ordered at {order}."
        ),
    }


def _gap_severity(action_type: str, denied: list[dict]) -> str:
    high_cls = any(d["classification"] == "restricted" for d in denied)
    high_act = action_type in ("write", "transform", "ingest")
    return "high" if (high_cls or high_act) else "medium"


def scan_policy_gaps(db: Session) -> dict:
    """Detect recorded activity that current policy would deny."""
    from ..routers.requests import build_policy_input  # noqa: F401 (re-exported for clarity)

    rows = db.query(models.DataHubAction).all()
    pairs: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        pairs.setdefault((r.agent_id, r.action_type), set()).add(r.entity_urn)

    gaps = []
    for (agent_id, action_type), urns in pairs.items():
        agent = db.get(models.Agent, agent_id)
        if agent is None or agent.status != "active":
            continue
        denied: list[dict] = []
        denied_by: int | None = None
        for urn in sorted(urns):
            ent = db.get(models.DataHubEntity, urn)
            if ent is None:
                continue
            input_data = _build_input(db, agent, action_type, ent)
            decision = policy.evaluate(db, input_data)
            if not decision.allow:
                denied.append({
                    "urn": urn, "name": ent.name, "domain": ent.domain,
                    "classification": ent.data_classification,
                    "reason": decision.reason, "policy_name": decision.policy_name,
                })
                if denied_by is None:
                    denied_by = _denied_by(db, decision)
        if not denied:
            continue

        gap_id = f"drift-{agent.id}-{action_type}"
        affected = ", ".join(f"{d['name']} ({d['policy_name']})" for d in denied[:5])
        gaps.append({
            "id": gap_id,
            "type": "drift",
            "severity": _gap_severity(action_type, denied),
            "title": f"{agent.name} {action_type}s data current policy denies",
            "detail": (
                f"{len(denied)} recorded {action_type} action(s) by {agent.name} "
                f"(tier {agent.tier}) are now denied by the policy engine: {affected}"
                + ("…" if len(denied) > 5 else "")
                + ". Policy has drifted from the agent's real footprint — review "
                "and either fix the grant or accept the deny."
            ),
            "agent": {"id": agent.id, "name": agent.name, "tier": agent.tier,
                      "status": agent.status},
            "action_type": action_type,
            "denied": denied,
            "patch": _patch_for(agent, action_type, denied, denied_by),
        })

    gaps.sort(key=lambda g: (0 if g["severity"] == "high" else 1,
                             len(g["denied"]), g["id"]))
    return {
        "scanned_pairs": len(pairs),
        "count": len(gaps),
        "gaps": gaps,
    }


def _find_gap(db: Session, gap_id: str) -> dict:
    report = scan_policy_gaps(db)
    for gap in report["gaps"]:
        if gap["id"] == gap_id:
            return gap
    raise KeyError(gap_id)


def preview_gap(db: Session, gap_id: str) -> dict:
    """Apply the patch transiently and re-run the REAL engine for each affected
    (agent, entity) pair, then roll back. Returns before/after decisions."""
    gap = _find_gap(db, gap_id)
    patch = gap["patch"]
    agent = db.get(models.Agent, gap["agent"]["id"])
    action_type = gap["action_type"]

    before = []
    for d in gap["denied"]:
        ent = db.get(models.DataHubEntity, d["urn"])
        if ent is None:
            continue
        before.append({"entity": d["name"], "decision": "deny",
                       "policy": d["policy_name"]})

    rule = models.Policy(
        id=f"tmp-{gap_id}", name=patch["name"], description="transient preview",
        effect=patch["effect"], actions=json.dumps(patch["actions"]),
        conditions=json.dumps(patch["conditions"]), order=patch["order"],
        enabled=True)
    db.add(rule)
    db.flush()  # session is configured autoflush=False; the engine must see the rule
    try:
        after = []
        for d in gap["denied"]:
            ent = db.get(models.DataHubEntity, d["urn"])
            if ent is None:
                continue
            input_data = _build_input(db, agent, action_type, ent)
            decision = policy.evaluate(db, input_data)
            after.append({"entity": d["name"], "decision": "allow" if decision.allow else "deny",
                          "policy": decision.policy_name})
    finally:
        db.rollback()

    consistent = all(a["decision"] == "allow" for a in after)
    return {
        "gap_id": gap_id,
        "patch": patch,
        "before": before,
        "after": after,
        "consistent": consistent,
        "note": "Preview evaluated the patch through the real policy engine; the rule was rolled back and not persisted.",
    }


def apply_gap(db: Session, gap_id: str) -> models.Policy:
    """Persist the patch as an audited ``lab-`` policy."""
    gap = _find_gap(db, gap_id)
    patch = gap["patch"]
    existing = (db.query(models.Policy)
                .filter(models.Policy.name == patch["name"]).first())
    if existing is not None:
        return existing
    rule = models.Policy(
        id=f"pol-{patch['name']}",
        name=patch["name"],
        description=f"Generated by policy-gap analysis for gap {gap_id}",
        effect=patch["effect"],
        actions=json.dumps(patch["actions"]),
        conditions=json.dumps(patch["conditions"]),
        order=patch["order"],
        enabled=True,
    )
    db.add(rule)
    return rule
