"""Run executor: drive a governed LangGraph agent end-to-end.

Two execution modes share the same graph and planner:

* ``inprocess`` — signs with the agent's private key inside the server process
  and calls the gateway service function directly. Used by synchronous runs and
  tests.
* ``http`` — a real agent runtime (the worker) signs Ed25519 requests and
  submits them over HTTP to the gateway. This is the production-honest path:
  keys stay in the agent runtime, the control plane only sees signed envelopes.
"""

from __future__ import annotations

import time

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.telemetry import meter as _meter

from .registry import get_agent_spec, load_demo_credentials
from .tools import GovernedToolSet
from .workflow import run_graph

settings = get_settings()

_run_counter = None


def _runs_counter():
    global _run_counter
    if _run_counter is None:
        _run_counter = _meter("agents").create_counter(
            "agents.runs", unit="1", description="Governed agent runs"
        )
    return _run_counter


def _db_catalog() -> list[dict]:
    with SessionLocal() as db:
        rows = db.query(models.DataHubEntity).all()
        return [
            {
                "urn": e.urn, "name": e.name, "type": e.type, "domain": e.domain,
                "data_classification": e.data_classification,
                "description": e.description,
                "upstream": e.upstream_json or "[]",
                "downstream": e.downstream_json or "[]",
            }
            for e in rows
        ]


def _inprocess_gateway(private_key_pem: str, agent_id: str):
    from app.routers.requests import evaluate_signed
    from app.schemas import GatewayRequest
    from app.security import canonical_json, sign

    def gateway(action: str, resource: str, target: dict | None = None,
                delegation_token: str = "") -> dict:
        body = GatewayRequest(
            agent_id=agent_id,
            request_id=f"run-{int(time.time_ns()) % 10**10}",
            action={"type": action, "resource": resource},
            target=target,
            delegation_token=delegation_token,
        )
        signature = sign(private_key_pem, canonical_json(body.model_dump()).encode())
        with SessionLocal() as db:
            return evaluate_signed(db, body, signature).model_dump()

    return gateway


def _http_gateway(creds, base_url: str):
    from sdk.controlplane import ControlPlaneClient

    client = ControlPlaneClient(base_url=base_url, creds=creds)

    def gateway(action: str, resource: str, target: dict | None = None,
                delegation_token: str = "") -> dict:
        return client.act(action, resource, delegation_token=delegation_token, target=target)

    return gateway, client


def execute_run(agent_id: str, objective: str, run_id: str | None = None,
                mode: str = "inprocess") -> dict:
    """Run a governed agent against the objective and return the final state."""
    spec = get_agent_spec(agent_id)
    creds = load_demo_credentials(agent_id)

    if mode == "http":
        gateway_fn, client = _http_gateway(creds, settings.self_url)
        tools = GovernedToolSet(gateway_fn, client.catalog, agent_id, spec["role"])
    else:
        gateway_fn = _inprocess_gateway(creds.private_key_pem, agent_id)
        tools = GovernedToolSet(gateway_fn, _db_catalog, agent_id, spec["role"])

    thread_id = run_id or f"run-{int(time.time_ns()) % 10**12}"
    state = run_graph(tools, agent_id, spec["role"], objective, thread_id)

    status = "succeeded"
    if state.get("denied"):
        status = "denied"
    elif not state.get("results"):
        status = "succeeded"

    _runs_counter().add(1, {
        "agent_id": agent_id, "role": spec["role"],
        "actions": len(state.get("results", [])), "status": status,
    })

    return {
        "agent_id": agent_id,
        "role": spec["role"],
        "objective": objective,
        "thread_id": thread_id,
        "plan": state.get("plan", []),
        "plan_source": state.get("plan_source", "rule"),
        "results": state.get("results", []),
        "summary": state.get("summary", ""),
        "status": status,
    }
