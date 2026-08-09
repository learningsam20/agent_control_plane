"""Seed the control plane with baseline policies, demo agents, and the catalog."""

import json
import os

from sqlalchemy.orm import Session

from . import models
from .datahub.catalog import seed_reference_catalog
from .models import tier_for_score
from .security import generate_keypair
from .util import utcnow

DEMO_AGENTS = [
    {
        "id": "ag_analyst",
        "name": "kay-analyst",
        "description": "Healthcare analytics analyst agent. Reads patient demographics and billing context from DataHub to draft reports.",
        "tier": "standard",
        "trust_score": 52.0,
        "domains": ["Healthcare"],
    },
    {
        "id": "ag_engineer",
        "name": "priya-data-engineer",
        "description": "Senior data engineer agent. Runs transforms and ingests refined datasets back to DataHub.",
        "tier": "privileged",
        "trust_score": 88.0,
        "domains": ["Healthcare", "Finance", "Engineering", "ML"],
    },
    {
        "id": "ag_ml_engineer",
        "name": "leo-ml-engineer",
        "description": "ML engineer agent. Trains models on patient feature stores and deploys predictions.",
        "tier": "elevated",
        "trust_score": 68.0,
        "domains": ["ML", "Engineering", "Healthcare"],
    },
    {
        "id": "ag_monitor",
        "name": "mona-guardian",
        "description": "Guardian agent. Runs monitor scans over criticality, policy gaps and the watchlist, reporting control-plane posture.",
        "tier": "privileged",
        "trust_score": 94.0,
        "domains": [],
    },
]

SEED_POLICIES = [
    {
        "name": "deny-inactive-agents",
        "description": "Zero-trust guardrail: suspended and revoked agents can never act.",
        "effect": "deny",
        "actions": [],
        "conditions": [{"path": "agent.status", "op": "in", "value": ["suspended", "revoked"]}],
        "order": 10,
    },
    {
        "name": "deny-delegation-depth-exceeded",
        "description": "Acting on a delegated scope beyond the authorized chain depth is denied.",
        "effect": "deny",
        "actions": [],
        "conditions": [
            {"path": "delegation.active", "op": "is_true"},
            {"path": "delegation.depth", "op": "gte", "ref": "delegation.max_depth"},
        ],
        "order": 20,
    },
    {
        "name": "deny-outside-granted-domains",
        "description": "Agents may only touch entities in domains they are granted, unless the entity is explicitly granted by dataset-scoped delegation.",
        "effect": "deny",
        "actions": [],
        "conditions": [
            {"path": "target.domain", "op": "not_in", "ref": "agent.granted_domains"},
            {"path": "delegation.dataset_scope_match", "op": "is_false"},
        ],
        "order": 30,
    },
    {
        "name": "allow-read-sensitive",
        "description": "Standard+ agents may read and query public and sensitive datasets.",
        "effect": "allow",
        "actions": ["read", "query"],
        "conditions": [
            {"path": "agent.reputation_tier", "op": "gte", "value": "standard"},
            {"path": "target.data_classification", "op": "in", "value": ["public", "sensitive"]},
        ],
        "order": 40,
    },
    {
        "name": "allow-transform-elevated",
        "description": "Elevated+ agents may transform sensitive data (public/sensitive).",
        "effect": "allow",
        "actions": ["transform"],
        "conditions": [
            {"path": "agent.reputation_tier", "op": "gte", "value": "elevated"},
            {"path": "target.data_classification", "op": "in", "value": ["public", "sensitive"]},
        ],
        "order": 50,
    },
    {
        "name": "allow-write-elevated",
        "description": "Elevated+ agents may write and ingest into public and sensitive entities.",
        "effect": "allow",
        "actions": ["write", "ingest"],
        "conditions": [
            {"path": "agent.reputation_tier", "op": "gte", "value": "elevated"},
            {"path": "target.data_classification", "op": "in", "value": ["public", "sensitive"]},
        ],
        "order": 60,
    },
    {
        "name": "allow-deploy-ml",
        "description": "Elevated+ agents may deploy ML models and pipelines in the ML domain.",
        "effect": "allow",
        "actions": ["deploy"],
        "conditions": [
            {"path": "agent.reputation_tier", "op": "gte", "value": "elevated"},
            {"path": "target.domain", "op": "eq", "value": "ML"},
            {"path": "target.data_classification", "op": "in", "value": ["public", "sensitive"]},
        ],
        "order": 55,
    },
    {
        "name": "allow-restricted-write-privileged",
        "description": "Only privileged agents may read or write restricted data (e.g. finance).",
        "effect": "allow",
        "actions": ["read", "query", "write", "transform", "ingest"],
        "conditions": [
            {"path": "agent.reputation_tier", "op": "gte", "value": "privileged"},
            {"path": "target.data_classification", "op": "eq", "value": "restricted"},
        ],
        "order": 70,
    },
]


def seed(db: Session, force: bool = False) -> None:
    seeded = {
        "policies": 0,
        "agents": 0,
        "entities": 0,
    }

    for p in SEED_POLICIES:
        existing = db.query(models.Policy).filter(models.Policy.name == p["name"]).first()
        if existing is None:
            db.add(
                models.Policy(
                    id=f"pol-{abs(hash(p['name'])) % 100000:05d}",
                    name=p["name"],
                    description=p["description"],
                    effect=p["effect"],
                    actions=json.dumps(p["actions"]),
                    conditions=json.dumps(p["conditions"]),
                    order=p["order"],
                    enabled=True,
                )
            )
            seeded["policies"] += 1

    for a in DEMO_AGENTS:
        existing = db.query(models.Agent).filter(models.Agent.id == a["id"]).first()
        if existing is None or force:
            private_pem, public_pem = _load_or_create_demo_key(a["id"])
            agent = existing or models.Agent(
                id=a["id"],
                name=a["name"],
                description=a["description"],
                public_key=public_pem,
                granted_domains=json.dumps(a["domains"]),
                status="active",
                trust_score=a["trust_score"],
                tier=tier_for_score(a["trust_score"]),
                created_at=utcnow(),
            )
            if existing:
                agent.public_key = public_pem
            else:
                db.add(agent)
            seeded["agents"] += 1

    seeded["entities"] = seed_reference_catalog(db)

    _prune_stale_syncs(db, seeded)

    db.commit()


def _prune_stale_syncs(db: Session, seeded: dict) -> None:
    """Remove catalog rows that came from a DataHub sync which is no longer
    reachable, so the demo never mixes generic synced noise with the curated
    reference catalog. When a live DataHub instance answers, nothing is pruned
    and the sync can be refreshed on demand."""
    from .datahub.catalog import REFERENCE_URNS

    if _datahub_reachable():
        return
    stale = (
        db.query(models.DataHubEntity)
        .filter(models.DataHubEntity.source == "datahub")
        .all()
    )
    for ent in stale:
        if ent.urn not in REFERENCE_URNS:
            db.delete(ent)
            seeded["entities_pruned"] = seeded.get("entities_pruned", 0) + 1
    db.flush()  # materialize deletions so the orphan scan below is accurate

    # Drop impact rows for datasets that no longer exist in the catalog so the
    # impact matrix/blast radius only reflect the curated reference stack.
    valid_urns = [row[0] for row in db.query(models.DataHubEntity.urn).all()]
    orphaned = (
        db.query(models.DataHubAction)
        .filter(~models.DataHubAction.entity_urn.in_(valid_urns))
        .all()
    )
    for action in orphaned:
        db.delete(action)
    if orphaned:
        seeded["impact_actions_pruned"] = len(orphaned)


def _datahub_reachable() -> bool:
    """True when a live DataHub GMS answers /health quickly."""
    import httpx

    from .config import get_settings

    endpoint = get_settings().datahub_endpoint
    if not endpoint:
        return False
    try:
        resp = httpx.get(f"{endpoint.rstrip('/')}/health", timeout=2)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _load_or_create_demo_key(agent_id: str) -> tuple[str, str]:
    """Load an existing demo keypair or create it once.

    The demo key store is the source of truth: identities are stable across
    database wipes, so signatures made with the on-disk private key always match
    the public key the control plane stores.
    """
    from cryptography.hazmat.primitives import serialization

    os.makedirs("data/demo_agents", exist_ok=True)
    path = os.path.join("data", "demo_agents", f"{agent_id}.pem")
    if os.path.exists(path):
        with open(path) as fh:
            private_pem = fh.read()
        private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        return private_pem, public_pem

    private_pem, public_pem = generate_keypair()
    with open(path, "w") as fh:
        fh.write(private_pem)
    os.chmod(path, 0o600)
    return private_pem, public_pem
