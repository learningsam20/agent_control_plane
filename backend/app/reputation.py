from datetime import timedelta

from .util import utcnow

from sqlalchemy.orm import Session

from . import models
from .config import get_settings
from .models import tier_for_score

settings = get_settings()


def clamp_score(score: float) -> float:
    return max(0.0, min(100.0, round(score, 2)))


def apply_feedback(db: Session, agent: models.Agent, delta: float, reason: str) -> models.ReputationEvent:
    score_before = agent.trust_score
    tier_before = agent.tier
    agent.trust_score = clamp_score(score_before + delta)
    agent.tier = tier_for_score(agent.trust_score)

    evt = models.ReputationEvent(
        agent_id=agent.id,
        delta=delta,
        score_before=score_before,
        score_after=agent.trust_score,
        tier_before=tier_before,
        tier_after=agent.tier,
        reason=reason,
    )
    db.add(evt)
    return evt


def record_violation(db: Session, agent: models.Agent, reason: str) -> None:
    db.add(models.Violation(agent_id=agent.id, reason=reason))
    since = utcnow() - timedelta(hours=24)
    count = (
        db.query(models.Violation)
        .filter(models.Violation.agent_id == agent.id, models.Violation.ts >= since)
        .count()
    )
    if agent.status == "active" and count >= settings.reputation_suspend_threshold:
        agent.status = "suspended"
        apply_feedback(db, agent, -10.0, f"auto-suspended after {count} violations in 24h")


def reputation_timeline(db: Session, agent_id: str) -> list[dict]:
    events = (
        db.query(models.ReputationEvent)
        .filter(models.ReputationEvent.agent_id == agent_id)
        .order_by(models.ReputationEvent.ts.asc())
        .all()
    )
    return [
        {
            "ts": e.ts.isoformat(),
            "delta": e.delta,
            "score": e.score_after,
            "tier": e.tier_after,
            "reason": e.reason,
        }
        for e in events
    ]
