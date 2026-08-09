"""Example 6 — Governed LangGraph agent runs.

Gives a natural-language objective to a real LangGraph agent (planner →
governed executor → summarizer). Every tool call is a signed gateway request:
the control plane decides allow/deny, audits, and feeds reputation. Same agent,
same tooling, but governance decides what actually happens.

Demo of the guardrails: the marketing analyst can read public campaign data, but
a read of restricted finance revenue is denied at the gateway.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "sdk"))

import httpx  # noqa: E402

from controlplane import default_base_url  # noqa: E402

BASE_URL = default_base_url()

ANALYST = "ag_analyst"


def run_agent(agent_id: str, objective: str) -> dict:
    resp = httpx.post(
        f"{BASE_URL}/api/agents/{agent_id}/run",
        json={"agent_id": agent_id, "objective": objective, "sync": True},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def show(label: str, run: dict) -> None:
    print(f"\n### {label}\n")
    print(f"  objective: {run['objective']}")
    print(f"  status:    {run['status']}   (run {run['id']})")
    plan_desc = [f"{p['action']} {p['resource'].split(',')[1]}" for p in run["plan"]]
    print(f"  plan:      {plan_desc}")
    for r in run["results"]:
        status = {"allow": "allowed", "deny": "DENIED", "failed": "FAILED"}[r["decision"]]
        print(f"    · {r['action']:<9} {r['resource'].split(',')[1]:<30} → {status:<7} "
              f"[{r['reason']}]")
    print(f"  summary:\n{run['summary']}")


def main() -> None:
    print("=== Governed LangGraph agent runs ===\n")

    # Reset demo reputation so repeated runs stay reproducible.
    httpx.post(f"{BASE_URL}/api/demo/reset", timeout=10)

    run = run_agent(ANALYST, "Read the restricted finance revenue ledger")
    show("Governance denies what the agent is not allowed to touch", run)

    run = run_agent(ANALYST, "Read the marketing campaign attribution data and report on it")
    show("In-scope objective completes", run)

    audit = httpx.get(f"{BASE_URL}/api/audit?event_type=agent.run.succeeded&limit=3", timeout=10)
    print("\nEvery run is in the tamper-evident audit chain:")
    for evt in audit.json():
        print(f"  seq {evt['seq']}  {evt['event_type']}  actor={evt['actor_id']}  "
              f"subject={evt['subject']}")


if __name__ == "__main__":
    main()
