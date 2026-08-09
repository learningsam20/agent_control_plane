"""Registry of governed LangGraph agents.

Each governed agent maps to a registered control-plane principal and carries a
role prompt plus the set of tools it is allowed to attempt. Credentials for the
seeded demo agents are stored on disk (``data/demo_agents/``) so the agent
runtime (worker) can sign genuine gateway requests — the control plane only
ever stores public keys.
"""

from __future__ import annotations

import json
import os

from sdk.controlplane import AgentCredentials

KEY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "demo_agents"
)

# Roles drive the rule-based planner when no LLM is configured.
ROLES = ("analyst", "engineer", "ml_engineer", "guardian")

GOVERNED_AGENTS: list[dict] = [
    {
        "id": "ag_analyst",
        "name": "kay-analyst",
        "role": "analyst",
        "domains": ["Healthcare"],
        "tools": ["read", "query", "search_catalog", "lineage"],
        "prompt": (
            "You are kay-analyst, a healthcare analytics analyst agent. You read "
            "governed patient demographics and billing datasets from the catalog to "
            "draft reports. You may read and query public and sensitive data, but never "
            "transform, write, or access restricted billing data."
        ),
    },
    {
        "id": "ag_engineer",
        "name": "priya-data-engineer",
        "role": "engineer",
        "domains": ["Healthcare", "Finance", "Engineering", "ML"],
        "tools": ["read", "query", "transform", "write", "ingest", "search_catalog", "lineage"],
        "prompt": (
            "You are priya-data-engineer, a senior data engineer agent. You run "
            "transforms and ingest refined datasets back to the catalog. You may "
            "read, query, transform, write, and ingest public/sensitive data."
        ),
    },
    {
        "id": "ag_ml_engineer",
        "name": "leo-ml-engineer",
        "role": "ml_engineer",
        "domains": ["ML", "Engineering", "Healthcare"],
        "tools": ["read", "query", "transform", "write", "deploy", "search_catalog", "lineage"],
        "prompt": (
            "You are leo-ml-engineer, an ML engineer agent. You train models on "
            "patient feature stores, refresh predictions, and deploy models. You may "
            "read and query ML data and deploy models."
        ),
    },
    {
        "id": "ag_monitor",
        "name": "mona-guardian",
        "role": "guardian",
        "domains": [],
        "tools": ["criticality", "policy_gaps", "watchlist_alerts"],
        "prompt": (
            "You are mona-guardian, the control-plane guardian agent. You run "
            "monitor scans: evaluate dataset criticality, re-scan recorded actions "
            "for policy gaps, and check the watchlist for breached thresholds. "
            "You report posture findings but never mutate policies yourself."
        ),
    },
]


def get_agent_spec(agent_id: str) -> dict:
    for spec in GOVERNED_AGENTS:
        if spec["id"] == agent_id:
            return spec
    raise KeyError(f"no governed agent spec for {agent_id}")


def _key_path(agent_id: str) -> str:
    return os.path.join(KEY_DIR, f"{agent_id}.pem")


def load_demo_credentials(agent_id: str) -> AgentCredentials:
    """Load an agent's private key from the demo key store.

    Raises FileNotFoundError when the key is missing (re-seed the DB).
    """
    with open(_key_path(agent_id)) as fh:
        private_pem = fh.read()
    return AgentCredentials(agent_id, private_pem, public_key_pem="")
