"""Example 3 — Zero-trust delegation.

A privileged engineering lead delegates a scoped ``transform`` capability for a
specific ML dataset to a standard-tier engineer. The engineer's direct attempt
is denied; under the delegation (which inherits the lead's authority within the
exact scope) it is allowed. Attempting to write — outside the delegated scope —
is denied again, and the engineer cannot re-delegate beyond the depth limit.
"""

import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "sdk"))

from controlplane import AgentCredentials, ControlPlaneClient, default_base_url  # noqa: E402

BASE_URL = default_base_url()
CRED_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "agents")

CHURN_FEATURES = "urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)"


def _signup(name: str, domains: list[str], delta: float = 0.0) -> ControlPlaneClient:
    keys = httpx.post(f"{BASE_URL}/api/agents/keypair").json()
    reg = httpx.post(f"{BASE_URL}/api/agents/register", json={
        "name": name, "description": "delegation demo", "public_key": keys["public_key"],
        "granted_domains": domains,
    }).json()
    if delta:
        httpx.post(f"{BASE_URL}/api/agents/{reg['id']}/reputation/adjust?delta={delta}&reason=demo-elevation")
    creds = AgentCredentials(reg["id"], keys["private_key"], keys["public_key"])
    return ControlPlaneClient(BASE_URL, creds)


def main() -> None:
    engineer = ControlPlaneClient.from_credentials(
        os.path.join(CRED_DIR, "data-engineer.json"), BASE_URL)
    lead = _signup("engineering-lead", ["ML", "Finance", "Engineering"], delta=40)

    print("=== Zero-trust delegation ===\n")

    direct = engineer.act("transform", CHURN_FEATURES)
    print(f"  1. engineer acts directly on ml.churn_features")
    print(f"     → {direct['decision'].upper():<5} {direct['reason']}\n")

    scope = {"actions": ["transform"], "datasets": [CHURN_FEATURES], "domains": []}
    dl = lead.delegate(engineer.creds.agent_id, scope, max_depth=1, ttl_hours=4)
    token = dl["token"]
    print(f"  2. lead delegates {{actions: [transform], datasets: [ml.churn_features]}}  id={dl['id']}\n")

    delegated = engineer.act("transform", CHURN_FEATURES, delegation_token=token)
    print(f"  3. engineer acts under delegation")
    print(f"     → {delegated['decision'].upper():<5} {delegated['reason']} "
          f"(inherits the delegator's authority within scope)\n")

    out_of_scope = engineer.act("write", CHURN_FEATURES, delegation_token=token)
    print(f"  4. engineer attempts write (outside delegated scope)")
    print(f"     → {out_of_scope['decision'].upper():<5} {out_of_scope['reason']}\n")

    sub = _signup("sub-agent", ["ML"])
    resp = httpx.post(f"{BASE_URL}/api/delegations", json={
        "delegator_id": engineer.creds.agent_id, "delegatee_id": sub.creds.agent_id,
        "scope": scope, "max_depth": 1,
    })
    print(f"  5. engineer re-delegates to sub-agent (depth chain already at limit)")
    if resp.status_code == 400:
        print(f"     → BLOCKED {resp.json()['detail']}")
    else:
        print(f"     → {resp.status_code} {resp.text}")


if __name__ == "__main__":
    main()
