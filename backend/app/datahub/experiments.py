"""Custom (composite) experiments.

A custom experiment is a blueprint of one or more what-if steps run against
the real lineage + policy engine and aggregated into a single auditable result.
Each step is a full ``impact_analysis.simulate`` run, so every consequence is
as traceable as a single-step experiment; only the blueprint (the composed
trigger) is authored by the user.
"""

from sqlalchemy.orm import Session

from .. import models
from . import impact_analysis

RISK_LEVEL = {"low": 0, "medium": 1, "high": 2}


def run_custom(db: Session, name: str, blueprint: list[dict]) -> dict:
    steps = []
    for step in blueprint:
        root = db.get(models.DataHubEntity, step["root_urn"])
        if root is None:
            raise ValueError(f"unknown entity urn: {step['root_urn']}")
        result = impact_analysis.simulate(
            db, step["root_urn"], step["kind"], step.get("params") or {})
        steps.append({
            "root_urn": step["root_urn"],
            "root_name": result["summary"]["root_name"],
            "kind": step["kind"],
            "params": step.get("params") or {},
            "risk": result["summary"]["risk"],
            "impacted_datasets": result["summary"]["impacted_datasets"],
            "impacted_agents": result["summary"]["impacted_agents"],
            "denied_agents": result["summary"]["denied_agents"],
            "max_depth": result["summary"]["max_depth"],
            "recommendations": result["recommendations"],
            "catalog_source": result.get("catalog_source", "reference"),
            "result": result,
        })
        if not name:
            name = f"{result['summary']['root_name']} {step['kind']}"

    # --- aggregate across steps ---
    downstream: list[dict] = []
    seen_ds: set[str] = set()
    agent_map: dict[str, dict] = {}
    recs: list[dict] = []
    seen_recs: set[str] = set()
    nodes_by_urn: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    denied: set[str] = set()
    max_depth = 0
    risk = "low"

    for step in steps:
        result = step["result"]
        if RISK_LEVEL[result["summary"]["risk"]] > RISK_LEVEL[risk]:
            risk = result["summary"]["risk"]
        max_depth = max(max_depth, result["summary"]["max_depth"])

        for d in result["downstream"]:
            if d["urn"] not in seen_ds:
                seen_ds.add(d["urn"])
                downstream.append(d)

        for a in result["agents"]:
            aid = a["agent"]["agent_id"]
            if aid not in agent_map:
                agent_map[aid] = {
                    "agent": a["agent"],
                    "actions": sorted(set(a["actions"])),
                    "entities": sorted(set(a["entities"])),
                    "count": a["count"],
                    "weight": a["weight"],
                    "impacted": a.get("impacted", False),
                    "will_be_denied": a.get("will_be_denied", False),
                    "denied_actions": sorted(set(a.get("denied_actions") or [])),
                    "reason": a.get("reason", ""),
                }
            if a.get("will_be_denied"):
                denied.add(aid)

        for r in result["recommendations"]:
            if r["title"] not in seen_recs:
                seen_recs.add(r["title"])
                recs.append(r)

        for n in result["graph"]["nodes"]:
            node = nodes_by_urn.get(n["id"])
            if node is None:
                nodes_by_urn[n["id"]] = dict(n)
            elif n["data"].get("root"):
                nodes_by_urn[n["id"]]["data"] = {**nodes_by_urn[n["id"]]["data"],
                                                 "root": True}

        for e in result["graph"]["edges"]:
            key = (e["source"], e["target"])
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"id": e["id"], "source": e["source"],
                              "target": e["target"],
                              **({k: v for k, v in e.items()
                                  if k not in ("id", "source", "target")})})

    if denied:
        risk = "high"

    steps_out = [{k: v for k, v in s.items() if k != "result"} for s in steps]

    return {
        "kind": "custom",
        "name": name,
        "root_urn": steps[0]["root_urn"],
        "root_name": steps[0]["root_name"],
        "params": {"blueprint": [{"root_urn": s["root_urn"], "kind": s["kind"],
                                  "params": s["params"]} for s in steps]},
        "simulated": {
            "kind": "custom",
            "params": {"steps": len(steps)},
            "root_urn": steps[0]["root_urn"],
            "note": "Custom experiment: each step runs the real engine; only the composed trigger is authored.",
        },
        "catalog_source": steps[0]["catalog_source"] if steps else "reference",
        "summary": {
            "kind": "custom",
            "root_urn": steps[0]["root_urn"],
            "root_name": steps[0]["root_name"],
            "impacted_datasets": len(seen_ds),
            "impacted_agents": len(agent_map),
            "denied_agents": len(denied),
            "max_depth": max_depth,
            "risk": risk,
            "steps": len(steps),
        },
        "downstream": downstream,
        "agents": list(agent_map.values()),
        "recommendations": recs,
        "steps": steps_out,
        "graph": {"nodes": list(nodes_by_urn.values()), "edges": edges},
    }
