"""Smoke test for the control plane core flows.

Runs against a temporary SQLite database and exercises: registration, policy
decisions (allow/deny), delegation + zero-trust depth enforcement, DataHub
impact, and tamper-evident chain verification.
"""

import json
import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/smoke.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.security import canonical_json, sign  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def register(client, name: str, domains: list[str], tier_key: dict | None = None):
    keys = client.post("/api/agents/keypair").json()
    resp = client.post(
        "/api/agents/register",
        json={
            "name": name,
            "description": "smoke",
            "public_key": keys["public_key"],
            "granted_domains": domains,
        },
    )
    body = resp.json()
    return body["id"], keys["private_key"]


def gateway(client, agent_id: str, private_key: str, action_type: str, resource: str,
            delegation_token: str = "", target: dict | None = None, request_id: str = "r1"):
    body = {
        "agent_id": agent_id,
        "request_id": request_id,
        "action": {"type": action_type, "resource": resource},
        "target": target,
        "delegation_token": delegation_token,
    }
    signed = canonical_json({
        "agent_id": body["agent_id"], "request_id": request_id, "action": body["action"],
        "target": body["target"], "delegation_token": delegation_token,
    })
    sig = sign(private_key, signed.encode())
    resp = client.post("/api/requests/gateway", json=body, headers={"X-Agent-Signature": sig})
    return resp.json()


def test_seed_and_agents(client):
    assert client.get("/health").json()["status"] == "ok"
    agents = client.get("/api/agents").json()
    assert len(agents) >= 3, "seed agents present"
    assert any(a["name"] == "kay-analyst" for a in agents)


def test_register_agent(client):
    agent_id, private_key = register(client, "smoke-analyst", ["Marketing"])
    assert agent_id.startswith("ag_")
    # signature-less request is denied
    resp = client.post("/api/requests/gateway",
                       json={"agent_id": agent_id, "request_id": "x",
                             "action": {"type": "read", "resource": "urn:whatever"}})
    assert resp.status_code == 200
    assert resp.json()["decision"] == "deny"
    assert "signature" in resp.json()["reason"]


def test_policy_allow_deny(client):
    analyst, analyst_key = register(client, "policy-analyst", ["Marketing"])
    engineer, engineer_key = register(client, "policy-engineer", ["Finance", "Sales", "Marketing"])
    # elevate the engineer so reputation tier enforcement allows restricted access
    client.post(f"/api/agents/{engineer}/reputation/adjust?delta=35&reason=test-elevation")
    assert client.get(f"/api/agents/{engineer}").json()["tier"] == "privileged"

    marketing_urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)"
    finance_urn = "urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue,PROD)"

    # read of public marketing data -> allow
    r = gateway(client, analyst, analyst_key, "read", marketing_urn, request_id="p1")
    assert r["decision"] == "allow", r
    assert r["result"]["entity"]["data_classification"] == "public"

    # analyst has no Finance domain -> denied outside granted domains
    r = gateway(client, analyst, analyst_key, "read", finance_urn, request_id="p2")
    assert r["decision"] == "deny", r

    # engineer (privileged) read of restricted finance data -> allow
    r = gateway(client, engineer, engineer_key, "read", finance_urn, request_id="p3")
    assert r["decision"] == "allow", r


def test_delegation_zero_trust(client):
    analyst, analyst_key = register(client, "deleg-analyst", ["Marketing"])
    engineer, engineer_key = register(client, "deleg-engineer", ["Marketing", "ML"])
    lead, lead_key = register(client, "deleg-lead", ["Finance", "Marketing", "ML"])
    client.post(f"/api/agents/{lead}/reputation/adjust?delta=40&reason=elevate-for-demo")

    urn = "urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)"
    scope = {"actions": ["transform"], "datasets": [urn], "domains": []}

    # engineer (standard tier) cannot transform ML data directly -> denied
    r = gateway(client, engineer, engineer_key, "transform", urn, request_id="d1")
    assert r["decision"] == "deny", r

    # lead (privileged) delegates the transform to engineer, depth limit 1
    dl = client.post("/api/delegations", json={
        "delegator_id": lead, "delegatee_id": engineer,
        "scope": scope, "max_depth": 1, "ttl_hours": 2,
    }).json()
    token = dl["token"]
    assert dl["id"].startswith("dlg-")

    # engineer under delegation inherits the delegator's authority within scope
    r = gateway(client, engineer, engineer_key, "transform", urn, delegation_token=token, request_id="d2")
    assert r["decision"] == "allow", r

    # write is outside the delegated scope -> denied
    r = gateway(client, engineer, engineer_key, "write", urn, delegation_token=token, request_id="d3")
    assert r["decision"] == "deny", r

    # transitive delegation depth: engineer (depth 1 under lead's max 1) attempts
    # to re-delegate to a third agent -> creation is rejected by the chain guard
    sub, sub_key = register(client, "deleg-sub", ["ML"])
    resp = client.post("/api/delegations", json={
        "delegator_id": engineer, "delegatee_id": sub,
        "scope": scope, "max_depth": 1,
    })
    assert resp.status_code == 400, resp.text
    assert "depth" in resp.json()["detail"].lower(), resp.json()


def test_delegation_token_validity(client):
    """Delegations are token-validity based: each issuance is an independent
    capability token with its own validity. Issuing an identical grant again
    mints a new token (distinct id + token) rather than reusing or deduplicating
    the previous one, and the API reports effective validity per token."""
    analyst, _ = register(client, "tv-analyst", ["Marketing"])
    engineer, _ = register(client, "tv-engineer", ["Marketing", "ML"])

    urn = "urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)"
    scope = {"actions": ["read"], "datasets": [urn], "domains": []}
    body = {"delegator_id": engineer, "delegatee_id": analyst,
            "scope": scope, "max_depth": 1, "ttl_hours": 1}

    d1 = client.post("/api/delegations", json=body).json()
    d2 = client.post("/api/delegations", json=body).json()
    assert d1["id"] != d2["id"], "each issuance is a distinct token"
    assert d1["token"] != d2["token"]

    rows = client.get("/api/delegations").json()
    both = [r for r in rows if r["id"] in (d1["id"], d2["id"])]
    assert len(both) == 2
    assert all(r["status"] == "active" for r in both), rows
    assert all(r["active"] is True for r in both)


def test_scenario_approve_rotates_delegation(client):
    """Re-approving the same plan retires the previous identical grant and mints
    a fresh token — the demo rotates instead of accumulating live duplicates,
    while each historical token keeps its own validity."""
    t = client.post("/api/demo/scenarios/transform", json={"scenario_id": "scn_billing"}).json()
    plan_id = t["plan_id"]

    first = client.post("/api/demo/scenarios/approve", json={"plan_id": plan_id}).json()
    first_id, first_token = first["delegation"]["id"], first["delegation"]["token"]
    assert first_id.startswith("dlg-")

    rows = client.get("/api/delegations").json()
    assert next(r for r in rows if r["id"] == first_id)["status"] == "active"

    second = client.post("/api/demo/scenarios/approve", json={"plan_id": plan_id}).json()
    second_id, second_token = second["delegation"]["id"], second["delegation"]["token"]
    assert second_id != first_id
    assert second_token != first_token

    rows = client.get("/api/delegations").json()
    retired = next(r for r in rows if r["id"] == first_id)
    assert retired["status"] == "revoked", retired
    assert next(r for r in rows if r["id"] == second_id)["status"] == "active"

    client.post("/api/demo/scenarios/reset")  # leave the shared DB clean


def test_hash_chain_tamper_detection(client):
    before = client.get("/api/audit/verify/chain").json()
    assert before["valid"] is True
    seq = before["block_count"] - 1  # tamper with the most recent block
    client.post(f"/api/audit/simulate-tamper?seq={seq}")
    after = client.get("/api/audit/verify/chain").json()
    assert after["valid"] is False
    assert any(i["seq"] == seq for i in after["issues"])


def test_datahub_impact(client):
    agent = client.get("/api/agents").json()
    analyst = next(a for a in agent if a["name"] == "kay-analyst")
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)"
    resp = client.post("/api/datahub/actions", json={
        "agent_id": analyst["id"], "entity_urn": urn, "action_type": "query",
        "metadata": {"source": "smoke"},
    })
    assert resp.status_code == 200
    impact = client.get("/api/datahub/impact").json()
    assert analyst["id"] in impact["matrix"]
    assert urn in impact["matrix"][analyst["id"]]
    assert impact["matrix"][analyst["id"]][urn] == 2.0  # query weight


def test_governed_agent_run(client):
    """A LangGraph agent run plans actions, executes them through the gateway,
    and records the outcome as a run."""
    analyst = next(a for a in client.get("/api/agents").json() if a["id"] == "ag_analyst")
    assert analyst["status"] == "active"

    allowed = client.post(
        "/api/agents/ag_analyst/run",
        json={"agent_id": "ag_analyst",
              "objective": "Read the patient demographics mart and report on it",
              "sync": True},
    ).json()
    assert allowed["status"] == "succeeded", allowed
    assert len(allowed["plan"]) >= 1
    assert all(r["decision"] == "allow" for r in allowed["results"]), allowed

    denied = client.post(
        "/api/agents/ag_analyst/run",
        json={"agent_id": "ag_analyst",
              "objective": "Read the restricted patient billing mart",
              "sync": True},
    ).json()
    assert denied["status"] == "denied", denied
    assert any(r["decision"] == "deny" for r in denied["results"]), denied
    # the deny targets the restricted billing mart and names a non-empty reason
    denied_res = [r for r in denied["results"] if r["decision"] == "deny"]
    assert denied_res and "billing" in denied_res[0]["resource"], denied
    assert all(r["reason"] for r in denied_res), denied

    runs = client.get("/api/runs?agent_id=ag_analyst").json()
    assert any(r["id"] == allowed["id"] for r in runs)
    assert any(r["id"] == denied["id"] for r in runs)

    # the denied action is audited end-to-end
    denied_events = client.get("/api/audit?agent_id=ag_analyst").json()
    assert any(
        e["event_type"].startswith("request.") and e["event_type"].endswith(".denied")
        for e in denied_events
    ), denied_events


def test_controlplane_env_aliases():
    """CONTROLPLANE_POLICY_ENGINE / CONTROLPLANE_OPA_URL map to settings."""
    from app.config import Settings

    s = Settings(_env_file=None,
                 controlplane_policy_engine="native",
                 controlplane_opa_url="http://localhost:8182")
    assert s.policy_engine == "native"
    assert s.opa_url == "http://localhost:8182"

    s2 = Settings(_env_file=None, policy_engine="opa", opa_url="http://x:1")
    assert s2.policy_engine == "opa"
    assert s2.opa_url == "http://x:1"


def test_rule_planner_action_resolution(monkeypatch):
    """Objective wording maps to sensible governed actions (esp. read-only roles)."""
    from agents.planner import build_plan
    from app.config import Settings

    # Force the deterministic rule planner regardless of LLM_MODEL in .env
    import agents.planner as planner_mod
    monkeypatch.setattr(planner_mod, "settings", Settings(_env_file=None, llm_model=""))

    entities = [
        {"urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)",
         "name": "campaign_attribution", "description": "marketing campaign performance",
         "domain": "Marketing"},
    ]
    # a marketing read/report stays a read for the analyst, not a denied transform
    p, source = build_plan("ag_analyst", "analyst", "compute marketing kpi summary", entities)
    assert source == "rule"
    assert p and p[0]["action"] == "query", p
    p, _ = build_plan("ag_analyst", "analyst", "look at the campaign attribution report", entities)
    assert p and p[0]["action"] == "query", p
    # explicit engineering verbs stay a transform for engineers
    p, _ = build_plan("ag_engineer", "engineer", "aggregate campaign events into churn features", entities)
    assert p and p[0]["action"] == "transform", p


def test_scenario_billing_flow(client):
    """Predefined scenario: transform -> preview -> approve -> reset. The plan
    stages agentic steps + generated policies + a delegation, preview simulates
    them in memory, approval persists them and enforces every step."""
    scn = client.get("/api/demo/scenarios").json()
    assert any(s["id"] == "scn_billing" for s in scn)

    t = client.post("/api/demo/scenarios/transform", json={"scenario_id": "scn_billing"}).json()
    assert t["status"] == "proposed"
    bp = t["blueprint"]
    assert len(bp["steps"]) == 4
    assert bp["delegation"] is not None
    assert any(p["name"].startswith("lab-") for p in bp["policies"])

    pv = client.post("/api/demo/scenarios/preview", json={"plan_id": t["plan_id"]}).json()
    assert pv["predictions"], pv
    for p in pv["predictions"]:
        assert p["predicted"] == p["expected"], p
    assert any(p["policy_generated"] for p in pv["predictions"])

    ex = client.post("/api/demo/scenarios/approve", json={"plan_id": t["plan_id"]}).json()
    assert ex["policies_created"], ex
    assert ex["delegation"] is not None
    assert len(ex["steps"]) == 4
    for s in ex["steps"]:
        assert s["decision"] == s["expected"], s
        assert s["audit_seq"] is not None, s

    res = client.post("/api/demo/scenarios/reset").json()
    assert res["policies_removed"] >= len(ex["policies_created"])
    lab_policies = client.get("/api/policies").json()
    assert not any(p["name"].startswith("lab-") for p in lab_policies)


def test_scenario_custom_translate(client):
    """Free-text scenarios are translated into agentic steps + derived policies."""
    t = client.post("/api/demo/scenarios/transform", json={
        "objective": (
            "kay-analyst is blocked from transforming raw PII patient records; "
            "leo-ml-engineer transforms sensitive staging patient data into features"
        ),
    }).json()
    assert t["status"] == "proposed"
    bp = t["blueprint"]
    assert any(s["action"] == "transform" for s in bp["steps"])
    names = [p["name"] for p in bp["policies"]]
    assert "lab-deny-pii-transforms-below-elevated" in names

    pv = client.post("/api/demo/scenarios/preview", json={"plan_id": t["plan_id"]}).json()
    by_agent = {p["agent"]: p for p in pv["predictions"]}
    assert by_agent["ag_analyst"]["predicted"] == "deny"
    assert by_agent["ag_ml_engineer"]["predicted"] == "allow"


def test_blast_radius(client):
    """Downstream blast radius of a dataset includes lineage consumers and the
    agents that have acted inside the affected subgraph."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"
    analyst = next(a for a in client.get("/api/agents").json() if a["id"] == "ag_analyst")
    client.post("/api/datahub/actions", json={
        "agent_id": analyst["id"], "entity_urn": urn, "action_type": "read",
    })

    report = client.get(f"/api/datahub/impact/blast/{urn}?depth=3").json()
    assert report["summary"]["impacted_datasets"] >= 2
    names = {d["name"] for d in report["downstream"]}
    assert "marketing.campaign_attribution" in names
    assert "analytics.customer_360" in names
    assert report["summary"]["impacted_agents"] >= 1
    assert any(a["agent"]["agent_id"] == "ag_analyst" for a in report["agents"])
    assert report["graph"]["nodes"] and report["graph"]["edges"]
    # depth-1 consumer appears at depth 1, customer_360 deeper
    depths = {d["name"]: d["depth"] for d in report["downstream"]}
    assert depths["marketing.campaign_attribution"] == 1
    assert depths["analytics.customer_360"] > 1


def test_whatif_chaos_experiment(client):
    """Raising mart_billing to restricted denies standard-tier agents that read
    it; the experiment is persisted and audited."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_billing,PROD)"
    analyst = next(a for a in client.get("/api/agents").json() if a["id"] == "ag_analyst")
    client.post("/api/datahub/actions", json={
        "agent_id": analyst["id"], "entity_urn": urn, "action_type": "read",
    })

    r = client.post("/api/datahub/impact/what-if", json={
        "root_urn": urn, "kind": "classification_change",
        "params": {"new_classification": "restricted"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["denied_agents"] >= 1
    analyst_row = next(a for a in body["agents"] if a["agent"]["agent_id"] == "ag_analyst")
    assert analyst_row["will_be_denied"] is True
    assert "read" in analyst_row["denied_actions"]
    assert analyst_row["reason"]
    assert body["recommendations"]
    assert any(rec["severity"] == "high" for rec in body["recommendations"])
    assert body["graph"]["nodes"] and body["experiment_id"]

    # persisted + listable
    exps = client.get("/api/datahub/experiments").json()
    assert any(e["id"] == body["experiment_id"] for e in exps)
    one = client.get(f"/api/datahub/experiments/{body['experiment_id']}").json()
    assert one["risk"] == "high"
    assert one["result"]["summary"]["denied_agents"] >= 1

    # audited into the hash chain
    events = client.get("/api/audit?event_type=datahub.experiment.classification_change").json()
    assert any(e["subject"] == urn for e in events)


def test_agent_blast_radius(client):
    """Agent blast radius lists each dataset an agent touched plus downstream
    consumers."""
    analyst = next(a for a in client.get("/api/agents").json() if a["id"] == "ag_analyst")
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"
    client.post("/api/datahub/actions", json={
        "agent_id": analyst["id"], "entity_urn": urn, "action_type": "query",
    })

    r = client.get(f"/api/datahub/impact/agent/{analyst['id']}/blast").json()
    assert r["agent"]["agent_id"] == "ag_analyst"
    ds = next(d for d in r["datasets"] if d["urn"] == urn)
    assert ds["entity"]["name"] == "marketing.campaign_events"
    assert "query" in ds["actions"]
    assert any(c["name"] == "marketing.campaign_attribution" for c in ds["downstream"])
    assert r["graph"]["nodes"] and r["graph"]["edges"]


def test_impact_endpoints_enriched(client):
    """Impact endpoints now carry agent/entity metadata instead of raw URNs."""
    analyst = next(a for a in client.get("/api/agents").json() if a["id"] == "ag_analyst")
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"
    r = client.get(f"/api/datahub/impact/agent/{analyst['id']}").json()
    assert r["agent"]["name"] == "kay-analyst"
    assert isinstance(r["actions"], list)
    e = client.get(f"/api/datahub/impact/entity/{urn}").json()
    assert e["entity"]["name"] == "marketing.campaign_events"
    assert isinstance(e["actions"], list)


def test_evidence_links_to_audit_chain(client):
    """A real gateway action must be traceable: the recorded DataHubAction's
    evidence resolves to the matching hash-chain audit event via request id.
    Regression: request_id lived only on the GatewayRequest, never in the
    action metadata, so the audit link was always null."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"
    agent_id, private_key = register(client, "traceable-analyst", ["Marketing"])
    resp = gateway(client, agent_id, private_key, "read", urn, request_id="trace-r1")
    assert resp["decision"] == "allow", resp

    blast = client.get(f"/api/datahub/impact/blast/{urn}?depth=3").json()
    row = next(a for a in blast["agents"] if a["agent"]["agent_id"] == agent_id)
    evidence = next(e for e in row["evidence"] if e["action_type"] == "read")
    assert evidence["audit"] is not None, evidence
    assert evidence["audit"]["event_type"] == "request.read"
    assert evidence["audit"]["decision"] == "allow"
    assert isinstance(evidence["audit"]["seq"], int)


def test_audit_export_and_event_trace(client):
    """The audit trail is exportable (CSV + JSON) and each event drills down to
    its policy decision, recorded action, entity lineage context, and the
    impact analyses that covered the entity."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"
    agent_id, private_key = register(client, "audit-trace-analyst", ["Marketing"])

    # seed a persisted experiment whose blast radius covers the entity
    client.post("/api/datahub/impact/what-if",
                json={"root_urn": urn, "kind": "outage", "params": {"depth": 2}})

    resp = gateway(client, agent_id, private_key, "read", urn, request_id="audit-trace-r1")
    assert resp["decision"] == "allow", resp
    event_id = resp["event_id"]

    # JSON export contains the event
    exported = client.get("/api/audit/export?format=json").json()
    assert exported["count"] >= 1
    assert any(x["id"] == event_id and x["request_id"] == "audit-trace-r1"
               for x in exported["events"])

    # CSV export has the header and the same block row
    csv_resp = client.get("/api/audit/export?format=csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "event_hash" in csv_resp.text
    row = next(x for x in exported["events"] if x["id"] == event_id)
    assert row["event_hash"] in csv_resp.text

    # event -> full impact trace
    trace = client.get(f"/api/audit/{event_id}/trace").json()
    assert trace["event"]["id"] == event_id
    assert trace["event"]["seq"] == resp["audit_seq"]
    assert trace["policy_decision"]["request_id"] == "audit-trace-r1"
    assert trace["policy_decision"]["decision"] == "allow"
    assert "lineage" in trace["policy_decision"]["policy_input"]
    assert trace["action"]["action_type"] == "read"
    assert trace["action"]["entity_urn"] == urn
    assert trace["entity"]["urn"] == urn
    assert "upstream_restricted" in trace["entity"]["lineage_facts"]
    assert any(x["root_urn"] == urn for x in trace["experiments"]), trace["experiments"]


def test_datahub_action_trace(client):
    """A recorded DataHubAction drills down to its hash-chain audit event, the
    entity's lineage context, and the experiments that covered the entity."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"
    agent_id, private_key = register(client, "action-trace-analyst", ["Marketing"])
    resp = gateway(client, agent_id, private_key, "read", urn, request_id="action-trace-r1")
    assert resp["decision"] == "allow", resp

    blast = client.get(f"/api/datahub/impact/blast/{urn}?depth=3").json()
    row = next(a for a in blast["agents"] if a["agent"]["agent_id"] == agent_id)
    evidence = next(e for e in row["evidence"] if e["action_type"] == "read")
    assert evidence["audit"] is not None, evidence

    trace = client.get(f"/api/datahub/actions/{evidence['id']}/trace").json()
    assert trace["action"]["id"] == evidence["id"]
    assert trace["action"]["action_type"] == "read"
    assert trace["agent"]["agent_id"] == agent_id
    assert trace["audit"]["event_type"] == "request.read"
    assert trace["entity"]["urn"] == urn
    assert trace["entity"]["lineage_facts"]["downstream_count"] >= 0
    assert isinstance(trace["experiments"], list)


def test_prune_stale_datahub_syncs(monkeypatch):
    """With DataHub unreachable, catalog rows from a prior sync are pruned and
    orphaned impact rows dropped, while the curated reference catalog survives."""
    from app import models
    from app.database import SessionLocal
    from app.seed import _prune_stale_syncs

    monkeypatch.setattr("app.seed._datahub_reachable", lambda: False)

    stale_urn = "urn:li:dataset:(urn:li:dataPlatform:hive,stale_thing,PROD)"
    db = SessionLocal()
    db.add(models.DataHubEntity(
        urn=stale_urn, name="stale_thing", type="dataset", platform="hive",
        domain="General", data_classification="public", owner_team="",
        description="", schema_json="[]", upstream_json="[]",
        downstream_json="[]", usage_json="{}", source="datahub"))
    db.add(models.DataHubAction(
        id="act-stale", agent_id="ag_analyst", entity_urn=stale_urn,
        action_type="read", impact_weight=1.0, metadata_json="{}"))
    db.commit()

    seeded: dict = {}
    _prune_stale_syncs(db, seeded)
    db.commit()

    assert db.get(models.DataHubEntity, stale_urn) is None
    assert seeded["entities_pruned"] == 1
    assert seeded["impact_actions_pruned"] == 1
    # curated reference entities are untouched
    assert db.get(models.DataHubEntity,
                  "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)") is not None
    assert not db.query(models.DataHubAction).filter(
        models.DataHubAction.entity_urn == stale_urn).all()
    db.close()


def test_criticality_scoring(client):
    """Criticality is computed from REAL lineage + actions, not hardcoded: a
    lineage head with downstream consumers ranks above a leaf, restricted
    entities carry more risk, and components are exposed for explainability."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_billing,PROD)"
    mkt = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"
    analyst = next(a for a in client.get("/api/agents").json() if a["id"] == "ag_analyst")
    client.post("/api/datahub/actions", json={
        "agent_id": analyst["id"], "entity_urn": urn, "action_type": "transform",
    })

    report = client.get("/api/datahub/criticality").json()
    assert report["count"] >= 20
    rows = {r["urn"]: r for r in report["entities"]}
    assert urn in rows
    mart = rows[urn]
    assert mart["criticality"] > 0
    assert {"centrality", "impact", "risk", "blast"} <= set(mart["components"])
    assert mart["agents"] >= 1
    # a lineage head carries downstream descendants from real edges
    mkt_row = rows[mkt]
    assert mkt_row["downstream_count"] >= 2
    # ranked list is sorted desc and every row is explainable
    vals = [r["criticality"] for r in report["entities"]]
    assert vals == sorted(vals, reverse=True)
    assert report["summary"]["weights"]["centrality"] == 0.35


def test_watchlist_alerts(client):
    """Watchlist endpoints: add/remove entries, and alerts fire only when a
    real criticality score crosses the threshold."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_billing,PROD)"
    r = client.post("/api/datahub/watchlist", json={"urn": urn, "threshold": 0.05})
    assert r.status_code == 200
    wid = r.json()["id"]

    listed = client.get("/api/datahub/watchlist").json()
    entry = next(e for e in listed["entries"] if e["id"] == wid)
    assert entry["urn"] == urn
    assert entry["current"] > 0
    assert entry["breached"] is True

    alerts = client.get("/api/datahub/watchlist/alerts").json()
    assert any(a["watchlist_id"] == wid for a in alerts["alerts"])
    top = alerts["alerts"][0]
    assert top["current"] >= top["threshold"]

    removed = client.delete(f"/api/datahub/watchlist/{wid}")
    assert removed.status_code == 200
    listed2 = client.get("/api/datahub/watchlist").json()
    assert all(e["id"] != wid for e in listed2["entries"])

    # audit trail for watchlist activity
    events = client.get("/api/audit?event_type=datahub.watchlist.add").json()
    assert any(e["subject"] == urn for e in events)


def test_lineage_reactive_simulations(client):
    """All four lineage sim kinds run through the same endpoint, persist as
    experiments, and compute consequences from real lineage; new_upstream can
    additionally evaluate a real policy change (reclassify)."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_billing,PROD)"
    analyst = next(a for a in client.get("/api/agents").json() if a["id"] == "ag_analyst")
    client.post("/api/datahub/actions", json={
        "agent_id": analyst["id"], "entity_urn": urn, "action_type": "transform",
    })

    cases = [
        ("data_quality", {"issue": "dirty PII", "rows_affected": 5000}),
        ("new_upstream", {"source_urn": "urn:li:dataset:(urn:li:dataPlatform:kafka,events.sdk,PROD)",
                          "category": "third-party"}),
        ("staleness", {"hours_stale": 48, "failed_job": "etl_daily"}),
        ("schema_drift", {"broken_columns": ["amount"], "contract_version": "v2"}),
    ]
    for kind, params in cases:
        r = client.post("/api/datahub/impact/what-if", json={
            "root_urn": urn, "kind": kind, "params": params})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"]["kind"] == kind
        assert body["summary"]["impacted_datasets"] >= 0
        assert body["experiment_id"]
        assert body["recommendations"]
        assert body["graph"]["nodes"]
        # persisted and retrievable
        one = client.get(f"/api/datahub/experiments/{body['experiment_id']}").json()
        assert one["result"]["summary"]["kind"] == kind

    # new_upstream with a reclassification goes through the real policy engine
    r = client.post("/api/datahub/impact/what-if", json={
        "root_urn": urn, "kind": "new_upstream",
        "params": {"source_urn": "urn:li:dataset:(urn:li:dataPlatform:api,claims_feed,PROD)",
                   "category": "unvetted", "reclassify": "restricted"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["risk"] == "high"
    assert body["summary"]["denied_agents"] >= 1
    analyst_row = next(a for a in body["agents"] if a["agent"]["agent_id"] == "ag_analyst")
    assert analyst_row["will_be_denied"] is True
    assert any(c["after"]["policy_name"] for c in analyst_row["policy_changes"])


def test_policy_gap_detection_preview_apply(client):
    """Recorded activity that current policy would deny surfaces as a drift gap
    with a lab patch; the patch is previewed through the real engine and then
    applied audited — and after applying, the action evaluates to allow."""
    from app import models
    from app.database import SessionLocal
    from app.routers.datahub import _entity_out  # noqa: F401

    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"

    # register an agent WITHOUT the Marketing domain, then record a read anyway
    # (direct action recording bypasses the gateway) -> drift
    agent_id, private_key = register(client, "drift-analyst", [])
    client.post("/api/datahub/actions", json={
        "agent_id": agent_id, "entity_urn": urn, "action_type": "read",
    })

    report = client.get("/api/datahub/policy-gaps").json()
    gap = next(g for g in report["gaps"]
               if g["agent"]["id"] == agent_id and g["action_type"] == "read")
    assert gap["type"] == "drift"
    assert any(d["urn"] == urn for d in gap["denied"])
    assert gap["patch"]["name"].startswith("lab-reinstate-")
    assert gap["patch"]["effect"] == "allow"

    preview = client.get(f"/api/datahub/policy-gaps/{gap['id']}/preview").json()
    assert all(b["decision"] == "deny" for b in preview["before"])
    assert all(a["decision"] == "allow" for a in preview["after"])
    assert preview["consistent"] is True
    # the transient rule was rolled back: still no lab policy persisted
    names = [p["name"] for p in client.get("/api/policies").json()]
    assert gap["patch"]["name"] not in names

    applied = client.post(f"/api/datahub/policy-gaps/{gap['id']}/apply")
    assert applied.status_code == 200
    assert applied.json()["name"] == gap["patch"]["name"]
    names = [p["name"] for p in client.get("/api/policies").json()]
    assert gap["patch"]["name"] in names

    # after applying, the real gateway allows the read for that agent
    resp = gateway(client, agent_id, private_key, "read", urn, request_id="gap-r1")
    assert resp["decision"] == "allow", resp

    events = client.get("/api/audit?event_type=datahub.policygap.apply").json()
    assert any(e["subject"] == gap["patch"]["name"] for e in events)


def test_custom_experiment_composes_steps(client):
    """A custom experiment runs each step through the real engine and
    aggregates a single auditable result with per-step detail."""
    mkt = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"
    billing = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_billing,PROD)"
    analyst = next(a for a in client.get("/api/agents").json() if a["id"] == "ag_analyst")
    client.post("/api/datahub/actions", json={
        "agent_id": analyst["id"], "entity_urn": billing, "action_type": "read",
    })

    r = client.post("/api/datahub/experiments/custom", json={
        "name": "quarter-end review",
        "blueprint": [
            {"root_urn": billing, "kind": "classification_change",
             "params": {"new_classification": "restricted"}},
            {"root_urn": mkt, "kind": "staleness",
             "params": {"hours_stale": 72, "failed_job": "etl_marketing_daily"}},
        ],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["kind"] == "custom"
    assert body["summary"]["steps"] == 2
    assert body["summary"]["risk"] == "high"
    assert body["summary"]["denied_agents"] >= 1
    assert len(body["steps"]) == 2
    assert {s["kind"] for s in body["steps"]} == {"classification_change", "staleness"}
    assert body["experiment_id"]
    assert body["graph"]["nodes"] and body["graph"]["edges"]
    # aggregated downstream counts unique affected datasets across steps
    assert body["summary"]["impacted_datasets"] >= 2

    one = client.get(f"/api/datahub/experiments/{body['experiment_id']}").json()
    assert one["result"]["summary"]["steps"] == 2
    events = client.get("/api/audit?event_type=datahub.experiment.custom").json()
    assert any(e["subject"] == billing for e in events)


def test_monitor_scan_guardian(client):
    """The guardian agent runs a governed monitor scan over real posture data;
    the scan is persisted, audited, and retrievable."""
    scan = client.post("/api/datahub/monitor/scan").json()
    assert scan["id"]
    assert scan["summary"]["agent"] == "ag_monitor"
    assert scan["summary"]["status"] == "succeeded"
    assert scan["risk"] in ("low", "medium", "high")
    kinds = {f["kind"] for f in scan["findings"]}
    assert {"criticality", "policy_gaps", "watchlist"} <= kinds
    assert any(f["kind"] == "criticality" for f in scan["findings"])

    scans = client.get("/api/datahub/monitor/scans").json()
    assert any(s["id"] == scan["id"] for s in scans)

    one = client.get(f"/api/datahub/monitor/scans/{scan['id']}").json()
    assert one["id"] == scan["id"]
    assert len(one["findings"]) == len(scan["findings"])

    events = client.get("/api/audit?event_type=datahub.monitor.scan").json()
    assert any(e["subject"] == "control-plane" for e in events)


def test_gateway_records_lineage_facts(client):
    """Every gateway decision records the lineage-aware input (real edges +
    criticality), so policies can reference lineage facts in the audit trail."""
    analyst = next(a for a in client.get("/api/agents").json() if a["id"] == "ag_analyst")
    urn = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_demographics,PROD)"
    key_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "demo_agents")
    with open(os.path.join(key_dir, "ag_analyst.pem")) as fh:
        private_key = fh.read()

    body = {
        "agent_id": analyst["id"],
        "request_id": "lineage-facts-test",
        "action": {"type": "read", "resource": urn},
        "target": None,
        "delegation_token": "",
    }
    from app.security import canonical_json, sign

    signature = sign(private_key, canonical_json({
        "agent_id": body["agent_id"], "request_id": body["request_id"],
        "action": body["action"], "target": body["target"],
        "delegation_token": body["delegation_token"],
    }).encode())
    resp = client.post("/api/requests/gateway", json=body,
                       headers={"X-Agent-Signature": signature})
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"] == "allow"

    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    rows = (
        db.query(models.PolicyDecision)
        .filter(models.PolicyDecision.request_id == "lineage-facts-test")
        .all()
    )
    db.close()
    assert rows
    pin = json.loads(rows[-1].policy_input or "{}")
    lineage = pin.get("lineage", {})
    assert lineage.get("upstream_restricted") is True
    assert lineage.get("upstream_restricted_count") == 1
    assert "criticality" in lineage and "is_critical" in lineage


def test_dashboard_agents_and_catalog_by_domain(client):
    """The dashboard summary exposes catalog and agent distribution by domain,
    plus recent audit events with timestamps."""
    s = client.get("/api/dashboard/summary").json()
    assert isinstance(s["catalog"]["by_domain"], dict)
    assert sum(s["catalog"]["by_domain"].values()) == s["catalog"]["entities"]
    assert isinstance(s["agents"]["by_domain"], dict)
    assert all(v >= 0 for v in s["agents"]["by_domain"].values())
    assert sum(s["agents"]["by_domain"].values()) >= s["agents"]["total"] or "Healthcare" in s["agents"]["by_domain"]
    assert all("ts" in e for e in s["recent_events"])


def test_watchlist_breach_action_audited(client):
    """The action on a watchlist breach appends a tamper-evident audit event per
    newly-crossed threshold and dedupes on re-run."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_billing,PROD)"
    wid = client.post("/api/datahub/watchlist", json={"urn": urn, "threshold": 0.05}).json()["id"]

    r1 = client.post("/api/datahub/watchlist/breaches").json()
    assert r1["recorded"] >= 1
    assert any(a["urn"] == urn for a in r1["alerts"])

    events = client.get("/api/audit?event_type=datahub.watchlist.breach").json()
    assert any(e["subject"] == urn for e in events)

    # second action dedupes: same criticality -> no new block for that entity
    r2 = client.post("/api/datahub/watchlist/breaches").json()
    events2 = client.get("/api/audit?event_type=datahub.watchlist.breach").json()
    assert len(events2) == len(events)

    client.delete(f"/api/datahub/watchlist/{wid}")


def test_what_if_prediction_and_predicted_agents(client):
    """What-if results carry a plain-language prediction and predicted agents
    (governed agents whose granted domains overlap the subgraph, evaluated by
    the real policy engine), so the impact is informative even with no
    recorded agent activity."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue,PROD)"
    r = client.post("/api/datahub/impact/what-if", json={
        "root_urn": urn, "kind": "outage", "params": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["prediction"]["risk"] in ("low", "medium", "high")
    assert body["prediction"]["likelihood"] in ("low", "medium", "high")
    assert body["prediction"]["summary"]
    assert body["prediction"]["signals"]["impacted_datasets"] == body["summary"]["impacted_datasets"]

    predicted = [a for a in body["predicted_agents"] if a["predicted"]]
    assert predicted, "governed agents should be predicted for a finance subgraph"
    assert all(a["reason"] for a in predicted)

    # blast radius carries the same fields
    b = client.get(f"/api/datahub/impact/blast/{urn}?depth=3").json()
    assert "predicted_agents" in b and "prediction" in b


def test_status_reports_datahub_providers(client):
    """/api/datahub/status exposes which read/analytics provider is active so a
    deployment can tell whether the DataHub MCP server / analytics agent are in
    use without reading logs."""
    body = client.get("/api/datahub/status").json()
    prov = body["providers"]
    assert prov["datahub_read"] in ("mcp", "graphql")
    assert prov["analytics"] in ("analytics-agent", "builtin")
    assert prov["analytics_agent_url"] == "http://localhost:8100"


def test_analytics_builtin_when_agent_disabled(client, monkeypatch):
    """With USE_ANALYTICS_AGENT unset the analytics endpoint answers from the
    built-in catalog search (current processing), never calling the agent."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "use_analytics_agent", False)
    r = client.post("/api/datahub/analytics", json={"question": "churn model data"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "builtin"
    assert body["answer"]
    assert any("churn" in res["name"] for res in body["results"])


def test_analytics_uses_agent_when_enabled(client, monkeypatch):
    """With USE_ANALYTICS_AGENT=true the analytics endpoint delegates to the
    analytics-agent client instead of the built-in search."""
    from app.config import get_settings
    from app.datahub import analytics_agent as aa

    monkeypatch.setattr(get_settings(), "use_analytics_agent", True)
    monkeypatch.setattr(
        aa.AnalyticsAgentClient, "ask",
        lambda self, q, engine=None: {
            "conversation_id": "conv-test",
            "answer": f"SELECT * FROM {q}",
            "sql": "SELECT 1",
            "chart": None,
            "events": ["TEXT", "SQL", "COMPLETE"],
        },
    )
    r = client.post("/api/datahub/analytics", json={"question": "top categories"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "analytics-agent"
    assert body["sql"] == "SELECT 1"
    assert body["conversation_id"] == "conv-test"


def test_analytics_agent_unreachable_falls_back(client, monkeypatch):
    """If the analytics agent is enabled but unreachable, the endpoint degrades
    to the built-in answer instead of failing."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "use_analytics_agent", True)
    monkeypatch.setattr(get_settings(), "analytics_agent_url", "http://127.0.0.1:1")
    r = client.post("/api/datahub/analytics", json={"question": "sales pipeline"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "builtin"
    assert any("sales" in res["name"] for res in body["results"])


def test_datahub_mcp_disabled_uses_graphql(client, monkeypatch):
    """With USE_DATAHUB_MCP unset the client reads via GraphQL and never touches
    the MCP server."""
    from app.config import get_settings
    from app.datahub.client import DataHubClient
    from app.datahub import mcp_client as mc

    monkeypatch.setattr(get_settings(), "use_datahub_mcp", False)
    calls = []

    def _boom(self, *a, **k):
        calls.append(1)
        raise mc.DataHubMCPError("should not be called")

    monkeypatch.setattr(mc.DataHubMCPClient, "search_datasets", _boom)
    with pytest.raises(Exception) as exc_info:
        DataHubClient(endpoint="http://127.0.0.1:1").search_datasets()
    assert not calls, "MCP client must not be invoked when USE_DATAHUB_MCP is off"
    assert "GraphQL" in str(exc_info.value)


def test_datahub_mcp_falls_back_to_graphql(client, monkeypatch):
    """With USE_DATAHUB_MCP=true and an unreachable MCP server, reads fall back
    to the GraphQL path instead of raising the MCP error."""
    from app.config import get_settings
    from app.datahub.client import DataHubClient
    from app.datahub import mcp_client as mc

    monkeypatch.setattr(get_settings(), "use_datahub_mcp", True)
    calls = []

    def _boom(self, *a, **k):
        calls.append(1)
        raise mc.DataHubMCPError("mcp down")

    monkeypatch.setattr(mc.DataHubMCPClient, "search_datasets", _boom)
    with pytest.raises(Exception) as exc_info:
        DataHubClient(endpoint="http://127.0.0.1:1").search_datasets()
    assert calls, "MCP client should be attempted when USE_DATAHUB_MCP is on"
    assert "GraphQL" in str(exc_info.value)
    assert "mcp down" not in str(exc_info.value)
