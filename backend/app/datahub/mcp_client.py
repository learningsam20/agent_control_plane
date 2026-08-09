"""Optional DataHub MCP server client (Model Context Protocol).

When ``USE_DATAHUB_MCP`` is enabled the catalog/lineage reads are routed through
the official ``@acryldata/mcp-server-datahub`` server (the ``mcp-server-datahub``
PyPI package) instead of raw GraphQL. The server is either spawned over stdio
(default, ``DATAHUB_MCP_COMMAND``) or reached over an SSE endpoint
(``DATAHUB_MCP_URL``).

Writes are intentionally NOT routed here: agent-impact contribution keeps using
DataHub's own MetadataChangeProposal ingest API, which is DataHub's "MCP"
ingest endpoint — a different thing from the Model Context Protocol server.
"""

import asyncio
import json
import os

from ..config import get_settings

settings = get_settings()


class DataHubMCPError(RuntimeError):
    pass


def _text_of(result) -> str:
    """Extract the text payload from an MCP tool result."""
    if hasattr(result, "content"):
        for item in result.content:
            text = getattr(item, "text", None)
            if text:
                return text
    return ""


def _json_of(result) -> dict:
    """Parse an MCP tool result into a dict (structured content or JSON text)."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    text = _text_of(result) or "{}"
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return {"text": text}


class DataHubMCPClient:
    """Thin async wrapper over the ``mcp`` SDK for the DataHub MCP server."""

    def __init__(
        self,
        endpoint: str | None = None,
        token: str | None = None,
        url: str | None = None,
        command: str | None = None,
    ):
        self.endpoint = (endpoint if endpoint is not None else settings.datahub_endpoint).rstrip("/")
        self.token = token if token is not None else settings.datahub_token
        self.url = (url or settings.datahub_mcp_url).rstrip("/")
        self.command = command or settings.datahub_mcp_command

    @property
    def enabled(self) -> bool:
        return bool(settings.use_datahub_mcp) and bool(self.endpoint or self.url)

    def _env(self) -> dict:
        env = dict(os.environ)
        if self.endpoint:
            env["DATAHUB_GMS_URL"] = self.endpoint
            env["DATAHUB_GMS_HOST"] = self.endpoint
            env["DATAHUB_GMS_PORT"] = ""
        if self.token:
            env["DATAHUB_GMS_TOKEN"] = self.token
        return env

    def _connection(self):
        if self.url:
            from mcp.client.sse import sse_client

            return sse_client(self.url)
        from mcp.client.stdio import StdioServerParameters, stdio_client

        parts = self.command.split()
        params = StdioServerParameters(command=parts[0], args=parts[1:], env=self._env())
        return stdio_client(params)

    async def _call(self, tool: str, arguments: dict) -> dict:
        if not self.enabled:
            raise DataHubMCPError("DataHub MCP server is not configured (USE_DATAHUB_MCP)")
        try:
            from mcp import ClientSession

            async with self._connection() as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
                    return _json_of(result)
        except Exception as exc:  # noqa: BLE001  surface as a single error type
            raise DataHubMCPError(f"DataHub MCP tool '{tool}' failed: {exc}") from exc

    def search_datasets(self, query: str = "*", count: int = 500) -> list[dict]:
        """MCP ``search`` tool: datasets only, mapped to the same shape as the
        GraphQL ``search_datasets`` so callers are interchangeable."""
        data = asyncio.run(self._call("search", {
            "query": query,
            "num_results": min(count, 50),
            "filter": "entity_type = dataset",
        }))
        results = data.get("searchResults") or data.get("results") or []
        out = []
        for r in results:
            ent = r.get("entity") or r
            props = ent.get("properties") or {}
            custom = props.get("customProperties") or {}
            owners = ((ent.get("ownership") or {}).get("owners") or [])
            out.append({
                "urn": ent.get("urn"),
                "name": ent.get("name"),
                "platform": (ent.get("platform") or {}).get("name")
                if isinstance(ent.get("platform"), dict) else ent.get("platform"),
                "description": props.get("description") or "",
                "customProperties": custom,
                "owner_team": (owners[0].get("owner") or {}).get("username") if owners else "",
            })
        return out

    def get_lineage(self, urn: str, direction: str = "DOWNSTREAM", depth: int = 2) -> dict:
        """MCP ``get_lineage`` tool, mapped to the same shape as the GraphQL
        ``get_lineage``: ``{urn, direction, relationships: [{urn, type}]}``."""
        upstream = direction.upper() == "UPSTREAM"
        data = asyncio.run(self._call("get_lineage", {
            "urn": urn,
            "upstream": upstream,
            "max_hops": max(1, min(int(depth), 10)),
            "max_results": 100,
        }))
        rels: list[dict] = []
        for key in ("upstreams", "downstreams"):
            chunk = data.get(key) or {}
            for r in chunk.get("searchResults") or chunk.get("results") or []:
                ent = r.get("entity") or r
                rels.append({"urn": ent.get("urn"), "type": key.upper()})
        return {"urn": urn, "direction": direction.upper(), "relationships": rels}


def get_mcp_client() -> DataHubMCPClient:
    return DataHubMCPClient()
