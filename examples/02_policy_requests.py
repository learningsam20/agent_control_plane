"""Example 2 — Policy enforcement: allow and deny decisions.

Shows the zero-trust gateway in action: a marketing analyst can read public
campaign data but is denied access to restricted finance data (domain + data
classification), and cannot run transforms (reputation tier).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "sdk"))

from controlplane import ControlPlaneClient, default_base_url  # noqa: E402

BASE_URL = default_base_url()
CRED_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "agents")

CAMPAIGN = "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)"
OPPORTUNITIES = "urn:li:dataset:(urn:li:dataPlatform:snowflake,sales.opportunities,PROD)"
REVENUE = "urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue,PROD)"
CHURN_FEATURES = "urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)"


def show(agent: str, action: str, resource: str, result: dict) -> None:
    status = "ALLOW" if result["decision"] == "allow" else "DENY"
    print(f"  [{status:>5}] {agent:<18} {action:<9} {resource.split('dataPlatform:')[1].split(',')[0]:<10} → {result['reason']}")


def main() -> None:
    analyst = ControlPlaneClient.from_credentials(os.path.join(CRED_DIR, "marketing-analyst.json"), BASE_URL)
    ml = ControlPlaneClient.from_credentials(os.path.join(CRED_DIR, "ml-engineer.json"), BASE_URL)

    print("=== Zero-trust policy decisions ===\n")
    show("marketing-analyst", "read", CAMPAIGN,
         analyst.act("read", CAMPAIGN))
    show("marketing-analyst", "read", OPPORTUNITIES,
         analyst.act("read", OPPORTUNITIES))
    show("marketing-analyst", "read", REVENUE,
         analyst.act("read", REVENUE))
    show("marketing-analyst", "transform", CAMPAIGN,
         analyst.act("transform", CAMPAIGN))
    show("ml-engineer", "transform", CHURN_FEATURES,
         ml.act("transform", CHURN_FEATURES))

    print("\nEach decision was appended to the tamper-evident audit chain and fed")
    print("back into the acting agent's reputation.")

    allowed = analyst.act("read", CAMPAIGN)
    if allowed.get("result"):
        print("\nSample context returned to the allowed read:")
        print(json.dumps({
            "name": allowed["result"]["entity"]["name"],
            "domain": allowed["result"]["entity"]["domain"],
            "classification": allowed["result"]["entity"]["data_classification"],
            "columns": [c["name"] for c in allowed["result"]["entity"]["schema"]][:5],
        }, indent=2))


if __name__ == "__main__":
    main()
