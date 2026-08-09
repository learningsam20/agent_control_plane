"""Example 1 — Onboard agents with Ed25519 identities.

Registers three agents with distinct domain grants and reputation profiles.
Private keys are written to ``backend/data/agents/`` and never leave the agent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "sdk"))

from controlplane import ControlPlaneClient, default_base_url  # noqa: E402

BASE_URL = default_base_url()
CRED_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "agents")

AGENTS = [
    ("marketing-analyst", ["Marketing", "Sales"], "Drafts campaign reports from DataHub context"),
    ("data-engineer", ["Marketing", "Sales", "Finance", "Engineering"], "Runs transforms and ingests datasets"),
    ("ml-engineer", ["ML", "Engineering"], "Trains and deploys models on feature stores"),
]


def main() -> None:
    cp = ControlPlaneClient(base_url=BASE_URL)
    os.makedirs(CRED_DIR, exist_ok=True)
    for name, domains, desc in AGENTS:
        path = os.path.join(CRED_DIR, f"{name}.json")
        if os.path.exists(path):
            print(f"  · {name:<20} already onboarded ({path})")
            continue
        creds = cp.register(name, domains, desc)
        creds.save(path)
        print(f"  · {name:<20} onboarded  id={creds.agent_id}  tier=standard  domains={domains}")

    print("\nCredentials stored under backend/data/agents/ (mode 0600).")
    print("Agents listed in the console under Agents → catalog.")


if __name__ == "__main__":
    main()
