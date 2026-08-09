"""Governed toolset for LangGraph agents.

Every tool is a thin wrapper around a gateway call. The gateway is injected so
the same graph runs over real HTTP (worker process, signed Ed25519 requests) or
in-process (server-side synchronous runs) — governance, audit, and reputation
are identical either way because they happen inside the control plane.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.telemetry import meter as _meter, tracer as _tracer

GATEWAY_TOOLS = ("read", "query", "transform", "write", "ingest", "deploy")

# Read-only governance tools (guardian role). These inspect the control plane's
# DataHub posture — criticality, policy gaps, watchlist alerts — and are
# evaluated by real data; they never pass through the gateway because they are
# not actions on a dataset. The guardian's calls are still audited at run level.
GOVERNANCE_TOOLS = ("criticality", "policy_gaps", "watchlist_alerts")

ALL_TOOLS = GATEWAY_TOOLS + GOVERNANCE_TOOLS


def _action_span(name: str, attributes: dict):
    """Context manager producing an OTel span for one governed tool call."""
    tr = _tracer("agents")
    return tr.start_as_current_span(name, attributes=attributes)


@dataclass
class GovernedToolSet:
    """Tools available to an agent, all funneling through the gateway.

    ``gateway_fn`` signature: ``(action_type, resource, target=None,
    delegation_token="") -> dict`` (a GatewayResponse).
    ``catalog_fn`` signature: ``() -> list[dict]`` (catalog entities).
    """

    gateway_fn: object
    catalog_fn: object = field(default=lambda: [])
    agent_id: str = ""
    role: str = ""

    def _gateway(self, action: str, resource: str, target: dict | None = None,
                 delegation_token: str = "") -> dict:
        with _action_span(
            f"agents.{action}",
            {"agent.id": self.agent_id, "agent.role": self.role,
             "gateway.action": action, "gateway.resource": resource},
        ):
            return self.gateway_fn(action, resource, target, delegation_token)

    # -- catalog tools -------------------------------------------------------

    def search_catalog(self, keyword: str | None = None, domain: str | None = None) -> list[dict]:
        """List catalog entities, optionally filtered by keyword/domain."""
        with _action_span(
            "agents.search_catalog",
            {"agent.id": self.agent_id, "catalog.keyword": keyword or "", "catalog.domain": domain or ""},
        ):
            entities = self.catalog_fn()
            kw = (keyword or "").lower()
            out = []
            for ent in entities:
                if domain and ent.get("domain") != domain:
                    continue
                if kw and kw not in json.dumps(ent, default=str).lower():
                    continue
                out.append({
                    "urn": ent["urn"], "name": ent["name"], "domain": ent["domain"],
                    "data_classification": ent.get("data_classification"),
                    "description": ent.get("description", ""),
                })
            return out

    def lineage(self, urn: str) -> dict:
        """Upstream/downstream lineage for an entity from the catalog."""
        with _action_span(
            "agents.lineage",
            {"agent.id": self.agent_id, "gateway.resource": urn},
        ):
            for ent in self.catalog_fn():
                if ent.get("urn") == urn:
                    return {
                        "urn": urn,
                        "upstream": ent.get("upstream", []),
                        "downstream": ent.get("downstream", []),
                    }
            return {"urn": urn, "upstream": [], "downstream": []}

    # -- governance tools (guardian role) --------------------------------------

    def criticality(self) -> list[dict]:
        """Dataset criticality ranking with the component breakdown (guardian)."""
        from app.datahub import criticality as crit
        from app.database import SessionLocal

        with _action_span(
            "agents.criticality",
            {"agent.id": self.agent_id},
        ):
            with SessionLocal() as db:
                report = crit.criticality_report(db)
                return [
                    {
                        "urn": r["urn"], "name": r["name"], "domain": r["domain"],
                        "criticality": r["criticality"], "risk": r["risk"],
                        "critical": r["criticality"] >= crit.CRITICAL_THRESHOLD,
                        "components": r["components"],
                    }
                    for r in report["entities"][:10]
                ]

    def policy_gaps(self) -> list[dict]:
        """Re-scan recorded actions for policy gaps and the gap report (guardian)."""
        from app.datahub.policy_gaps import scan_policy_gaps
        from app.database import SessionLocal

        with _action_span(
            "agents.policy_gaps",
            {"agent.id": self.agent_id},
        ):
            with SessionLocal() as db:
                report = scan_policy_gaps(db)
                return [
                    {
                        "gap_id": g["id"], "agent": g["agent"]["name"],
                        "action_type": g["action_type"],
                        "severity": g["severity"], "reason": g["title"],
                    }
                    for g in report["gaps"]
                ]

    def watchlist_alerts(self) -> list[dict]:
        """Watchlisted datasets whose criticality breached their threshold."""
        from app.datahub import monitor
        from app.database import SessionLocal

        with _action_span(
            "agents.watchlist_alerts",
            {"agent.id": self.agent_id},
        ):
            with SessionLocal() as db:
                return monitor.watchlist_alerts(db)

    # -- governed action tools -------------------------------------------------

    def read(self, urn: str) -> dict:
        return self._gateway("read", urn)

    def query(self, urn: str) -> dict:
        return self._gateway("query", urn)

    def transform(self, urn: str) -> dict:
        return self._gateway("transform", urn)

    def write(self, urn: str) -> dict:
        return self._gateway("write", urn)

    def ingest(self, urn: str) -> dict:
        return self._gateway("ingest", urn)

    def deploy(self, urn: str) -> dict:
        return self._gateway("deploy", urn)

    def call(self, action: str, resource: str) -> dict:
        if action in GATEWAY_TOOLS:
            return self._gateway(action, resource)
        if action in GOVERNANCE_TOOLS:
            method = getattr(self, action)
            return {"decision": "allow", "policy_name": f"governance.{action}",
                    "result": method()}
        raise ValueError(f"unknown governed tool: {action}")

    def tools_available(self) -> list[str]:
        return list(ALL_TOOLS)
