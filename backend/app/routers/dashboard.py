import json
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..hashchain import verify_chain
from ..models import TIER_ORDER

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    agents = db.query(models.Agent).all()
    delegations = db.query(models.Delegation).all()
    decisions = db.query(models.PolicyDecision).all()
    entities = db.query(models.DataHubEntity).all()

    tier_counts = Counter(a.tier for a in agents)
    status_counts = Counter(a.status for a in agents)
    decision_counts = Counter(d.decision for d in decisions)
    deny_reasons = Counter(d.reason for d in decisions if d.decision == "deny")

    chain = verify_chain(db)

    recent_events = (
        db.query(models.AuditEvent)
        .order_by(models.AuditEvent.seq.desc())
        .limit(10)
        .all()
    )

    by_domain = Counter()
    for e in entities:
        by_domain[e.domain] += 1

    agents_by_domain: Counter = Counter()
    for a in agents:
        try:
            domains = json.loads(a.granted_domains or "[]")
        except (TypeError, ValueError):
            domains = []
        for d in domains:
            agents_by_domain[d] += 1

    return {
        "agents": {
            "total": len(agents),
            "active": status_counts.get("active", 0),
            "suspended": status_counts.get("suspended", 0),
            "revoked": status_counts.get("revoked", 0),
            "tiers": {t: tier_counts.get(t, 0) for t in TIER_ORDER},
            "by_domain": dict(agents_by_domain),
        },
        "delegations": {
            "total": len(delegations),
            "active": sum(1 for d in delegations if d.active),
        },
        "decisions": {
            "total": len(decisions),
            "allow": decision_counts.get("allow", 0),
            "deny": decision_counts.get("deny", 0),
            "deny_rate": round(decision_counts.get("deny", 0) / max(len(decisions), 1), 4),
            "top_deny_reasons": deny_reasons.most_common(5),
        },
        "catalog": {
            "entities": len(entities),
            "by_domain": dict(by_domain),
        },
        "chain": {
            "block_count": chain["block_count"],
            "valid": chain["valid"],
        },
        "recent_events": [
            {"seq": e.seq, "event_type": e.event_type, "actor_id": e.actor_id,
             "decision": e.decision, "ts": e.ts}
            for e in recent_events
        ],
    }
