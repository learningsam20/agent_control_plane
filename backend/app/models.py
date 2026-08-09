from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .util import utcnow

# Reputation tiers, ordered
TIER_ORDER = ["untrusted", "standard", "elevated", "privileged"]
TIER_MIN_SCORES = {"untrusted": 0, "standard": 40, "elevated": 60, "privileged": 80}

AGENT_STATUSES = ["active", "suspended", "revoked"]

ACTION_TYPES = ["read", "query", "transform", "write", "ingest", "deploy", "delegate", "onboard"]

CLASSIFICATIONS = ["public", "sensitive", "restricted"]


def tier_for_score(score: float) -> str:
    for tier in reversed(TIER_ORDER):
        if score >= TIER_MIN_SCORES[tier]:
            return tier
    return "untrusted"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    public_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    tier: Mapped[str] = mapped_column(String(16), default="untrusted", index=True)
    trust_score: Mapped[float] = mapped_column(Float, default=50.0)
    granted_domains: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    reputation_events: Mapped[list["ReputationEvent"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class ReputationEvent(Base):
    __tablename__ = "reputation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    delta: Mapped[float] = mapped_column(Float)
    score_before: Mapped[float] = mapped_column(Float)
    score_after: Mapped[float] = mapped_column(Float)
    tier_before: Mapped[str] = mapped_column(String(16))
    tier_after: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(255))

    agent: Mapped[Agent] = relationship(back_populates="reputation_events")


class Delegation(Base):
    __tablename__ = "delegations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    delegator_id: Mapped[str] = mapped_column(String(64), index=True)
    delegatee_id: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(Text)  # JSON: {actions, datasets, domains}
    max_depth: Mapped[int] = mapped_column(Integer, default=1)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token: Mapped[str] = mapped_column(Text)  # signed delegation proof
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    effect: Mapped[str] = mapped_column(String(8))  # allow | deny
    actions: Mapped[str] = mapped_column(Text, default="[]")  # JSON list; [] => any
    conditions: Mapped[str] = mapped_column(Text, default="[]")  # JSON rules
    order: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    event_hash: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # allow | deny
    signed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    ts: Mapped[str] = mapped_column(String(64), index=True)  # ISO-8601, canonicalized


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    policy_input: Mapped[str] = mapped_column(Text)  # JSON
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(16))
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    audit_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DataHubEntity(Base):
    __tablename__ = "datahub_entities"

    urn: Mapped[str] = mapped_column(String(512), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)  # dataset|mlModel|job|dashboard
    platform: Mapped[str] = mapped_column(String(64), default="")
    domain: Mapped[str] = mapped_column(String(64), index=True)
    data_classification: Mapped[str] = mapped_column(String(32), default="public")
    owner_team: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    schema_json: Mapped[str] = mapped_column(Text, default="[]")
    upstream_json: Mapped[str] = mapped_column(Text, default="[]")
    downstream_json: Mapped[str] = mapped_column(Text, default="[]")
    usage_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(16), default="demo")  # demo | datahub


class DataHubAction(Base):
    __tablename__ = "datahub_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    entity_urn: Mapped[str] = mapped_column(String(512), index=True)
    action_type: Mapped[str] = mapped_column(String(32), index=True)
    impact_weight: Mapped[float] = mapped_column(Float, default=1.0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class DataHubExperiment(Base):
    """A persisted what-if "chaos experiment" on the catalog: the simulation
    kind, the dataset it targeted, the blast-radius result, and the derived
    recommendations — an auditable record of impact analysis runs."""

    __tablename__ = "datahub_experiments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    root_urn: Mapped[str] = mapped_column(String(512), index=True)
    root_name: Mapped[str] = mapped_column(String(255), default="")
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    risk: Mapped[str] = mapped_column(String(16), default="low", index=True)
    status: Mapped[str] = mapped_column(String(16), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class WatchlistEntry(Base):
    """A persisted watch on a catalog entity: when the entity's current
    criticality score crosses ``threshold`` an alert fires (audited)."""

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    urn: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    threshold: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MonitorScan(Base):
    """A guardian-agent scan: one pass over criticality, policy gaps and the
    watchlist, with the findings and audit events it produced."""

    __tablename__ = "monitor_scans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    findings_json: Mapped[str] = mapped_column(Text, default="[]")
    risk: Mapped[str] = mapped_column(String(16), default="low", index=True)
    status: Mapped[str] = mapped_column(String(16), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    reason: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


SCENARIO_STATUSES = ["proposed", "previewed", "approved", "executed", "rejected"]


class ScenarioPlan(Base):
    """A lab scenario transformed by the planner into agentic steps, generated
    policies and optional delegations — staged for preview and approval before
    anything is persisted or enforced."""

    __tablename__ = "scenario_plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    blueprint: Mapped[str] = mapped_column(Text)  # JSON {agents, steps, policies, delegation}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    previewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


RUN_STATUSES = ["pending", "running", "succeeded", "denied", "failed"]


class AgentRun(Base):
    """A LangGraph agent run: the objective the agent was given, the plan it
    produced, the governed actions it took, and the outcome."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    plan_json: Mapped[str] = mapped_column(Text, default="[]")   # list[{action, resource}]
    results_json: Mapped[str] = mapped_column(Text, default="[]")  # list[gateway responses]
    summary: Mapped[str] = mapped_column(Text, default="")
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
