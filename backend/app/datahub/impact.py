"""Impact tracking: records what agents do to DataHub entities and aggregates
it into an agent x entity impact matrix (read < query < transform < write),
including an attempted contribution back to the DataHub graph.
"""

import json
from collections import defaultdict
from ..util import utcnow

from sqlalchemy.orm import Session

from .. import models
from ..config import get_settings
from ..security import canonical_json, digest

settings = get_settings()

IMPACT_WEIGHTS = {"read": 1.0, "query": 2.0, "transform": 3.0, "write": 4.0, "ingest": 2.5}


def record_action(
    db: Session,
    agent_id: str,
    entity_urn: str,
    action_type: str,
    metadata: dict | None = None,
    contribute: bool = True,
) -> models.DataHubAction:
    metadata = metadata or {}
    nonce = digest(f"{utcnow().timestamp()}:{agent_id}:{entity_urn}:{action_type}".encode())
    action = models.DataHubAction(
        id=f"act-{nonce[:12]}",
        agent_id=agent_id,
        entity_urn=entity_urn,
        action_type=action_type,
        impact_weight=IMPACT_WEIGHTS.get(action_type, 1.0),
        metadata_json=canonical_json(metadata),
    )
    db.add(action)
    db.flush()

    if contribute:
        _contribute_to_datahub(entity_urn, agent_id, action_type, metadata)

    return action


def _contribute_to_datahub(entity_urn: str, agent_id: str, action_type: str,
                           metadata: dict) -> None:
    if not settings.datahub_endpoint:
        return
    try:
        from .client import DataHubClient

        client = DataHubClient()
        client.ingest_agent_impact(
            entity_urn,
            {
                "agentId": agent_id,
                "actionType": action_type,
                "timestamp": utcnow().isoformat(),
                "metadata": metadata,
            },
        )
    except Exception:  # noqa: BLE001  contribution is best-effort
        return


def impact_matrix(db: Session) -> dict:
    """Aggregate agent x entity impact for the heatmap visualization."""
    rows = db.query(models.DataHubAction).all()
    matrix: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        matrix[r.agent_id][r.entity_urn] += r.impact_weight
        counts[r.agent_id][r.entity_urn] += 1

    return {
        "agents": {a: dict(v) for a, v in matrix.items()},
        "counts": {a: dict(v) for a, v in counts.items()},
    }


def entity_impact(db: Session, entity_urn: str) -> list[models.DataHubAction]:
    return (
        db.query(models.DataHubAction)
        .filter(models.DataHubAction.entity_urn == entity_urn)
        .order_by(models.DataHubAction.ts.desc())
        .all()
    )


def agent_impact(db: Session, agent_id: str) -> list[models.DataHubAction]:
    return (
        db.query(models.DataHubAction)
        .filter(models.DataHubAction.agent_id == agent_id)
        .order_by(models.DataHubAction.ts.desc())
        .all()
    )
