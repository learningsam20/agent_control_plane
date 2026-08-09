"""DataHub client: GraphQL/MCP reads plus MetadataChangeProposal writes.

The control plane reads the DataHub context graph (datasets, lineage, ML
models) and contributes back by ingesting agent-impact metadata so other
agents and humans inherit the knowledge — satisfying the hackathon requirement
to do more than read metadata.

Reads use GraphQL by default; when ``USE_DATAHUB_MCP`` is set they are routed
through the ``@acryldata/mcp-server-datahub`` MCP server and fall back to
GraphQL if that server is unreachable. Writes always use DataHub's own
MetadataChangeProposal ("MCP") ingest API.
"""

import json

import httpx

from ..config import get_settings

settings = get_settings()


class DataHubError(RuntimeError):
    pass


class DataHubClient:
    def __init__(self, endpoint: str | None = None, token: str | None = None):
        self.endpoint = (endpoint or settings.datahub_endpoint).rstrip("/")
        self.token = token or settings.datahub_token

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        if not self.enabled:
            raise DataHubError("DataHub endpoint is not configured")
        try:
            resp = httpx.post(
                f"{self.endpoint}/api/graphql",
                json={"query": query, "variables": variables or {}},
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as exc:
            raise DataHubError(f"DataHub GraphQL request failed: {exc}") from exc
        if body.get("errors"):
            raise DataHubError(f"DataHub GraphQL errors: {body['errors']}")
        return body.get("data", {})

    def search_datasets(self, query: str = "*", count: int = 500) -> list[dict]:
        # When USE_DATAHUB_MCP is on, prefer the MCP server; fall back to GraphQL.
        if settings.use_datahub_mcp:
            try:
                from .mcp_client import DataHubMCPClient

                return DataHubMCPClient(endpoint=self.endpoint, token=self.token).search_datasets(query, count)
            except Exception as exc:  # noqa: BLE001  MCP is best-effort
                print(f"[datahub] MCP search unavailable, falling back to GraphQL: {exc}")
        gql = """
        query Search($query: String!, $count: Int!) {
          search(input: {type: DATASET, query: $query, start: 0, count: $count}) {
            total
            searchResults {
              entity {
                urn
                ... on Dataset {
                  name
                  platform { name }
                  properties {
                    description
                    customProperties {
                      key
                      value
                    }
                  }
                  ownership { owners { owner { ... on CorpUser { urn username } } } }
                }
              }
            }
          }
        }
        """
        data = self.graphql(gql, {"query": query, "count": count})
        results = (data.get("search") or {}).get("searchResults") or []
        out = []
        for r in results:
            ent = r.get("entity") or {}
            props = (ent.get("properties") or {})
            custom_props = props.get("customProperties") or []
            owners = ((ent.get("ownership") or {}).get("owners") or [])
            out.append({
                "urn": ent.get("urn"),
                "name": ent.get("name"),
                "platform": (ent.get("platform") or {}).get("name"),
                "description": (props.get("description") or ""),
                "customProperties": {
                    item.get("key", ""): item.get("value", "")
                    for item in custom_props if item.get("key")
                },
                "owner_team": (owners[0].get("owner") or {}).get("username") if owners else "",
            })
        return out

    def get_lineage(self, urn: str, direction: str = "DOWNSTREAM", depth: int = 2) -> dict:
        # When USE_DATAHUB_MCP is on, prefer the MCP server; fall back to GraphQL.
        if settings.use_datahub_mcp:
            try:
                from .mcp_client import DataHubMCPClient

                return DataHubMCPClient(endpoint=self.endpoint, token=self.token).get_lineage(urn, direction, depth)
            except Exception as exc:  # noqa: BLE001  MCP is best-effort
                print(f"[datahub] MCP lineage unavailable, falling back to GraphQL: {exc}")
        gql = """
        query Lineage($urn: String!, $direction: LineageDirection!, $depth: Int!) {
          lineage(input: {urn: $urn, direction: $direction, start: 0, count: 100, orFilters: []}) {
            entities(direction: $direction, start: 0, count: 100, query: "") {
              total
              relationships {
                entity { urn type }
                type
              }
            }
          }
        }
        """
        data = self.graphql(gql, {"urn": urn, "direction": direction, "depth": depth})
        lineage = data.get("lineage") or {}
        entities = (lineage.get("entities") or {})
        rels = entities.get("relationships") or []
        return {
            "urn": urn,
            "direction": direction,
            "relationships": [
                {"urn": r.get("entity", {}).get("urn"), "type": r.get("type")}
                for r in rels
            ],
        }

    def ingest_agent_impact(self, urn: str, aspect: dict) -> bool:
        """Contribute back to the DataHub graph.

        Writes the impact into the entity's ``datasetProperties`` aspect under a
        ``controlPlaneAgentImpact`` custom property. Custom aspects are not in the
        stock quickstart entity registry, so we use the registered dataset aspect
        and read-modify-write to preserve existing properties/description.
        """
        if not self.enabled:
            return False
        try:
            existing = self._dataset_properties(urn)
            if existing is None:
                return False
            custom = {
                item.get("key", ""): item.get("value", "")
                for item in (existing.get("customProperties") or []) if item.get("key")
            }
            custom["controlPlaneAgentImpact"] = json.dumps(aspect)
            body: dict = {"customProperties": custom}
            if existing.get("description"):
                body["description"] = existing["description"]

            proposal = {
                "entityUrn": urn,
                "entityType": "dataset",
                "aspectName": "datasetProperties",
                "changeType": "UPSERT",
                "aspect": {"value": json.dumps(body), "contentType": "application/json"},
            }
            resp = httpx.post(
                f"{self.endpoint}/aspects?action=ingestProposal",
                json={"proposal": proposal, "async": "false"},
                headers=self._headers(),
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:  # noqa: BLE001  contribution is best-effort
            return False

    def _dataset_properties(self, urn: str) -> dict | None:
        """Return the dataset's properties (description, customProperties) or None
        when the URN is not a dataset."""
        if not self.enabled:
            return None
        if not urn.startswith("urn:li:dataset:"):
            return None
        gql = """
        query DatasetProperties($urn: String!) {
          dataset(urn: $urn) {
            properties {
              description
              customProperties { key value }
            }
          }
        }
        """
        data = self.graphql(gql, {"urn": urn})
        return (data.get("dataset") or {}).get("properties") or {}


def get_client() -> DataHubClient:
    return DataHubClient()
