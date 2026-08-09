"""Reference data catalog.

When a live DataHub instance is configured the catalog is synced from its
GraphQL API (see ``sync_from_datahub``). For offline evaluation a bundled
reference catalog models a realistic analytics stack — raw event streams,
marketing/sales/finance datasets, and an end-to-end ML lineage from training
features to a deployed churn model — so every feature is demonstrable without
standing up DataHub.
"""

import json

from sqlalchemy.orm import Session

from .. import models

REFERENCE_ENTITIES: list[dict] = [
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:kafka,events.raw_clickstream,PROD)",
        "name": "events.raw_clickstream",
        "type": "dataset", "platform": "kafka", "domain": "Engineering",
        "data_classification": "sensitive", "owner_team": "Platform",
        "description": "Raw product clickstream events ingested from the mobile and web clients.",
        "schema": [{"name": "event_id", "type": "string"}, {"name": "user_id", "type": "long"},
                   {"name": "ts", "type": "timestamp"}, {"name": "page", "type": "string"},
                   {"name": "referrer", "type": "string"}],
        "upstream": [], "downstream": ["urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)"],
        "usage": {"queryCount": 4821, "uniqueUsers": 38, "p99LatencyMs": 620},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:airbyte,raw.churn_survey,PROD)",
        "name": "raw.churn_survey",
        "type": "dataset", "platform": "airbyte", "domain": "ML",
        "data_classification": "sensitive", "owner_team": "Data Science",
        "description": "Structured responses from the quarterly churn-risk survey.",
        "schema": [{"name": "respondent_id", "type": "string"}, {"name": "nps", "type": "int"},
                   {"name": "usage_frequency", "type": "string"}, {"name": "sentiment", "type": "string"}],
        "upstream": [], "downstream": ["urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)"],
        "usage": {"queryCount": 912, "uniqueUsers": 12, "p99LatencyMs": 140},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)",
        "name": "ml.churn_features",
        "type": "dataset", "platform": "bigquery", "domain": "ML",
        "data_classification": "sensitive", "owner_team": "Data Science",
        "description": "Feature store table joining clickstream and survey signals for churn modeling.",
        "schema": [{"name": "account_id", "type": "string"}, {"name": "nps", "type": "int"},
                   {"name": "days_since_last_login", "type": "int"},
                   {"name": "p99_latency_30d", "type": "float"}, {"name": "feature_ts", "type": "timestamp"}],
        "upstream": [
            "urn:li:dataset:(urn:li:dataPlatform:kafka,events.raw_clickstream,PROD)",
            "urn:li:dataset:(urn:li:dataPlatform:airbyte,raw.churn_survey,PROD)",
        ],
        "downstream": ["urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"],
        "usage": {"queryCount": 3104, "uniqueUsers": 22, "p99LatencyMs": 980},
    },
    {
        "urn": "urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)",
        "name": "churn_model",
        "type": "mlModel", "platform": "mlflow", "domain": "ML",
        "data_classification": "sensitive", "owner_team": "Data Science",
        "description": "Gradient-boosted churn prediction model trained on ml.churn_features.",
        "schema": [],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_features,PROD)"],
        "downstream": ["urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_predictions,PROD)"],
        "usage": {"queryCount": 1290, "uniqueUsers": 9, "p99LatencyMs": 40},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_predictions,PROD)",
        "name": "ml.churn_predictions",
        "type": "dataset", "platform": "bigquery", "domain": "ML",
        "data_classification": "sensitive", "owner_team": "Data Science",
        "description": "Scored predictions from churn_model refreshed nightly and served to product surfaces.",
        "schema": [{"name": "account_id", "type": "string"}, {"name": "churn_probability", "type": "float"},
                   {"name": "risk_band", "type": "string"}, {"name": "prediction_date", "type": "date"}],
        "upstream": ["urn:li:mlModel:(urn:li:dataPlatform:mlflow,churn_model,PROD)"],
        "downstream": [],
        "usage": {"queryCount": 6402, "uniqueUsers": 45, "p99LatencyMs": 310},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)",
        "name": "marketing.campaign_events",
        "type": "dataset", "platform": "snowflake", "domain": "Marketing",
        "data_classification": "public", "owner_team": "Growth",
        "description": "Marketing campaign delivery and interaction events.",
        "schema": [{"name": "campaign_id", "type": "string"}, {"name": "channel", "type": "string"},
                   {"name": "event_type", "type": "string"}, {"name": "event_ts", "type": "timestamp"}],
        "upstream": [], "downstream": [
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)"
        ],
        "usage": {"queryCount": 2210, "uniqueUsers": 18, "p99LatencyMs": 210},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)",
        "name": "marketing.campaign_attribution",
        "type": "dataset", "platform": "snowflake", "domain": "Marketing",
        "data_classification": "public", "owner_team": "Growth",
        "description": "Attributed campaign ROI by channel, refreshed hourly.",
        "schema": [{"name": "campaign_id", "type": "string"}, {"name": "channel", "type": "string"},
                   {"name": "spend", "type": "float"}, {"name": "revenue_attributed", "type": "float"},
                   {"name": "attribution_date", "type": "date"}],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_events,PROD)"],
        "downstream": ["urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customer_360,PROD)"],
        "usage": {"queryCount": 1187, "uniqueUsers": 14, "p99LatencyMs": 190},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,sales.opportunities,PROD)",
        "name": "sales.opportunities",
        "type": "dataset", "platform": "snowflake", "domain": "Sales",
        "data_classification": "sensitive", "owner_team": "Sales Ops",
        "description": "Live CRM opportunities with account, stage, and forecasted value.",
        "schema": [{"name": "opportunity_id", "type": "string"}, {"name": "account_id", "type": "string"},
                   {"name": "stage", "type": "string"}, {"name": "amount", "type": "float"},
                   {"name": "close_date", "type": "date"}],
        "upstream": [], "downstream": [
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,sales.opportunities_daily_agg,PROD)",
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customer_360,PROD)",
        ],
        "usage": {"queryCount": 5310, "uniqueUsers": 61, "p99LatencyMs": 340},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,sales.opportunities_daily_agg,PROD)",
        "name": "sales.opportunities_daily_agg",
        "type": "dataset", "platform": "snowflake", "domain": "Sales",
        "data_classification": "sensitive", "owner_team": "Sales Ops",
        "description": "Daily aggregate of pipeline by stage and territory.",
        "schema": [{"name": "agg_date", "type": "date"}, {"name": "territory", "type": "string"},
                   {"name": "stage", "type": "string"}, {"name": "pipeline_value", "type": "float"}],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:snowflake,sales.opportunities,PROD)"],
        "downstream": [],
        "usage": {"queryCount": 890, "uniqueUsers": 12, "p99LatencyMs": 150},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue,PROD)",
        "name": "finance.revenue",
        "type": "dataset", "platform": "bigquery", "domain": "Finance",
        "data_classification": "restricted", "owner_team": "Finance",
        "description": "Restricted revenue ledger. Access requires privileged reputation tier.",
        "schema": [{"name": "invoice_id", "type": "string"}, {"name": "account_id", "type": "string"},
                   {"name": "amount", "type": "float"}, {"name": "recognized_date", "type": "date"}],
        "upstream": [], "downstream": [
            "urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue_forecast,PROD)",
            "urn:li:dataJob:(urn:li:dataFlow:(airflow,revenue_etl,PROD),dbt_revenue_agg)",
        ],
        "usage": {"queryCount": 1240, "uniqueUsers": 8, "p99LatencyMs": 240},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue_forecast,PROD)",
        "name": "finance.revenue_forecast",
        "type": "dataset", "platform": "bigquery", "domain": "Finance",
        "data_classification": "restricted", "owner_team": "Finance",
        "description": "Forecast model output combining recognized and deferred revenue.",
        "schema": [{"name": "forecast_date", "type": "date"}, {"name": "period", "type": "string"},
                   {"name": "forecast_amount", "type": "float"}, {"name": "confidence", "type": "float"}],
        "upstream": [
            "urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue,PROD)",
            "urn:li:dataJob:(urn:li:dataFlow:(airflow,revenue_etl,PROD),dbt_revenue_agg)",
        ],
        "downstream": [],
        "usage": {"queryCount": 733, "uniqueUsers": 6, "p99LatencyMs": 180},
    },
    {
        "urn": "urn:li:dataJob:(urn:li:dataFlow:(airflow,revenue_etl,PROD),dbt_revenue_agg)",
        "name": "revenue_etl.dbt_revenue_agg",
        "type": "job", "platform": "airflow", "domain": "Finance",
        "data_classification": "restricted", "owner_team": "Data Eng",
        "description": "dbt aggregation job materializing the daily revenue rollup.",
        "schema": [],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue,PROD)"],
        "downstream": ["urn:li:dataset:(urn:li:dataPlatform:bigquery,finance.revenue_forecast,PROD)"],
        "usage": {"queryCount": 365, "uniqueUsers": 3, "p99LatencyMs": 45000},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.customer_360,PROD)",
        "name": "analytics.customer_360",
        "type": "dataset", "platform": "snowflake", "domain": "Sales",
        "data_classification": "sensitive", "owner_team": "Data Eng",
        "description": "Customer 360 golden record joining sales pipeline with marketing attribution.",
        "schema": [{"name": "account_id", "type": "string"}, {"name": "lifetime_value", "type": "float"},
                   {"name": "pipeline_value", "type": "float"}, {"name": "attributed_roi", "type": "float"},
                   {"name": "updated_at", "type": "timestamp"}],
        "upstream": [
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,sales.opportunities,PROD)",
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing.campaign_attribution,PROD)",
        ],
        "downstream": [],
        "usage": {"queryCount": 4102, "uniqueUsers": 47, "p99LatencyMs": 520},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.raw_patients,PROD)",
        "name": "raw_patients",
        "type": "dataset", "platform": "sqlite", "domain": "Healthcare",
        "data_classification": "sensitive", "owner_team": "Clinical",
        "description": "Raw synthetic patient records with PII (name, age, billing) and planted quality issues (negative billing, invalid ages, NULL names).",
        "schema": [{"name": "name", "type": "string"}, {"name": "age", "type": "string"},
                   {"name": "medical_condition", "type": "string"}, {"name": "billing_amount", "type": "string"},
                   {"name": "date_of_admission", "type": "string"}, {"name": "insurance_provider", "type": "string"}],
        "upstream": [], "downstream": [
            "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.staging_patients,PROD)",
            "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.v_staging_from_raw,PROD)",
        ],
        "usage": {"queryCount": 55500, "uniqueUsers": 3, "p99LatencyMs": 840},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.v_staging_from_raw,PROD)",
        "name": "v_staging_from_raw",
        "type": "dataset", "platform": "sqlite", "domain": "Healthcare",
        "data_classification": "sensitive", "owner_team": "Clinical",
        "description": "View materializing the raw→staging transformation (clean casing, pipeline status flags).",
        "schema": [{"name": "name", "type": "string"}, {"name": "billing_amount", "type": "string"},
                   {"name": "gender_clean", "type": "string"}, {"name": "pipeline_status", "type": "string"}],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.raw_patients,PROD)"],
        "downstream": [],
        "usage": {"queryCount": 1200, "uniqueUsers": 4, "p99LatencyMs": 510},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.staging_patients,PROD)",
        "name": "staging_patients",
        "type": "dataset", "platform": "sqlite", "domain": "Healthcare",
        "data_classification": "sensitive", "owner_team": "Data Eng",
        "description": "Cleaned patient staging table. Billing rows with quality issues are flagged but not yet dropped.",
        "schema": [{"name": "name", "type": "string"}, {"name": "billing_amount", "type": "string"},
                   {"name": "gender_clean", "type": "string"}, {"name": "condition_clean", "type": "string"},
                   {"name": "pipeline_status", "type": "string"}],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.raw_patients,PROD)"],
        "downstream": [
            "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_billing,PROD)",
            "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_demographics,PROD)",
        ],
        "usage": {"queryCount": 21400, "uniqueUsers": 6, "p99LatencyMs": 620},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_billing,PROD)",
        "name": "mart_billing",
        "type": "dataset", "platform": "sqlite", "domain": "Healthcare",
        "data_classification": "restricted", "owner_team": "Finance",
        "description": "Restricted billing mart. Negative/flagged billing rows propagate here from staging; access requires privileged reputation tier.",
        "schema": [{"name": "name", "type": "string"}, {"name": "billing_amount", "type": "real"},
                   {"name": "length_of_stay_days", "type": "string"}, {"name": "pipeline_status", "type": "string"}],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.staging_patients,PROD)"],
        "downstream": [],
        "usage": {"queryCount": 890, "uniqueUsers": 5, "p99LatencyMs": 480},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.v_billing_from_staging,PROD)",
        "name": "v_billing_from_staging",
        "type": "dataset", "platform": "sqlite", "domain": "Healthcare",
        "data_classification": "restricted", "owner_team": "Finance",
        "description": "View exposing the billing mart projection for analytics consumers.",
        "schema": [{"name": "name", "type": "string"}, {"name": "billing_amount", "type": "real"},
                   {"name": "pipeline_status", "type": "string"}],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.staging_patients,PROD)"],
        "downstream": [],
        "usage": {"queryCount": 440, "uniqueUsers": 3, "p99LatencyMs": 380},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_demographics,PROD)",
        "name": "mart_demographics",
        "type": "dataset", "platform": "sqlite", "domain": "Healthcare",
        "data_classification": "public", "owner_team": "Clinical",
        "description": "Aggregated patient demographics (age, gender, condition) with PII removed. Safe for broad read access.",
        "schema": [{"name": "age", "type": "int"}, {"name": "gender", "type": "string"},
                   {"name": "medical_condition", "type": "string"}, {"name": "hospital", "type": "string"}],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.staging_patients,PROD)"],
        "downstream": [],
        "usage": {"queryCount": 6600, "uniqueUsers": 18, "p99LatencyMs": 300},
    },
    {
        "urn": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.v_demographics_from_staging,PROD)",
        "name": "v_demographics_from_staging",
        "type": "dataset", "platform": "sqlite", "domain": "Healthcare",
        "data_classification": "public", "owner_team": "Clinical",
        "description": "View projecting the demographics mart for reporting.",
        "schema": [{"name": "age", "type": "int"}, {"name": "gender", "type": "string"},
                   {"name": "medical_condition", "type": "string"}],
        "upstream": ["urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.staging_patients,PROD)"],
        "downstream": [],
        "usage": {"queryCount": 920, "uniqueUsers": 7, "p99LatencyMs": 240},
    },
]


REFERENCE_URNS = {ent["urn"] for ent in REFERENCE_ENTITIES}


def seed_reference_catalog(db: Session) -> int:
    """Upsert the reference catalog so lineage/classification are always present.

    A prior live-DataHub sync may have created reference URNs without lineage
    (or overwritten their metadata), so we refresh every reference entity on
    startup instead of only inserting missing ones.
    """
    count = 0
    for ent in REFERENCE_ENTITIES:
        exists = db.get(models.DataHubEntity, ent["urn"])
        if exists is None:
            db.add(
                models.DataHubEntity(
                    urn=ent["urn"],
                    name=ent["name"],
                    type=ent["type"],
                    platform=ent["platform"],
                    domain=ent["domain"],
                    data_classification=ent["data_classification"],
                    owner_team=ent["owner_team"],
                    description=ent["description"],
                    schema_json=json.dumps(ent["schema"]),
                    upstream_json=json.dumps(ent["upstream"]),
                    downstream_json=json.dumps(ent["downstream"]),
                    usage_json=json.dumps(ent["usage"]),
                    source="demo",
                )
            )
        else:
            exists.name = ent["name"]
            exists.type = ent["type"]
            exists.platform = ent["platform"]
            exists.domain = ent["domain"]
            exists.data_classification = ent["data_classification"]
            exists.owner_team = ent["owner_team"]
            exists.description = ent["description"]
            exists.schema_json = json.dumps(ent["schema"])
            exists.upstream_json = json.dumps(ent["upstream"])
            exists.downstream_json = json.dumps(ent["downstream"])
            exists.usage_json = json.dumps(ent["usage"])
            exists.source = "demo"
        count += 1
    db.flush()
    return count


def sync_from_datahub(db: Session) -> int:
    """Sync the catalog from a live DataHub instance (GraphQL)."""
    from .client import DataHubClient, DataHubError

    client = DataHubClient()
    if not client.enabled:
        raise DataHubError("DataHub endpoint is not configured; catalog stays on the reference data")

    count = 0
    for ent in client.search_datasets():
        urn = ent.get("urn")
        if not urn:
            continue
        existing = db.get(models.DataHubEntity, urn)
        props = ent.get("customProperties") or {}
        if existing:
            existing.name = ent.get("name") or existing.name
            existing.platform = ent.get("platform") or existing.platform
            existing.description = ent.get("description") or existing.description
            existing.owner_team = ent.get("owner_team") or existing.owner_team
            existing.source = "datahub"
            if props.get("dataClassification"):
                existing.data_classification = props["dataClassification"]
            if props.get("domain"):
                existing.domain = props["domain"]
        else:
            db.add(
                models.DataHubEntity(
                    urn=urn,
                    name=ent.get("name") or urn,
                    type="dataset",
                    platform=ent.get("platform") or "",
                    domain=props.get("domain") or "General",
                    data_classification=props.get("dataClassification") or "public",
                    owner_team=ent.get("owner_team") or "",
                    description=ent.get("description") or "",
                    schema_json="[]",
                    upstream_json="[]",
                    downstream_json="[]",
                    usage_json="{}",
                    source="datahub",
                )
            )
        count += 1
    db.flush()
    return count
