# Sample outputs from the governed agents

These are representative artifacts the control-plane agents produce. They are
static samples so judges can inspect the quality without booting the stack; the
live agents produce the same shape of output after their governed plan has been
executed through the gateway.

Every artifact carries a header recording which governed agent produced it, the
actions it took, and the policy that allowed each step. Nothing here was created
outside a governed plan.

| Artifact                                   | Agent        | Governed actions |
| ------------------------------------------ | ------------ | ---------------- |
| `dbt/churn_features.sql`                   | data-engineer | `transform`, `write` |
| `queries/marketing_roi.sql`                | analyst       | `query` (allow-read-sensitive) |
| `reports/marketing_kpi_summary.md`         | analyst       | `query` |
| `model/churn_model_deployment_card.md`     | ml-engineer   | `deploy` (allow-deploy-ml) |

The entity names and schemas match the reference catalog in
`backend/app/datahub/catalog.py` (and the DataHub graph when
`DATAHUB_ENDPOINT` is configured). Try the live version:

```bash
cd backend && python3 -m agents.worker   # in another terminal
curl -X POST http://localhost:5186/api/agents/ag_ml_engineer/run \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"ag_ml_engineer","objective":"deploy the churn model to production"}'
```
