"""Lineage-reactive simulations.

Additional what-if kinds that reason about the lineage graph itself rather
than the access-policy surface: dirty-data propagation, a new upstream source
joining, staleness after an ETL failure, and schema drift breaking downstream
contracts. They share the traceability contract of :mod:`impact_analysis` —
only the trigger/params are simulated; consequences come from real lineage
edges, real recorded ``DataHubAction`` rows, and (where a policy change is
part of the trigger) the real policy engine.
"""

import json

from sqlalchemy.orm import Session

from .. import models

LINEAGE_SIM_KINDS = {"data_quality", "new_upstream", "staleness", "schema_drift"}

RISKY_CLASSES = {"sensitive", "restricted"}


def _class_of(e: models.DataHubEntity) -> str:
    return getattr(e, "data_classification", "public") or "public"


def _agents_in(db: Session, urns: set[str]) -> dict[str, dict]:
    """All agents with a real recorded footprint inside ``urns``."""
    from .impact_analysis import affected_agents

    return affected_agents(db, urns)


def _policy(db: Session, agent: models.Agent | None, action_type: str,
            entity: models.DataHubEntity | None, overrides: dict | None) -> dict:
    from .impact_analysis import _policy_outcome

    return _policy_outcome(db, agent, action_type, entity, overrides)


def _desc_names(downstream: list[dict]) -> str:
    return ", ".join(d["name"] for d in downstream[:6]) + (
        "…" if len(downstream) > 6 else ""
    )


def _build_agent_rows(db: Session, agents: dict[str, dict],
                      root_name: str, template: str, kind: str) -> list[dict]:
    """Mark every affected agent and, when their actions write/transform, call
    out that they would propagate the condition downstream."""
    rows = []
    for a in agents.values():
        agent = db.get(models.Agent, a["agent"]["agent_id"])
        writing = [act for act in a["actions"] if act in ("transform", "write", "ingest")]
        a["impacted"] = True
        a["reason"] = (
            f"{template} (writes {', '.join(writing)} downstream of {root_name})"
            if writing else f"{template} (consumes data downstream of {root_name})"
        )
        a["propagating_actions"] = writing
        a["policy_changes"] = []
        a["denied_actions"] = []
        a["will_be_denied"] = False
        a["policy"] = None
        rows.append(a)
    return rows


def data_quality_sim(db: Session, root, params: dict,
                     downstream: list[dict], agents: dict[str, dict],
                     root_urn: str) -> tuple[list[dict], list[dict], str, list[dict]]:
    """Dirty data at the root propagates to every lineage consumer."""
    issue = str(params.get("issue", "data quality regression"))
    rows_affected = int(params.get("rows_affected", 0))
    quality = float(params.get("quality_score", 0.8)) if params.get("quality_score") is not None else 0.8

    for d in downstream:
        d["affected"] = True
        d["reason"] = f"inherits {issue} from upstream (lineage)"

    risky = [d for d in downstream if d.get("data_classification") in RISKY_CLASSES]
    agent_rows = _build_agent_rows(
        db, agents, root.name,
        f"consumes data affected by {issue}", "data_quality")

    risk = "high" if risky else ("medium" if downstream else "low")
    recs = [
        {
            "severity": "high" if risky else "medium",
            "title": f"Quarantine {root.name} until {issue} is resolved",
            "detail": (
                f"{len(downstream)} downstream dataset(s) inherit {issue}: "
                + _desc_names(downstream)
                + (f" — {rows_affected} rows affected, quality score {quality:.2f}."
                   if rows_affected else f" — quality score {quality:.2f}.")
                + " Halt dependent pipelines and quarantine the source to stop propagation."
            ),
            "action": "quarantine",
            "evidence": {"datasets": [d["name"] for d in downstream],
                         "agents": [a["agent"]["name"] for a in agent_rows]},
        },
        {
            "severity": "medium",
            "title": "Add freshness / quality checks to downstream jobs",
            "detail": (
                "A quality gate in each consuming pipeline catches dirty data at "
                "ingestion instead of silently propagating it."
            ),
            "action": "quality_gate",
            "evidence": {},
        },
    ]
    return downstream, agent_rows, risk, recs


def new_upstream_sim(db: Session, root, params: dict,
                     downstream: list[dict], agents: dict[str, dict],
                     root_urn: str) -> tuple[list[dict], list[dict], str, list[dict]]:
    """A new upstream source joins the lineage feeding the root. Optionally the
    trigger includes a reclassification (``reclassify``) whose access effects are
    evaluated through the real policy engine."""
    source = str(params.get("source_urn", "")) or str(
        params.get("source_platform", "a new upstream source"))
    category = str(params.get("category", "third-party"))
    unvetted = category != "vetted"
    source_label = source.replace("urn:li:dataset:(urn:li:dataPlatform:", "").rstrip(")")

    for d in downstream:
        d["affected"] = True
        d["reason"] = (f"now depends on new upstream {source_label} "
                       f"({category}) via {root.name}")

    new_cls = params.get("reclassify")
    agent_rows = []
    if new_cls:
        new_cls = str(new_cls)
        from .impact_analysis import CLASS_LEVEL

        for a in agents.values():
            agent = db.get(models.Agent, a["agent"]["agent_id"])
            if agent is None:
                continue
            denied = []
            for urn in a["entities"]:
                ent = db.get(models.DataHubEntity, urn)
                if ent is None:
                    continue
                if urn == root_urn or CLASS_LEVEL[new_cls] > CLASS_LEVEL.get(_class_of(ent), 0):
                    for action_type in a["actions"]:
                        before = _policy(db, agent, action_type, ent, {})
                        after = _policy(db, agent, action_type, ent,
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
                if denied else f"consumes {source_label} data under {new_cls}"
            )
            agent_rows.append(a)
    else:
        agent_rows = _build_agent_rows(
            db, agents, root.name,
            f"consumes data joined from {source_label} ({category})",
            "new_upstream")

    denied_rows = [a for a in agent_rows if a.get("will_be_denied")]
    risk = "high" if denied_rows else ("medium" if unvetted else "low")
    recs = [
        {
            "severity": "high" if unvetted else "medium",
            "title": f"Validate and tag the new upstream source {source_label}",
            "detail": (
                f"A {category} source now feeds {root.name}, impacting "
                f"{len(downstream)} downstream dataset(s). Run a data-lineage and "
                "classification review before trusting it for production consumers."
            ),
            "action": "vet_source",
            "evidence": {"source": source_label, "category": category,
                         "datasets": [d["name"] for d in downstream]},
        },
    ]
    if denied_rows:
        policies = sorted({c["after"]["policy_name"] for a in denied_rows
                           for c in a["policy_changes"]})
        recs.insert(0, {
            "severity": "high",
            "title": f"{len(denied_rows)} agent(s) denied under {new_cls}",
            "detail": (
                f"Real policy evaluation blocks {', '.join(a['agent']['name'] for a in denied_rows)}. "
                f"Governing policies: {', '.join(policies)}."
            ),
            "action": "review_tier",
            "evidence": {"agents": [a["agent"]["name"] for a in denied_rows],
                         "policies": policies},
        })
    return downstream, agent_rows, risk, recs


def staleness_sim(db: Session, root, params: dict,
                  downstream: list[dict], agents: dict[str, dict],
                  root_urn: str) -> tuple[list[dict], list[dict], str, list[dict]]:
    """The ETL feeding the root failed; everything downstream consumes stale data."""
    hours = int(params.get("hours_stale", 24))
    failed_job = str(params.get("failed_job", "")) or "the upstream ETL job"

    for d in downstream:
        d["affected"] = True
        d["reason"] = f"consumes stale data ({failed_job} last ran >{hours}h ago)"

    risky = [d for d in downstream if d.get("data_classification") in RISKY_CLASSES]
    agent_rows = _build_agent_rows(
        db, agents, root.name,
        f"acts on data stale by {hours}h ({failed_job} failed)", "staleness")

    risk = "high" if risky else ("medium" if downstream else "low")
    recs = [
        {
            "severity": "high" if risky else "medium",
            "title": f"Re-run {failed_job} and backfill",
            "detail": (
                f"{root.name} has not refreshed in {hours}h, so {len(downstream)} "
                "downstream dataset(s) are stale: " + _desc_names(downstream)
                + ". Re-run the failed job, backfill, and verify the new watermark."
            ),
            "action": "backfill",
            "evidence": {"datasets": [d["name"] for d in downstream],
                         "agents": [a["agent"]["name"] for a in agent_rows]},
        },
        {
            "severity": "medium",
            "title": "Alert on data staleness before consumers read",
            "detail": (
                "Surface the last-successful watermark on every entity so "
                "consumers know how fresh the data is before acting on it."
            ),
            "action": "freshness_alert",
            "evidence": {},
        },
    ]
    return downstream, agent_rows, risk, recs


def schema_drift_sim(db: Session, root, params: dict,
                     downstream: list[dict], agents: dict[str, dict],
                     root_urn: str) -> tuple[list[dict], list[dict], str, list[dict]]:
    """The root's schema drifted from its contract; downstream jobs break.

    Only consumers that actually ingest the drifted contract are affected
    (jobs and entities with a real recorded write/transform/ingest action), so
    the impacted set is distinct from a plain outage."""
    broken = params.get("broken_columns") or []
    broken = list(broken) if isinstance(broken, (list, tuple)) else []
    contract = str(params.get("contract_version", "v1"))
    cols = ", ".join(broken) or "key columns"
    from .impact_analysis import WRITE_ACTIONS, _subgraph_writers

    writers = _subgraph_writers(agents)
    jobs = sum(1 for d in downstream if d.get("type") == "job")
    for d in downstream:
        if d.get("type") == "job" or d["urn"] in writers:
            d["affected"] = True
            d["reason"] = f"depends on drifted column(s) [{cols}] (schema contract {contract})"
        else:
            d["affected"] = False
            d["reason"] = "downstream, but no recorded write/transform of the drifted contract"

    agent_rows = []
    for a in agents.values():
        agent = db.get(models.Agent, a["agent"]["agent_id"])
        writing = [act for act in a["actions"] if act in WRITE_ACTIONS]
        a["impacted"] = bool(writing)
        a["reason"] = (
            f"writes/transforms ({', '.join(writing)}) may fail on drifted [{cols}]"
            if writing else "read-only consumer — revalidate queries against the drifted contract"
        )
        a["breaking_actions"] = writing
        a["policy_changes"] = []
        a["denied_actions"] = []
        a["will_be_denied"] = False
        agent_rows.append(a)

    affected_down = [d for d in downstream if d["affected"]]
    risk = "high" if jobs else ("medium" if affected_down else "low")
    recs = [
        {
            "severity": "high" if jobs else "medium",
            "title": f"Update {len(affected_down)} consumers before applying the new contract",
            "detail": (
                f"{root.name} drifted from contract {contract} on [{cols}]. "
                f"{jobs} downstream job(s) and {len(affected_down)} consumer(s) "
                "would break: " + _desc_names(affected_down)
                + ". Stage the change and migrate consumers first."
            ),
            "action": "migrate",
            "evidence": {"datasets": [d["name"] for d in affected_down],
                         "columns": broken},
        },
        {
            "severity": "medium",
            "title": "Enforce the schema contract in CI",
            "detail": (
                "Contract checks on the pipeline catch drift before it reaches "
                "downstream consumers."
            ),
            "action": "contract_test",
            "evidence": {},
        },
    ]
    return downstream, agent_rows, risk, recs


SIMULATORS = {
    "data_quality": data_quality_sim,
    "new_upstream": new_upstream_sim,
    "staleness": staleness_sim,
    "schema_drift": schema_drift_sim,
}


def simulate_lineage(db: Session, root, kind: str, params: dict,
                     downstream: list[dict], agents: dict[str, dict],
                     root_urn: str) -> tuple[list[dict], list[dict], str, list[dict]]:
    """Dispatch a lineage-reactive simulation. Returns
    (downstream, agent_rows, risk, recs) in the impact_analysis shape."""
    sim = SIMULATORS[kind]
    return sim(db, root, params, downstream, agents, root_urn)


def reason_label(kind: str, root_name: str, params: dict) -> str:
    """Human-readable one-line summary for a lineage sim result."""
    if kind == "data_quality":
        issue = str(params.get("issue", "data quality regression"))
        return f"{root_name} carries {issue} that propagates to consumers"
    if kind == "new_upstream":
        source = str(params.get("source_urn", "")) or str(params.get("source_platform", "a new upstream"))
        return f"{root_name} now depends on {source}"
    if kind == "staleness":
        return f"{root_name} is stale ({params.get('hours_stale', 24)}h, ETL failure)"
    if kind == "schema_drift":
        return f"{root_name} drifted from its schema contract ({params.get('contract_version', 'v1')})"
    return f"{root_name} simulation"
