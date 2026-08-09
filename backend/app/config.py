from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Agent Control Plane 2.0"
    api_prefix: str = "/api"

    # Server binding
    host: str = "0.0.0.0"
    port: int = 5186
    self_url: str = "http://localhost:5186"

    database_url: str = "sqlite:///./data/controlplane.db"

    # Used to sign admin API tokens. Override in production.
    secret_key: str = "dev-secret-change-me-in-production"
    token_algorithm: str = "HS256"
    token_expire_minutes: int = 60 * 8

    # Policy engine: "auto" tries OPA first and falls back to the native engine,
    # "native" uses the built-in rule engine only, "opa" requires OPA.
    # Accepts POLICY_ENGINE or CONTROLPLANE_POLICY_ENGINE.
    policy_engine: str = Field(
        default="auto",
        validation_alias=AliasChoices("policy_engine", "controlplane_policy_engine"))
    opa_url: str = Field(
        default="",  # e.g. http://localhost:8181
        validation_alias=AliasChoices("opa_url", "controlplane_opa_url"))
    # The Rego module declares `package controlplane`, so the OPA data path /
    # policy id must match it for /v1/data/<name> queries to resolve.
    opa_policy_name: str = "controlplane"
    # Path to the Rego module pushed at startup. Leave empty to auto-resolve the
    # bundled policies/datahub.rego relative to this repository.
    opa_policy_file: str = ""

    # DataHub. When DATAHUB_ENDPOINT is set the control plane syncs the catalog
    # and writes back agent impact as DataHub metadata; otherwise it uses the
    # bundled reference catalog so the whole stack runs offline.
    datahub_endpoint: str = ""
    datahub_token: str = ""
    datahub_platform_urn: str = "urn:li:dataPlatform:controlplane"

    # DataHub MCP server (Model Context Protocol). When USE_DATAHUB_MCP=true the
    # catalog/lineage reads are routed through the @acryldata/mcp-server-datahub
    # server (``mcp-server-datahub`` on PyPI) instead of raw GraphQL; if the MCP
    # server is unreachable the client transparently falls back to GraphQL.
    # The server is spawned over stdio (DATAHUB_MCP_COMMAND, default `uvx
    # mcp-server-datahub@latest`) or reached over an SSE endpoint
    # (DATAHUB_MCP_URL, e.g. http://localhost:8101/sse). Writes always keep
    # using DataHub's own MetadataChangeProposal ingest API.
    use_datahub_mcp: bool = False
    datahub_mcp_command: str = "uvx mcp-server-datahub@latest"
    datahub_mcp_url: str = ""

    # DataHub analytics agent (Talk-to-Data). When USE_ANALYTICS_AGENT=true the
    # control plane can answer natural-language analytics questions via a running
    # ``datahub-analytics-agent`` service (default http://localhost:8100) instead
    # of its built-in catalog search; set to false to keep current processing.
    use_analytics_agent: bool = False
    analytics_agent_url: str = "http://localhost:8100"
    # Engine name on the analytics agent used for new conversations.
    analytics_agent_engine: str = ""

    # Agent LLM (LiteLLM). Anything LiteLLM supports works — OpenAI-compatible
    # cloud endpoints, Ollama, etc. Leave LLM_MODEL empty to run the rule-based
    # planner (no external dependency). Examples:
    #   LLM_MODEL="openai/gpt-4o-mini"                  LLM_API_KEY=sk-...
    #   LLM_MODEL="ollama/llama3.2"                     LLM_BASE_URL=http://localhost:11434
    #   LLM_MODEL="openai/llama3.2:latest"              LLM_BASE_URL=http://localhost:11434/v1
    #   LLM_MODEL="openai/my-gpt"                       LLM_BASE_URL=http://localhost:8000/v1
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_temperature: float = 0.0

    cors_origins: list[str] = [
        "http://localhost:5185",
        "http://127.0.0.1:5185",
    ]

    # Delegation defaults
    default_max_depth: int = 2
    max_delegation_ttl_hours: int = 24

    # Reputation tuning
    reputation_allow_delta: float = 1.0
    reputation_deny_delta: float = -3.0
    reputation_violation_delta: float = -5.0
    reputation_suspend_threshold: int = 3  # auto-suspend after N violations in 24h

    # Agents worker (agent runtime process)
    worker_poll_interval: float = 5.0
    worker_name: str = "worker-default"


@lru_cache
def get_settings() -> Settings:
    return Settings()
