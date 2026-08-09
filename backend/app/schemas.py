from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class AgentRegister(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    description: str = ""
    public_key: str
    granted_domains: list[str] = []
    metadata: dict[str, Any] = {}


class AgentOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    tier: str
    trust_score: float
    granted_domains: list[str]
    created_at: datetime
    last_seen: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AgentKeyPair(BaseModel):
    id: str
    name: str
    private_key: str  # returned exactly once at registration
    public_key: str


class AgentStatusUpdate(BaseModel):
    status: str  # active | suspended | revoked


class DelegationCreate(BaseModel):
    delegator_id: str
    delegatee_id: str
    scope: dict[str, Any]  # {actions: [...], datasets: [...], domains: [...]}
    max_depth: int = Field(default=1, ge=1, le=3)
    ttl_hours: Optional[float] = Field(default=None, gt=0)
    signature: str = ""  # delegator Ed25519 signature over canonical payload


class DelegationOut(BaseModel):
    id: str
    delegator_id: str
    delegatee_id: str
    scope: dict[str, Any]
    max_depth: int
    depth: int
    active: bool
    status: str = "active"  # effective validity: active | expired | revoked
    issued_at: datetime
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DelegationCreated(DelegationOut):
    token: str  # capability token returned once at creation


class TargetInput(BaseModel):
    entity_type: str = "dataset"
    resource: str = ""  # URN
    domain: str = ""
    data_classification: str = "public"
    owner_team: str = ""


class GatewayRequest(BaseModel):
    agent_id: str
    action: dict[str, Any]  # {type, resource, input?}
    target: Optional[TargetInput] = None
    delegation_token: str = ""
    request_id: str = ""


class GatewayResponse(BaseModel):
    request_id: str
    decision: str  # allow | deny
    reason: str
    engine: str
    policy_name: str
    agent_id: str
    event_id: str
    audit_seq: int
    result: Optional[dict[str, Any]] = None


class PolicyCreate(BaseModel):
    name: str
    description: str = ""
    effect: str = Field(pattern="^(allow|deny)$")
    actions: list[str] = []
    conditions: list[dict[str, Any]] = []
    order: int = 100
    enabled: bool = True


class PolicyOut(BaseModel):
    id: str
    name: str
    description: str
    effect: str
    actions: list[str]
    conditions: list[dict[str, Any]]
    order: int
    enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PolicyTest(BaseModel):
    agent_id: str
    action: dict[str, Any]
    target: Optional[TargetInput] = None
    delegation_token: str = ""


class ReputationAdjust(BaseModel):
    delta: float
    reason: str


class AuditOut(BaseModel):
    id: str
    seq: int
    prev_hash: str
    event_hash: str
    event_type: str
    actor_id: str
    subject: str
    payload: dict[str, Any]
    decision: Optional[str] = None
    signed_by: Optional[str] = None
    ts: str

    model_config = ConfigDict(from_attributes=True)


class DataHubActionIn(BaseModel):
    agent_id: str
    entity_urn: str
    action_type: str = Field(pattern="^(read|query|transform|write|ingest)$")
    metadata: dict[str, Any] = {}


class WhatIfSimulation(BaseModel):
    root_urn: str
    kind: str = Field(
        pattern="^(outage|classification_change|schema_change|ownership_change|data_quality|new_upstream|staleness|schema_drift)$"
    )
    params: dict[str, Any] = {}


class CustomExperiment(BaseModel):
    name: str = ""
    blueprint: list[WhatIfSimulation] = Field(min_length=1, max_length=8)


class WatchlistAdd(BaseModel):
    urn: str
    threshold: float = Field(ge=0.0, le=1.0, default=0.5)


class AnalyticsQuestion(BaseModel):
    question: str = Field(min_length=1)
    engine: str = ""


class ScenarioTransform(BaseModel):
    scenario_id: str = ""  # pick a predefined scenario
    objective: str = ""    # ... or describe your own scenario in natural language
    agents: list[str] = []  # optional: constrain which agents to use


class ScenarioRef(BaseModel):
    plan_id: str
