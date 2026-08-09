"""Entity criticality for the catalog.

Every entity is scored from REAL recorded data — no hardcoded rankings:

* centrality  -> PageRank over the actual lineage graph (how central the entity
                 is to the data mesh: many consumers depend on it transitively)
* impact      -> sum of recorded ``DataHubAction`` weight across all agents
                 (min-max normalized)
* risk        -> classification band (public=0, sensitive=1, restricted=2)
* blast       -> number of downstream descendants via real lineage edges
                 (min-max normalized)

criticality = 0.35*centrality + 0.25*impact + 0.20*risk + 0.20*blast

Each component is exposed so a score is explainable and the Watchlist can
threshold on the composite or any single component.
"""

import json
from collections import defaultdict

from sqlalchemy.orm import Session

from .. import models

CLASS_LEVEL = {"public": 0, "sensitive": 1, "restricted": 2}
RISK_MAX = max(CLASS_LEVEL.values())

# PageRank damping / iterations (graph is tiny; a few dozen iterations converge)
DAMPING = 0.85
ITERS = 50

# Score at or above which an entity is reported as "critical" (top of the
# catalog on a fresh install, since risk alone can reach 0.20 and centrality
# normalizes the highest-ranking lineage head to 1.0).
CRITICAL_THRESHOLD = 0.40


def _edges(db: Session) -> tuple[set[str], dict[str, set[str]]]:
    """All URNs and their downstream neighbors (real lineage edges)."""
    rows = db.query(models.DataHubEntity).all()
    urns = {e.urn for e in rows}
    out: dict[str, set[str]] = {}
    for e in rows:
        try:
            out[e.urn] = set(json.loads(e.downstream_json or "[]")) & urns
        except (TypeError, ValueError):
            out[e.urn] = set()
    return urns, out


def pagerank(downstream: dict[str, set[str]]) -> dict[str, float]:
    """Iterative PageRank on the directed lineage graph."""
    urns = list(downstream.keys())
    n = len(urns)
    if n == 0:
        return {}
    # reverse adjacency: who feeds each node (upstream sources)
    incoming: dict[str, list[str]] = defaultdict(list)
    for u, targets in downstream.items():
        for t in targets:
            incoming[t].append(u)

    rank = {u: 1.0 / n for u in urns}
    for _ in range(ITERS):
        nxt: dict[str, float] = {}
        for u in urns:
            s = 0.0
            for src in incoming[u]:
                degree = len(downstream[src])
                if degree:
                    s += rank[src] / degree
            nxt[u] = (1 - DAMPING) / n + DAMPING * s
        rank = nxt
    return rank


def _minmax(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi - lo < 1e-9:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def _descendants(urn: str, downstream: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(downstream.get(urn, ()))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(downstream.get(cur, ()))
    return seen


def criticality_report(db: Session, include_components: bool = True) -> dict:
    """Full scoring pass over every catalog entity."""
    urns, downstream = _edges(db)

    centrality = pagerank(downstream)
    cent_norm = _minmax(centrality)

    impact_raw: dict[str, float] = defaultdict(float)
    for r in db.query(models.DataHubAction).all():
        if r.entity_urn in urns:
            impact_raw[r.entity_urn] += r.impact_weight
    impact_norm = _minmax(dict(impact_raw))

    blast_raw = {u: len(_descendants(u, downstream)) for u in urns}
    blast_norm = _minmax({u: float(v) for u, v in blast_raw.items()})

    agents_per_urn: dict[str, set[str]] = defaultdict(set)
    for r in db.query(models.DataHubAction).all():
        if r.entity_urn in urns:
            agents_per_urn[r.entity_urn].add(r.agent_id)

    by_class: dict[str, list[str]] = defaultdict(list)
    entities: dict[str, models.DataHubEntity] = {}
    for e in db.query(models.DataHubEntity).all():
        entities[e.urn] = e
        by_class[e.data_classification].append(e.urn)

    rows = []
    for urn in urns:
        e = entities[urn]
        c = cent_norm.get(urn, 0.0)
        i = impact_norm.get(urn, 0.0)
        r = CLASS_LEVEL.get(e.data_classification, 0) / RISK_MAX
        b = blast_norm.get(urn, 0.0)
        score = 0.35 * c + 0.25 * i + 0.20 * r + 0.20 * b
        row = {
            "urn": urn,
            "name": e.name,
            "type": e.type,
            "platform": e.platform,
            "domain": e.domain,
            "data_classification": e.data_classification,
            "owner_team": e.owner_team,
            "source": e.source,
            "criticality": round(score, 3),
            "centrality": round(c, 3),
            "impact": round(i, 3),
            "risk": round(r, 3),
            "blast": round(b, 3),
            "downstream_count": blast_raw.get(urn, 0),
            "agents": len(agents_per_urn.get(urn, ())),
            "actions": sum(1 for r in db.query(models.DataHubAction)
                           .filter(models.DataHubAction.entity_urn == urn).all()),
        }
        if include_components:
            row["components"] = {
                "centrality": row["centrality"],
                "impact": row["impact"],
                "risk": row["risk"],
                "blast": row["blast"],
            }
        rows.append(row)

    rows.sort(key=lambda x: x["criticality"], reverse=True)

    by_risk: dict[str, int] = {}
    for urn, names in by_class.items():
        by_risk[urn] = len(names)
    high = sum(1 for r in rows if r["criticality"] >= CRITICAL_THRESHOLD)

    return {
        "count": len(rows),
        "entities": rows,
        "summary": {
            "top": [{"urn": r["urn"], "name": r["name"], "criticality": r["criticality"]}
                    for r in rows[:5]],
            "critical_entities": high,
            "critical_threshold": CRITICAL_THRESHOLD,
            "by_classification": by_risk,
            "weights": {"centrality": 0.35, "impact": 0.25, "risk": 0.20, "blast": 0.20},
        },
    }
