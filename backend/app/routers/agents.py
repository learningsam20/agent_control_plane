import json
from ..util import utcnow

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..hashchain import append_event
from ..models import tier_for_score
from ..reputation import apply_feedback, reputation_timeline
from ..schemas import AgentKeyPair, AgentOut, AgentRegister, AgentStatusUpdate
from ..security import create_access_token, generate_keypair

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/keypair", response_model=AgentKeyPair)
def generate_keys():
    """Generate an Ed25519 identity for an agent. The private key is returned once."""
    private_pem, public_pem = generate_keypair()
    return AgentKeyPair(
        id="pending", name="pending", private_key=private_pem, public_key=public_pem
    )


@router.post("/register", response_model=AgentKeyPair)
def register_agent(body: AgentRegister, db: Session = Depends(get_db)):
    existing = db.query(models.Agent).filter(models.Agent.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="an agent with this name already exists")

    generate_keys = body.public_key in ("", "auto")
    if generate_keys:
        private_pem, public_pem = generate_keypair()
    else:
        public_pem = body.public_key
        private_pem = None

    agent = models.Agent(
        id=f"ag_{abs(hash(body.name)) % 10**8:08x}",
        name=body.name,
        description=body.description,
        public_key=public_pem,
        granted_domains=json.dumps(body.granted_domains),
        metadata_json=json.dumps(body.metadata or {}),
        status="active",
        tier=tier_for_score(50.0),
        trust_score=50.0,
        created_at=utcnow(),
        last_seen=None,
    )
    db.add(agent)
    db.flush()

    append_event(
        db,
        event_type="agent.register",
        actor_id="system",
        subject=agent.id,
        payload={"name": agent.name, "domains": body.granted_domains,
                 "generated_keys": generate_keys},
        decision="allow",
    )
    db.commit()

    return AgentKeyPair(
        id=agent.id,
        name=agent.name,
        private_key=private_pem or "client-generated",
        public_key=public_pem,
    )


@router.get("", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db)):
    agents = db.query(models.Agent).order_by(models.Agent.created_at.asc()).all()
    out = []
    for a in agents:
        out.append(AgentOut(
            id=a.id, name=a.name, description=a.description, status=a.status,
            tier=a.tier, trust_score=a.trust_score,
            granted_domains=json.loads(a.granted_domains or "[]"),
            created_at=a.created_at, last_seen=a.last_seen,
        ))
    return out


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = db.get(models.Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return AgentOut(
        id=agent.id, name=agent.name, description=agent.description, status=agent.status,
        tier=agent.tier, trust_score=agent.trust_score,
        granted_domains=json.loads(agent.granted_domains or "[]"),
        created_at=agent.created_at, last_seen=agent.last_seen,
    )


@router.post("/{agent_id}/status", response_model=AgentOut)
def update_agent_status(agent_id: str, body: AgentStatusUpdate, db: Session = Depends(get_db)):
    agent = db.get(models.Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    if body.status not in models.AGENT_STATUSES:
        raise HTTPException(status_code=400, detail="invalid status")

    agent.status = body.status
    if body.status == "revoked":
        agent.tier = "untrusted"
        agent.trust_score = 0.0

    append_event(
        db,
        event_type="agent.status_change",
        actor_id="system",
        subject=agent.id,
        payload={"from": "", "to": body.status, "by": "control-plane"},
        decision="allow",
    )
    db.commit()
    db.refresh(agent)
    return AgentOut(
        id=agent.id, name=agent.name, description=agent.description, status=agent.status,
        tier=agent.tier, trust_score=agent.trust_score,
        granted_domains=json.loads(agent.granted_domains or "[]"),
        created_at=agent.created_at, last_seen=agent.last_seen,
    )


@router.post("/{agent_id}/token")
def issue_token(agent_id: str, db: Session = Depends(get_db)):
    agent = db.get(models.Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    if agent.status != "active":
        raise HTTPException(status_code=400, detail="agent is not active")
    return {"token": create_access_token(agent.id)}


@router.get("/{agent_id}/reputation")
def agent_reputation(agent_id: str, db: Session = Depends(get_db)):
    agent = db.get(models.Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return {
        "agent_id": agent.id,
        "tier": agent.tier,
        "trust_score": agent.trust_score,
        "timeline": reputation_timeline(db, agent.id),
    }


@router.post("/{agent_id}/reputation/adjust")
def adjust_reputation(agent_id: str, delta: float, reason: str, db: Session = Depends(get_db)):
    agent = db.get(models.Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    apply_feedback(db, agent, delta, reason)
    append_event(
        db,
        event_type="reputation.adjust",
        actor_id="system",
        subject=agent.id,
        payload={"delta": delta, "reason": reason, "score": agent.trust_score, "tier": agent.tier},
    )
    db.commit()
    db.refresh(agent)
    return {"agent_id": agent.id, "tier": agent.tier, "trust_score": agent.trust_score}
