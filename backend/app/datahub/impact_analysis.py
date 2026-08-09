"""DataHub-augmented impact analysis.

Traceability contract
----------------------
Only the *trigger* of an experiment is simulated (a what-if state such as
"this dataset is reclassified", "this dataset is down"). Every consequence is
computed from real, recorded evidence across the layers:

* catalog    -> entity metadata + lineage edges (from a live DataHub sync when
                available, otherwise the bundled reference catalog). Each row
                carries its ``source`` (demo|datahub) so nothing is faked.
* policy     -> the real policy engine evaluates each agent action under the
                simulated state; the decision names the actual governing policy
                (``policy_name``) instead of a hardcoded rule.
* actions    -> real ``DataHubAction`` rows (id, ts, weight) recorded by the
                gateway when the agent acted.
* audit      -> the tamper-evident hash-chain event linked to each action via
                its request id (audit seq + event id).
* datahub    -> when a live instance is configured, agent impact is contributed
                back into the DataHub graph (``contributed`` flag).
"""

import json
from collections import defaultdict, deque

from sqlalchemy.orm import Session

from .. import models, policy
from .lineage_sims import LINEAGE_SIM_KINDS, simulate_lineage

CLASS_LEVEL = {"public": 0, "sensitive": 1, "restricted": 2}
TIER_LEVEL = {"untrusted": 0, "standard": 1, "elevated": 2, "privileged": 3}

SIMULATION_KINDS = {
    "outage", "classification_change", "schema_change", "ownership_change",
} | LINEAGE_SIM_KINDS


def _entity_dict(e: models.DataHubEntity | None) -> dict | None:
    if e is None:
        return None
    return {
        "urn": e.urn,
        "name": e.name,
        "type": e.type,
        "platform": e.platform,
        "domain": e.domain,
        "data_classification": e.data_classification,
        "owner_team": e.owner_team,
        "description": e.description,
        "source": e.source,
    }


def _upstream_for(e: models.DataHubEntity) -> set[str]:
    try:
        return set(json.loads(e.upstream_json or "[]"))
    except (TypeError, ValueError):
        return set()


def _downstream_for(e: models.DataHubEntity) -> set[str]:
    try:
        return set(json.loads(e.downstream_json or "[]"))
    except (TypeError, ValueError):
        return set()


def _graph_source(urns: set[str], db: Session) -> str:
    """Which metadata source backs this subgraph: a live DataHub sync (any
    entity carries source=datahub) or the reference catalog."""
    for urn in urns:
        e = db.get(models.DataHubEntity, urn)
        if e is not None and e.source == "datahub":
            return "datahub"
    return "reference"


def traverse(
    db: Session, root_urn: str, direction: str, max_depth: int
) -> dict[str, dict]:
    """BFS from root along lineage edges.

    Returns {urn: {"entity": {...}, "depth": int, "path": [urns]}}. The root is
    always present at depth 0 even when it has no lineage neighbors.
    """
    start = db.get(models.DataHubEntity, root_urn)
    if start is None:
        return {}
    out = {root_urn: {"entity": _entity_dict(start), "depth": 0, "path": [root_urn]}}
    queue = deque([(root_urn, 0, [root_urn])])
    while queue:
        urn, depth, path = queue.popleft()
        if depth >= max_depth:
            continue
        ent = db.get(models.DataHubEntity, urn)
        if ent is None:
            continue
        next_urns = (
            _downstream_for(ent) if direction == "downstream" else _upstream_for(ent)
        )
        for n in next_urns:
            if n in out:
                continue
            nent = db.get(models.DataHubEntity, n)
            out[n] = {"entity": _entity_dict(nent), "depth": depth + 1, "path": path + [n]}
            queue.append((n, depth + 1, path + [n]))
    return out


def _audit_link(db: Session, agent_id: str, urn: str, request_id: str) -> dict | None:
    """Find the hash-chain audit event for a recorded action via its request id."""
    if not request_id:
        return None
    events = (
        db.query(models.AuditEvent)
        .filter(
            models.AuditEvent.actor_id == agent_id,
            models.AuditEvent.subject == urn,
        )
        .order_by(models.AuditEvent.seq.desc())
        .limit(100)
        .all()
    )
    for e in events:
        try:
            payload = json.loads(e.payload or "{}")
        except (TypeError, ValueError):
            continue
        if payload.get("request_id") == request_id:
            return {"seq": e.seq, "event_id": e.id,
                    "event_type": e.event_type, "decision": e.decision}
    return None


def _evidence(db: Session, agent_id: str, urns: set[str]) -> list[dict]:
    """Real recorded actions for an agent in a subgraph, linked to the audit
    chain (hash-chain seq + event id) via the request id."""
    if not urns:
        return []
    rows = (
        db.query(models.DataHubAction)
        .filter(
            models.DataHubAction.agent_id == agent_id,
            models.DataHubAction.entity_urn.in_(urns),
        )
        .order_by(models.DataHubAction.ts.desc())
        .all()
    )
    out = []
    for r in rows:
        metadata = {}
        try:
            metadata = json.loads(r.metadata_json or "{}")
        except (TypeError, ValueError):
            pass
        out.append(
            {
                "id": r.id,
                "entity_urn": r.entity_urn,
                "action_type": r.action_type,
                "impact_weight": r.impact_weight,
                "ts": r.ts.isoformat(),
                "audit": _audit_link(db, agent_id, r.entity_urn, metadata.get("request_id", "")),
            }
        )
    return out


def _experiment_touches(e: models.DataHubExperiment, urn: str) -> bool:
    """Did a persisted experiment's blast/impact analysis cover this entity?
    Matches the recorded root URN and, for composite (custom) runs, any step
    root embedded in the stored result JSON."""
    if not urn:
        return False
    if e.root_urn == urn:
        return True
    try:
        return urn in (e.result_json or "")
    except (TypeError, ValueError):
        return False


def related_experiments(db: Session, urn: str) -> list[dict]:
    """Every persisted what-if / custom experiment whose impact analysis
    covered ``urn`` (as a root or inside its downstream subgraph), newest first.
    This is the reverse link: audit/action -> the impact analyses that touched
    the entity."""
    if not urn:
        return []
    rows = (
        db.query(models.DataHubExperiment)
        .order_by(models.DataHubExperiment.created_at.desc())
        .all()
    )
    return [
        {
            "id": e.id,
            "name": e.name,
            "kind": e.kind,
            "root_urn": e.root_urn,
            "risk": e.risk,
            "status": e.status,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
        if _experiment_touches(e, urn)
    ]


def _neighbor_entity(db: Session, urn: str) -> dict:
    e = db.get(models.DataHubEntity, urn)
    if e is None:
        return {"urn": urn}
    return {
        "urn": e.urn, "name": e.name, "type": e.type, "domain": e.domain,
        "data_classification": e.data_classification, "owner_team": e.owner_team,
    }


def entity_trace_context(db: Session, urn: str) -> dict | None:
    """The lineage context behind a catalog entity, with the same lineage facts
    the real policy engine saw when this entity was requested."""
    e = db.get(models.DataHubEntity, urn)
    if e is None:
        return None
    from ..routers.requests import _lineage_facts

    context = _entity_dict(e) or {}
    try:
        facts = _lineage_facts(db, e)["lineage"]
    except Exception:  # noqa: BLE001  lineage facts are best-effort context
        facts = {}
    context["lineage_facts"] = facts
    context["upstream"] = [_neighbor_entity(db, u) for u in _upstream_for(e)]
    context["downstream"] = [_neighbor_entity(db, u) for u in _downstream_for(e)]
    return context


def action_trace(db: Session, action_id: str) -> dict | None:
    """Full drill-down for a recorded DataHubAction: the action row, the agent,
    its hash-chain audit event (via request id), the entity's lineage context,
    and the impact analyses (experiments) that covered that entity."""
    r = db.get(models.DataHubAction, action_id)
    if r is None:
        return None
    try:
        metadata = json.loads(r.metadata_json or "{}")
    except (TypeError, ValueError):
        metadata = {}
    agent = db.get(models.Agent, r.agent_id)
    return {
        "action": {
            "id": r.id,
            "entity_urn": r.entity_urn,
            "action_type": r.action_type,
            "impact_weight": r.impact_weight,
            "metadata": metadata,
            "ts": r.ts.isoformat(),
        },
        "agent": {
            "agent_id": r.agent_id,
            "name": agent.name if agent else r.agent_id,
            "tier": agent.tier if agent else "unknown",
            "status": agent.status if agent else "unknown",
        },
        "audit": _audit_link(db, r.agent_id, r.entity_urn, metadata.get("request_id", "")),
        "entity": entity_trace_context(db, r.entity_urn),
        "experiments": related_experiments(db, r.entity_urn),
    }


def audit_trace(db: Session, event_id: str) -> dict | None:
    """Full drill-down from a hash-chain audit event: the event itself, the
    policy decision it recorded (with the exact policy input the engine saw),
    the DataHubAction it produced (request id link), the entity's lineage
    context, and every impact analysis (experiment) that covered the entity."""
    event = db.get(models.AuditEvent, event_id)
    if event is None:
        return None
    try:
        payload = json.loads(event.payload or "{}")
    except (TypeError, ValueError):
        payload = {}
    request_id = payload.get("request_id", "")

    policy_decision = None
    if request_id:
        pd = (
            db.query(models.PolicyDecision)
            .filter(models.PolicyDecision.request_id == request_id)
            .first()
        )
        if pd is None:
            pd = (
                db.query(models.PolicyDecision)
                .filter(models.PolicyDecision.audit_event_id == event.id)
                .first()
            )
        if pd is not None:
            try:
                policy_input = json.loads(pd.policy_input or "{}")
            except (TypeError, ValueError):
                policy_input = {}
            policy_decision = {
                "id": pd.id, "request_id": pd.request_id,
                "decision": pd.decision, "reason": pd.reason,
                "engine": pd.engine, "policy_input": policy_input,
                "audit_event_id": pd.audit_event_id,
                "ts": pd.ts.isoformat(),
            }

    action = None
    entity = db.get(models.DataHubEntity, event.subject) if event.subject else None
    if entity is not None:
        rows = (
            db.query(models.DataHubAction)
            .filter(
                models.DataHubAction.agent_id == event.actor_id,
                models.DataHubAction.entity_urn == event.subject,
            )
            .order_by(models.DataHubAction.ts.desc())
            .limit(50)
            .all()
        )
        for r in rows:
            try:
                metadata = json.loads(r.metadata_json or "{}")
            except (TypeError, ValueError):
                metadata = {}
            if not request_id or metadata.get("request_id") == request_id:
                action = {
                    "id": r.id, "entity_urn": r.entity_urn,
                    "action_type": r.action_type,
                    "impact_weight": r.impact_weight,
                    "metadata": metadata, "ts": r.ts.isoformat(),
                    "audit": {
                        "seq": event.seq, "event_id": event.id,
                        "event_type": event.event_type, "decision": event.decision,
                    },
                }
                break

    return {
        "event": {
            "id": event.id, "seq": event.seq,
            "event_type": event.event_type, "actor_id": event.actor_id,
            "subject": event.subject, "decision": event.decision,
            "event_hash": event.event_hash, "prev_hash": event.prev_hash,
            "signed_by": event.signed_by, "ts": event.ts, "payload": payload,
        },
        "policy_decision": policy_decision,
        "action": action,
        "entity": entity_trace_context(db, event.subject) if entity else None,
        "experiments": related_experiments(db, event.subject) if entity else [],
    }


def _policy_outcome(
    db: Session,
    agent: models.Agent,
    action_type: str,
    entity: models.DataHubEntity | None,
    overrides: dict | None = None,
) -> dict:
    """Evaluate one agent action through the REAL policy engine.

    ``overrides`` carries the simulated trigger state (e.g. a new
    ``data_classification`` or ``domain``); everything else uses current,
    recorded metadata. The returned decision names the actual governing policy.
    """
    from ..routers.requests import build_policy_input

    target = {
        "entity_type": entity.type if entity else "dataset",
        "domain": entity.domain if entity else "",
        "data_classification": entity.data_classification if entity else "public",
        "owner_team": entity.owner_team if entity else "",
    }
    if overrides:
        target.update(overrides)
    resource = entity.urn if entity else ""
    input_data = build_policy_input(
        db, agent, {"type": action_type, "resource": resource}, target, None, False
    )
    decision = policy.evaluate(db, input_data)
    return {
        "decision": "allow" if decision.allow else "deny",
        "policy_name": decision.policy_name,
        "reason": decision.reason,
        "engine": "native",
    }


WRITE_ACTIONS = ("transform", "write", "ingest")


def _subgraph_writers(agents: dict[str, dict]) -> set[str]:
    """Entities in a subgraph where any agent recorded a write/transform/ingest
    action — the real consumers that would break on a schema contract change.
    Read-only consumption does not mark an entity as a contract writer."""
    urns: set[str] = set()
    for a in agents.values():
        if any(act in WRITE_ACTIONS for act in a.get("actions", [])):
            urns.update(a.get("entities", []))
    return urns


def candidate_agents(db: Session, urns: set[str]) -> list[dict]:
    """Predict which governed agents would be involved in a subgraph even when
    they have not recorded actions yet: every governed agent whose granted
    domains overlap the subgraph, evaluated through the real policy engine.
    Rows carry ``predicted: True`` so the UI can label them as a prediction."""
    if not urns:
        return []
    from agents.registry import GOVERNED_AGENTS

    entities: dict[str, models.DataHubEntity] = {}
    domains: set[str] = set()
    for u in urns:
        e = db.get(models.DataHubEntity, u)
        if e is None:
            continue
        entities[u] = e
        domains.add(e.domain)

    rows = []
    for spec in GOVERNED_AGENTS:
        agent = db.get(models.Agent, spec["id"])
        if agent is None:
            continue
        try:
            granted = set(json.loads(agent.granted_domains or "[]"))
        except (TypeError, ValueError):
            granted = set(spec.get("domains", []) or [])
        if not granted:
            continue
        in_scope = [u for u in entities if entities[u].domain in granted]
        if not in_scope:
            continue
        evaluated: set[str] = set()
        denied = []
        for u in in_scope:
            for action_type in ("read", "write"):
                outcome = _policy_outcome(db, agent, action_type, entities[u], {})
                evaluated.add(action_type)
                if outcome["decision"] == "deny":
                    denied.append({
                        "action_type": action_type,
                        "entity": entities[u].name,
                        "policy": outcome["policy_name"],
                    })
        rows.append({
            "agent": {
                "agent_id": agent.id, "name": agent.name,
                "tier": agent.tier, "status": agent.status,
            },
            "count": 0,
            "weight": 0.0,
            "actions": sorted(evaluated),
            "entities": sorted(in_scope),
            "will_be_denied": bool(denied),
            "denied_actions": sorted({d_["action_type"] for d_ in denied}),
            "impacted": True,
            "predicted": True,
            "reason": (
                f"predicted: {len(denied)} action(s) denied by policy"
                if denied else "predicted: granted domain overlaps subgraph (no recorded actions yet)"
            ),
        })
    rows.sort(key=lambda r: (r["will_be_denied"], len(r["entities"])), reverse=True)
    return rows


def _prediction(
    db: Session,
    kind: str,
    root: models.DataHubEntity,
    params: dict,
    summary: dict,
) -> dict:
    """Predictive what-if intelligence: a plain-language likelihood + summary
    plus the key signals, derived from the real simulation outcome."""
    impacted = summary.get("impacted_datasets", 0)
    agents = summary.get("impacted_agents", 0)
    denied = summary.get("denied_agents", 0)

    if kind == "outage":
        likelihood = "high" if impacted else "low"
        summary_text = (
            f"High likelihood consumers lose input: {impacted} downstream dataset(s) "
            f"and {agents} agent(s) affected."
            if impacted else f"Low likelihood — no consumers downstream of {root.name}."
        )
    elif kind == "classification_change":
        likelihood = "high" if denied else ("medium" if impacted else "low")
        summary_text = (
            f"Raising classification denies {denied} agent(s) under real policy evaluation."
            if denied else (
                f"{impacted} downstream dataset(s) would inherit the higher classification."
                if impacted else "No agent or dataset would be affected by the reclassification.")
        )
    elif kind in ("schema_change", "schema_drift"):
        likelihood = "high" if impacted else "low"
        summary_text = (
            f"{impacted} contract consumer(s) (jobs/writers) would break."
            if impacted else "No recorded contract consumers downstream — readers unaffected.")
    elif kind in ("data_quality", "staleness", "new_upstream"):
        likelihood = "high" if impacted else "low"
        summary_text = f"Condition propagates to {impacted} downstream dataset(s)."
    elif kind == "ownership_change":
        likelihood = "medium"
        summary_text = (
            f"Ownership transfers to {params.get('new_owner', 'new-owner-team')} "
            f"affecting {impacted} dataset(s)."
        )
    else:
        likelihood = "low"
        summary_text = f"Experiment on {root.name}."

    return {
        "risk": summary["risk"],
        "likelihood": likelihood,
        "summary": summary_text,
        "signals": {
            "impacted_datasets": impacted,
            "impacted_agents": agents,
            "denied_agents": denied,
        },
    }


def affected_agents(
    db: Session, urns: set[str], with_evidence: bool = True
) -> dict[str, dict]:
    """Aggregate real DataHubActions over a set of URNs, per agent, with the
    traceable evidence behind each agent's footprint."""
    if not urns:
        return {}
    rows = (
        db.query(models.DataHubAction)
        .filter(models.DataHubAction.entity_urn.in_(urns))
        .all()
    )
    agg: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "weight": 0.0, "actions": set(), "entities": set()}
    )
    for r in rows:
        a = agg[r.agent_id]
        a["count"] += 1
        a["weight"] += r.impact_weight
        a["actions"].add(r.action_type)
        a["entities"].add(r.entity_urn)

    agents: dict[str, dict] = {}
    for aid, data in agg.items():
        agent = db.get(models.Agent, aid)
        d = dict(data)
        d["actions"] = sorted(d["actions"])
        d["entities"] = sorted(d["entities"])
        d["agent"] = {
            "agent_id": aid,
            "name": agent.name if agent else aid,
            "tier": agent.tier if agent else "unknown",
            "status": agent.status if agent else "unknown",
        }
        d["evidence"] = _evidence(db, aid, set(d["entities"])) if with_evidence else []
        agents[aid] = d
    return agents


def _positioned(nodes_by_urn: dict[str, dict], edges: list[tuple[str, str]]) -> dict:
    """Lay nodes out in columns by depth and build the ReactFlow payload."""
    cols: dict[int, list[str]] = defaultdict(list)
    for urn, spec in nodes_by_urn.items():
        cols[spec["col"]].append(urn)
    nodes = []
    for col in sorted(cols):
        for i, urn in enumerate(cols[col]):
            spec = nodes_by_urn[urn]
            nodes.append(
                {
                    "id": urn,
                    "position": {"x": 60 + col * 270, "y": 60 + i * 150},
                    "type": "impact",
                    "data": {
                        "label": spec.get("label", urn),
                        "cls": spec.get("cls", "public"),
                        "kind": spec.get("kind", "entity"),
                        "root": spec.get("root", False),
                        "affected": spec.get("affected", False),
                        "reason": spec.get("reason", ""),
                        "domain": spec.get("domain", ""),
                        "source": spec.get("source", ""),
                        "depth": spec.get("depth", col),
                    },
                }
            )
    edge_list = [
        {
            "id": f"{s}-{t}",
            "source": s,
            "target": t,
            "animated": bool(nodes_by_urn.get(t, {}).get("affected")),
            "markerEnd": {"type": "arrowclosed"},
            "style": {
                "stroke": "var(--accent)"
                if nodes_by_urn.get(t, {}).get("affected")
                else "#5b6472"
            },
        }
        for s, t in edges
    ]
    return {"nodes": nodes, "edges": edge_list}


def blast_radius(db: Session, root_urn: str, max_depth: int = 3) -> dict:
    """Report: the downstream blast radius of a dataset plus the agents that
    have actually acted inside it, each with its recorded evidence."""
    graph = traverse(db, root_urn, "downstream", max_depth)
    if not graph:
        return {"root": None, "downstream": [], "agents": [],
                "summary": {"root": root_urn, "impacted_datasets": 0,
                            "impacted_agents": 0, "max_depth": 0,
                            "restricted_count": 0, "sensitive_count": 0},
                "catalog_source": "reference",
                "graph": {"nodes": [], "edges": []}}

    root = graph[root_urn]["entity"]
    downstream = [
        {**(graph[u]["entity"] or {}), "depth": graph[u]["depth"]}
        for u in graph
        if u != root_urn
    ]
    agents = affected_agents(db, set(graph.keys()))

    cls_counts: dict[str, int] = defaultdict(int)
    for u, info in graph.items():
        ent = info["entity"]
        if ent:
            cls_counts[ent["data_classification"]] += 1

    summary = {
        "root": root_urn,
        "impacted_datasets": len(downstream),
        "impacted_agents": len(agents),
        "max_depth": max((graph[u]["depth"] for u in graph), default=0),
        "restricted_count": cls_counts.get("restricted", 0),
        "sensitive_count": cls_counts.get("sensitive", 0),
    }

    nodes_by_urn = {
        root_urn: {
            "col": 0, "label": root["name"], "cls": root["data_classification"],
            "kind": root["type"], "root": True, "name": root["name"],
            "domain": root["domain"], "source": root.get("source", "demo"),
        }
    }
    edges: list[tuple[str, str]] = []
    for u, info in graph.items():
        if u == root_urn:
            continue
        ent = info["entity"] or {}
        nodes_by_urn[u] = {
            "col": info["depth"], "label": ent.get("name", u),
            "cls": ent.get("data_classification", "public"),
            "kind": ent.get("type", "entity"), "root": False,
            "affected": True, "name": ent.get("name", u),
            "domain": ent.get("domain", ""),
            "source": ent.get("source", "demo"),
        }
        edges.append((info["path"][-2], u))

    return {
        "root": root,
        "downstream": downstream,
        "agents": list(agents.values()),
        "predicted_agents": candidate_agents(db, set(graph.keys())),
        "summary": summary,
        "prediction": {
            "risk": "high" if summary["impacted_datasets"] else "low",
            "likelihood": "high" if summary["impacted_datasets"] else "low",
            "summary": (
                f"{summary['impacted_datasets']} downstream dataset(s) and "
                f"{summary['impacted_agents']} agent(s) with recorded actions sit "
                "inside this blast radius."
                if summary["impacted_datasets"]
                else "No downstream datasets sit inside this blast radius."
            ),
            "signals": {
                "impacted_datasets": summary["impacted_datasets"],
                "impacted_agents": summary["impacted_agents"],
                "denied_agents": 0,
            },
        },
        "catalog_source": _graph_source(set(graph.keys()), db),
        "graph": _positioned(nodes_by_urn, edges),
    }


def agent_blast_radius(db: Session, agent_id: str, max_depth: int = 2) -> dict:
    """Report: every dataset an agent has touched (with its recorded evidence),
    plus the downstream consumers those datasets feed."""
    agent = db.get(models.Agent, agent_id)
    actions = (
        db.query(models.DataHubAction)
        .filter(models.DataHubAction.agent_id == agent_id)
        .all()
    )
    detail: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "weight": 0.0, "actions": set()}
    )
    for a in actions:
        d = detail[a.entity_urn]
        d["count"] += 1
        d["weight"] += a.impact_weight
        d["actions"].add(a.action_type)

    datasets = []
    all_urns: set[str] = set()
    nodes_by_urn = {
        f"agent-{agent_id}": {
            "col": 0, "label": agent.name if agent else agent_id,
            "cls": "public", "kind": "agent", "root": True,
            "name": agent.name if agent else agent_id, "domain": "",
            "source": "demo",
        }
    }
    edges: list[tuple[str, str]] = []
    for urn, d in detail.items():
        ent = db.get(models.DataHubEntity, urn)
        dgraph = traverse(db, urn, "downstream", max_depth) if ent else {}
        consumers = [
            {**(dgraph[u]["entity"] or {}), "depth": dgraph[u]["depth"]}
            for u in dgraph
            if u != urn and dgraph[u]["entity"]
        ]
        all_urns |= set(dgraph.keys())
        datasets.append(
            {
                "urn": urn,
                "entity": _entity_dict(ent),
                "count": d["count"],
                "weight": round(d["weight"], 1),
                "actions": sorted(d["actions"]),
                "downstream": consumers,
                "evidence": _evidence(db, agent_id, {urn}),
            }
        )
        e = _entity_dict(ent) or {}
        nodes_by_urn[urn] = {
            "col": 1, "label": e.get("name", urn),
            "cls": e.get("data_classification", "public"),
            "kind": e.get("type", "dataset"), "root": False, "affected": True,
            "name": e.get("name", urn), "domain": e.get("domain", ""),
            "source": e.get("source", "demo"),
        }
        edges.append((f"agent-{agent_id}", urn))
        for c in consumers:
            if c["urn"] not in nodes_by_urn:
                nodes_by_urn[c["urn"]] = {
                    "col": 1 + c["depth"], "label": c["name"],
                    "cls": c["data_classification"],
                    "kind": c["type"], "root": False, "affected": True,
                    "name": c["name"], "domain": c["domain"],
                    "source": c.get("source", "demo"),
                }
            edges.append((urn, c["urn"]))

    return {
        "agent": {
            "agent_id": agent_id,
            "name": agent.name if agent else agent_id,
            "tier": agent.tier if agent else "unknown",
            "status": agent.status if agent else "unknown",
        },
        "datasets": datasets,
        "total_actions": len(actions),
        "catalog_source": _graph_source(all_urns | set(detail.keys()), db),
        "graph": _positioned(nodes_by_urn, edges),
    }


def _agent_decision_set(
    db: Session,
    graph: dict[str, dict],
    agents: dict[str, dict],
    overrides: dict | None = None,
) -> list[dict]:
    """Evaluate each (agent, action) pair in the subgraph through the real
    policy engine. One row per distinct action type per entity the agent
    actually acted on."""
    rows = []
    for aid, data in agents.items():
        agent = db.get(models.Agent, aid)
        if agent is None:
            continue
        for urn in data["entities"]:
            ent = db.get(models.DataHubEntity, urn)
            for action_type in data["actions"]:
                outcome = _policy_outcome(db, agent, action_type, ent, overrides)
                rows.append(
                    {
                        "agent_id": aid,
                        "entity_urn": urn,
                        "action_type": action_type,
                        "policy": outcome,
                    }
                )
    return rows


def simulate(
    db: Session, root_urn: str, kind: str, params: dict | None = None
) -> dict:
    """Run a what-if "chaos experiment".

    Only ``params`` (the trigger state) is simulated. The consequences are
    computed from real lineage, real recorded actions, and real policy
    evaluation, and each row carries its evidence trace.
    """
    params = params or {}
    root = db.get(models.DataHubEntity, root_urn)
    if root is None:
        raise ValueError(f"unknown entity urn: {root_urn}")
    if kind not in SIMULATION_KINDS:
        raise ValueError(f"unknown simulation kind: {kind}")

    graph = traverse(db, root_urn, "downstream", int(params.get("depth", 3)))
    subgraph_urns = set(graph.keys())
    agents = affected_agents(db, subgraph_urns)
    root_agent = db.get(models.Agent, root.owner_team)  # noqa: F841  (kept for clarity)
    catalog_source = _graph_source(subgraph_urns, db)

    downstream: list[dict] = []
    for u, info in graph.items():
        if u == root_urn:
            continue
        e = info["entity"] or {}
        downstream.append({**e, "urn": u, "depth": info["depth"],
                           "affected": False, "reason": ""})

    simulated = {
        "kind": kind,
        "params": params,
        "root_urn": root_urn,
        "note": "Only the trigger is simulated; consequences are computed from "
                "real lineage, real recorded actions, and real policy evaluation.",
    }

    if kind in LINEAGE_SIM_KINDS:
        downstream, agent_rows, risk, recs = simulate_lineage(
            db, root, kind, params, downstream, agents, root_urn)

    elif kind == "outage":
        for d in downstream:
            d["affected"] = True
            d["reason"] = "loses its upstream input (lineage)"
        agent_rows = []
        for a in agents.values():
            a["impacted"] = True
            a["reason"] = "acts on data downstream of the downed dataset"
            a["policy"] = _policy_outcome(
                db, db.get(models.Agent, a["agent"]["agent_id"]),
                a["actions"][0] if a["actions"] else "read", root, {}
            )
            agent_rows.append(a)
        risk = "high" if downstream else "low"
        recs = [
            {
                "severity": "high",
                "title": f"Restore or fail over {root.name}",
                "detail": (
                    f"{len(downstream)} downstream dataset(s) lose their input: "
                    + ", ".join(d["name"] for d in downstream[:6])
                    + ("…" if len(downstream) > 6 else "")
                    + ". Restore the source or route consumers to a replica before "
                    "dependent jobs run."
                ),
                "action": "restore",
                "evidence": {"datasets": [d["name"] for d in downstream],
                             "agents": [a["agent"]["name"] for a in agent_rows]},
            },
        ]

    elif kind == "classification_change":
        new_cls = params.get("new_classification", "restricted")
        if new_cls not in CLASS_LEVEL:
            new_cls = "restricted"
        # Downstream datasets that already carry risk are unaffected; datasets
        # below the new band would be reclassified if they ingest from root.
        for d in downstream:
            if CLASS_LEVEL[new_cls] > CLASS_LEVEL.get(d["data_classification"], 0):
                d["affected"] = True
                d["reason"] = f"would inherit {new_cls} risk via lineage (current: {d['data_classification']})"

        agent_rows = []
        for a in agents.values():
            agent = db.get(models.Agent, a["agent"]["agent_id"])
            if agent is None:
                continue
            denied = []
            for urn in a["entities"]:
                ent = db.get(models.DataHubEntity, urn)
                if ent is None:
                    continue
                # Only evaluate the reclassification where it would actually bind:
                # the root, or downstream entities below the new band.
                if urn == root_urn or CLASS_LEVEL[new_cls] > CLASS_LEVEL.get(ent.data_classification, 0):
                    for action_type in a["actions"]:
                        before = _policy_outcome(db, agent, action_type, ent, {})
                        after = _policy_outcome(
                            db, agent, action_type, ent,
                            {"data_classification": new_cls})
                        if after["decision"] == "deny":
                            denied.append({
                                "action_type": action_type,
                                "entity": ent.name,
                                "before": before,
                                "after": after,
                            })
            a["will_be_denied"] = bool(denied)
            a["denied_actions"] = sorted({d_["action_type"] for d_ in denied})
            a["policy_changes"] = denied
            a["impacted"] = True
            a["reason"] = (
                f"{len(denied)} action(s) blocked by policy under {new_cls}"
                if denied else "still permitted"
            )
            agent_rows.append(a)

        risk = "high" if any(a["will_be_denied"] for a in agent_rows) else (
            "medium" if any(d["affected"] for d in downstream) else "low"
        )
        recs = []
        denied = [a for a in agent_rows if a["will_be_denied"]]
        if denied:
            policies = sorted({c["after"]["policy_name"] for a in denied for c in a["policy_changes"]})
            recs.append(
                {
                    "severity": "high",
                    "title": f"{len(denied)} agent(s) would be denied under {new_cls}",
                    "detail": (
                        f"Real policy evaluation blocks {', '.join(a['agent']['name'] for a in denied)}. "
                        f"Governing policies: {', '.join(policies)}. Review tiers or delegate "
                        "the restricted scope instead of a global raise."
                    ),
                    "action": "review_tier",
                    "evidence": {
                        "agents": [a["agent"]["name"] for a in denied],
                        "policies": policies,
                        "changes": [c["after"] for a in denied for c in a["policy_changes"]],
                    },
                }
            )
        inherited = [d for d in downstream if d["affected"]]
        if inherited:
            recs.append(
                {
                    "severity": "medium",
                    "title": "Reclassify or segment downstream consumers",
                    "detail": (
                        f"{len(inherited)} downstream dataset(s) would inherit the higher "
                        "classification: " + ", ".join(d["name"] for d in inherited[:6])
                        + ". Reclassify or segment them so access stays proportional."
                    ),
                    "action": "reclassify",
                    "evidence": {"datasets": [d["name"] for d in inherited]},
                }
            )

    elif kind == "schema_change":
        # A contract break only affects consumers that actually ingest the
        # changed contract: downstream jobs and entities with a real recorded
        # write/transform/ingest action. Read-only consumers are downstream but
        # unaffected — so the impacted set differs from an outage.
        writers = _subgraph_writers(agents)
        jobs = sum(1 for d in downstream if d.get("type") == "job")
        for d in downstream:
            if d.get("type") == "job" or d["urn"] in writers:
                d["affected"] = True
                d["reason"] = "breaking schema contract (consumes via write/transform/ingest)"
            else:
                d["affected"] = False
                d["reason"] = "downstream, but no recorded write/transform of the changed contract"
        agent_rows = []
        breaking_agents = 0
        for a in agents.values():
            breaking = [act for act in a["actions"] if act in ("transform", "write", "ingest")]
            a["impacted"] = bool(breaking)
            a["reason"] = (
                f"writes/transforms ({', '.join(breaking)}) may fail"
                if breaking else "read-only consumer — revalidate queries against the new contract"
            )
            a["breaking_actions"] = breaking
            breaking_agents += 1 if breaking else 0
            agent_rows.append(a)
        affected_down = [d for d in downstream if d["affected"]]
        risk = "high" if jobs or breaking_agents else (
            "medium" if affected_down else "low")
        recs = [
            {
                "severity": "high" if jobs else "medium",
                "title": "Add compatibility views or shadow reads",
                "detail": (
                    f"{len(affected_down)} downstream consumer(s) ingest {root.name} "
                    f"({jobs} job(s)). Coordinate with their owners and deploy "
                    "compatibility views or dual-read before cutting over."
                ),
                "action": "shadow",
                "evidence": {"datasets": [d["name"] for d in affected_down]},
            },
            {
                "severity": "medium",
                "title": "Add schema contract tests",
                "detail": (
                    "Contract tests in the pipeline catch breaking changes in CI "
                    "before consumers are affected."
                ),
                "action": "test",
                "evidence": {},
            },
        ]

    elif kind == "ownership_change":
        new_owner = params.get("new_owner", "new-owner-team")
        old_owner = root.owner_team
        transferred = 0
        for d in downstream:
            if d.get("owner_team") and d["owner_team"] == old_owner:
                d["affected"] = True
                d["reason"] = f"owned by {old_owner} (current)"
                transferred += 1
        agent_rows = []
        for a in agents.values():
            a["impacted"] = True
            a["reason"] = "consumes data under new ownership"
            agent_rows.append(a)
        risk = "medium"
        recs = [
            {
                "severity": "medium",
                "title": f"Transfer ownership to {new_owner}",
                "detail": (
                    f"Update owner metadata on {root.name} and {transferred} downstream "
                    f"dataset(s) still owned by {old_owner}: "
                    + ", ".join(d["name"] for d in downstream if d["affected"])[:180]
                ),
                "action": "transfer",
                "evidence": {"datasets": [d["name"] for d in downstream if d["affected"]]},
            },
            {
                "severity": "low",
                "title": "Re-run catalog sync",
                "detail": (
                    "After ownership changes, re-sync the catalog so lineage and owner "
                    "metadata are current for policy evaluation."
                ),
                "action": "sync",
                "evidence": {},
            },
        ]

    else:  # pragma: no cover - validated above
        raise ValueError(f"unknown simulation kind: {kind}")

    summary = {
        "kind": kind,
        "root_urn": root_urn,
        "root_name": root.name,
        "impacted_datasets": sum(1 for d in downstream if d["affected"]),
        "impacted_agents": len(agent_rows),
        "denied_agents": sum(1 for a in agent_rows if a.get("will_be_denied")),
        "max_depth": max((d["depth"] for d in downstream), default=0),
        "risk": risk,
    }

    prediction = _prediction(db, kind, root, params, summary)
    predicted_agents = candidate_agents(db, subgraph_urns)

    nodes_by_urn = {
        root_urn: {
            "col": 0, "label": root.name, "cls": root.data_classification,
            "kind": root.type, "root": True, "affected": False, "reason": "",
            "name": root.name, "domain": root.domain, "source": root.source,
        }
    }
    edges: list[tuple[str, str]] = []
    for u, info in graph.items():
        if u == root_urn:
            continue
        e = info["entity"] or {}
        meta = next((d for d in downstream if d["urn"] == u), None)
        nodes_by_urn[u] = {
            "col": info["depth"], "label": e.get("name", u),
            "cls": e.get("data_classification", "public"),
            "kind": e.get("type", "entity"), "root": False,
            "affected": bool(meta and meta["affected"]),
            "reason": (meta or {}).get("reason", ""),
            "name": e.get("name", u), "domain": e.get("domain", ""),
            "source": e.get("source", "demo"),
        }
        edges.append((info["path"][-2], u))

    return {
        "kind": kind,
        "root_urn": root_urn,
        "params": params,
        "simulated": simulated,
        "catalog_source": catalog_source,
        "summary": summary,
        "prediction": prediction,
        "predicted_agents": predicted_agents,
        "downstream": downstream,
        "agents": agent_rows,
        "recommendations": recs,
        "graph": _positioned(nodes_by_urn, edges),
    }
