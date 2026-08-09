"""Example 5 — DataHub impact.

The control plane tracks every agent action against DataHub entities (read <
query < transform < write) and contributes the impact back to the DataHub graph
when a DataHub endpoint is configured. Without a live instance, impact is
recorded locally and surfaced in the DataHub → Impact heatmap.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "sdk"))

import httpx  # noqa: E402

from controlplane import ControlPlaneClient, default_base_url  # noqa: E402

BASE_URL = default_base_url()
CRED_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "agents")

ENTITIES = [
    ("urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)", "read"),
    ("urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)", "query"),
    ("urn:li:dataset:(urn:li:dataPlatform:snowflake,sales.opportunities,PROD)", "query"),
    ("urn:li:dataset:(urn:li:dataPlatform:snowflake,sales.opportunities_daily_agg,PROD)", "transform"),
    ("urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customer_360,PROD)", "read"),
]


def main() -> None:
    analyst = ControlPlaneClient.from_credentials(
        os.path.join(CRED_DIR, "marketing-analyst.json"), BASE_URL)

    print("=== Agent impact on the DataHub graph ===\n")
    for urn, action in ENTITIES:
        res = analyst.datahub_act(urn, action, metadata={"purpose": "reporting"})
        print(f"  · {action:<9} {urn.split('dataPlatform:')[1].split(',')[0]:<22} "
              f"impact={res['impact_weight']}")

    status = httpx.get(f"{BASE_URL}/api/datahub/status").json()
    print(f"\nDataHub endpoint: {status['endpoint'] or '(none — local impact only)'}")

    impact = httpx.get(f"{BASE_URL}/api/datahub/impact").json()
    matrix = impact["matrix"].get(analyst.creds.agent_id, {})
    print(f"\nAggregated impact for {analyst.creds.agent_id}:")
    for urn, weight in sorted(matrix.items(), key=lambda kv: -kv[1]):
        print(f"  {weight:>5.1f}  {urn.split('dataPlatform:')[1].split(',')[0]}")


if __name__ == "__main__":
    main()
