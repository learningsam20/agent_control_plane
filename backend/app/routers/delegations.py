import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import delegation as delegation_service
from .. import models
from ..database import get_db
from ..hashchain import append_event
from ..schemas import DelegationCreate, DelegationCreated, DelegationOut

router = APIRouter(prefix="/delegations", tags=["delegations"])


def _to_out(d: models.Delegation, with_token: bool = False) -> DelegationOut | DelegationCreated:
    base = dict(
        id=d.id,
        delegator_id=d.delegator_id,
        delegatee_id=d.delegatee_id,
        scope=json.loads(d.scope),
        max_depth=d.max_depth,
        depth=d.depth,
        active=d.active,
        status=delegation_service.status_of(d),
        issued_at=d.issued_at,
        expires_at=d.expires_at,
        revoked_at=d.revoked_at,
    )
    if with_token:
        return DelegationCreated(**base, token=d.token)
    return DelegationOut(**base)


@router.post("", response_model=DelegationCreated)
def create_delegation(body: DelegationCreate, db: Session = Depends(get_db)):
    delegator = db.get(models.Agent, body.delegator_id)
    delegatee = db.get(models.Agent, body.delegatee_id)
    if delegator is None or delegatee is None:
        raise HTTPException(status_code=404, detail="delegator or delegatee not found")

    try:
        delegation = delegation_service.issue(
            db, delegator, delegatee, body.scope, body.max_depth,
            ttl_hours=body.ttl_hours, signature=body.signature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    append_event(
        db,
        event_type="delegation.issue",
        actor_id=delegator.id,
        subject=delegatee.id,
        payload={"delegation_id": delegation.id, "scope": body.scope,
                 "max_depth": body.max_depth, "signed": bool(body.signature)},
        decision="allow",
    )
    db.commit()
    db.refresh(delegation)
    return _to_out(delegation, with_token=True)


@router.get("", response_model=list[DelegationOut])
def list_delegations(db: Session = Depends(get_db)):
    rows = db.query(models.Delegation).order_by(models.Delegation.issued_at.desc()).all()
    return [_to_out(d) for d in rows]


@router.get("/{delegation_id}", response_model=DelegationOut)
def get_delegation(delegation_id: str, db: Session = Depends(get_db)):
    d = db.get(models.Delegation, delegation_id)
    if d is None:
        raise HTTPException(status_code=404, detail="delegation not found")
    return _to_out(d)


@router.post("/{delegation_id}/revoke", response_model=DelegationOut)
def revoke_delegation(delegation_id: str, db: Session = Depends(get_db)):
    d = db.get(models.Delegation, delegation_id)
    if d is None:
        raise HTTPException(status_code=404, detail="delegation not found")
    delegation_service.revoke(db, d)
    append_event(
        db,
        event_type="delegation.revoke",
        actor_id=d.delegator_id,
        subject=d.delegatee_id,
        payload={"delegation_id": d.id},
        decision="allow",
    )
    db.commit()
    db.refresh(d)
    return _to_out(d)
