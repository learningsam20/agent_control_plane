import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..hashchain import append_event
from ..schemas import PolicyCreate, PolicyOut

router = APIRouter(prefix="/policies", tags=["policies"])


def _to_out(p: models.Policy) -> PolicyOut:
    return PolicyOut(
        id=p.id, name=p.name, description=p.description, effect=p.effect,
        actions=json.loads(p.actions or "[]"),
        conditions=json.loads(p.conditions or "[]"),
        order=p.order, enabled=p.enabled, created_at=p.created_at,
    )


@router.get("", response_model=list[PolicyOut])
def list_policies(db: Session = Depends(get_db)):
    rows = db.query(models.Policy).order_by(models.Policy.order.asc()).all()
    return [_to_out(p) for p in rows]


@router.post("", response_model=PolicyOut)
def create_policy(body: PolicyCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Policy).filter(models.Policy.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="a policy with this name already exists")

    policy = models.Policy(
        id=f"pol-{abs(hash(body.name)) % 100000:05d}",
        name=body.name,
        description=body.description,
        effect=body.effect,
        actions=json.dumps(body.actions),
        conditions=json.dumps(body.conditions),
        order=body.order,
        enabled=body.enabled,
    )
    db.add(policy)
    db.flush()
    append_event(
        db,
        event_type="policy.create",
        actor_id="system",
        subject=policy.id,
        payload={"name": policy.name, "effect": policy.effect, "actions": body.actions},
        decision="allow",
    )
    db.commit()
    db.refresh(policy)
    return _to_out(policy)


@router.patch("/{policy_id}/enabled", response_model=PolicyOut)
def set_enabled(policy_id: str, enabled: bool, db: Session = Depends(get_db)):
    p = db.get(models.Policy, policy_id)
    if p is None:
        raise HTTPException(status_code=404, detail="policy not found")
    p.enabled = enabled
    append_event(
        db,
        event_type="policy.toggle",
        actor_id="system",
        subject=p.id,
        payload={"name": p.name, "enabled": enabled},
        decision="allow",
    )
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.delete("/{policy_id}")
def delete_policy(policy_id: str, db: Session = Depends(get_db)):
    p = db.get(models.Policy, policy_id)
    if p is None:
        raise HTTPException(status_code=404, detail="policy not found")
    db.delete(p)
    db.commit()
    return {"deleted": policy_id}
