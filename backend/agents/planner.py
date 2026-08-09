"""Plan builder for governed agents.

Turns a natural-language objective into a concrete plan of governed actions
``[{action, resource}, ...]``. When ``LLM_MODEL`` is configured the plan is
drafted with LiteLLM (any model LiteLLM supports); otherwise a deterministic
rule-based planner resolves the objective against the catalog. Governance never
happens at plan time — the gateway decides allow/deny per action.
"""

from __future__ import annotations

import json
import re

from app.config import get_settings
from app.telemetry import tracer as _tracer

from .tools import GATEWAY_TOOLS

settings = get_settings()

# keyword -> action type
_ACTION_KEYWORDS: dict[str, list[str]] = {
    "write": ["write", "ingest", "load", "refresh", "publish", "store", "persist", "create", "insert", "upsert", "save"],
    "ingest": ["ingest", "import", "sync", "pull"],
    "deploy": ["deploy", "ship", "release", "serve", "rollout"],
    "transform": ["transform", "clean", "aggregate", "join", "feature", "enrich", "process", "preprocess", "build"],
    "query": ["look", "inspect", "query", "summar", "report", "check", "review", "explore",
              "analyze", "analyse", "compute", "calculate", "count", "read"],
}

# Per-role default target when nothing in the objective matches the catalog.
_ROLE_DEFAULT = {
    "analyst": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.mart_demographics,PROD)",
    "engineer": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.raw_patients,PROD)",
    "ml_engineer": "urn:li:dataset:(urn:li:dataPlatform:sqlite,healthcare.main.staging_patients,PROD)",
}


_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "on", "for", "with", "at", "by",
    "in", "it", "its", "this", "that", "data", "read", "query", "write", "report",
    "use", "using", "give", "me", "please", "current", "now", "up", "into",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOPWORDS}


def _action_type(objective: str, role: str = "") -> str:
    words = _tokens(objective)
    lower = objective.lower()
    # Strong mutating verbs take precedence (write/ingest/deploy).
    for action in ("write", "ingest", "deploy"):
        if any(kw in words or kw in lower for kw in _ACTION_KEYWORDS[action]):
            return action
    # Explicit data-engineering verbs are a transform. Engineers also mean a
    # transform by "compute/build/aggregate"; analysts mean a read/report.
    if any(kw in words or kw in lower for kw in _ACTION_KEYWORDS["transform"]):
        if role in ("engineer", "ml_engineer") or not any(
                kw in words for kw in _ACTION_KEYWORDS["query"]):
            return "transform"
    return "query"


def _match_entity(objective: str, entities: list[dict], domains: list[str]) -> str | None:
    """Pick the catalog entity the objective is most about, preferring the
    agent's granted domains."""
    words = _tokens(objective)
    best, best_score = None, 0
    for ent in entities:
        hay = _tokens(f"{ent['name']} {ent.get('description', '')} {ent.get('domain', '')}")
        overlap = len(words & hay)
        if ent.get("domain") in domains:
            overlap += 1
        if overlap > best_score:
            best, best_score = ent["urn"], overlap
    return best if best_score >= 1 else None


def rule_based_plan(agent_id: str, role: str, objective: str, entities: list[dict]) -> list[dict]:
    if role == "guardian":
        return [
            {"action": "criticality", "resource": "control-plane"},
            {"action": "policy_gaps", "resource": "control-plane"},
            {"action": "watchlist_alerts", "resource": "control-plane"},
        ]
    action = _action_type(objective, role)
    domains = _spec_domains(agent_id, role)
    urn = _match_entity(objective, entities, domains) or _ROLE_DEFAULT.get(role)

    plan = [{"action": action, "resource": urn}]
    # A data engineer asked to produce a dataset naturally writes the output.
    if role == "engineer" and action == "transform" and "prediction" in objective.lower():
        plan.append({
            "action": "write",
            "resource": "urn:li:dataset:(urn:li:dataPlatform:bigquery,ml.churn_predictions,PROD)",
        })
    return plan


def _spec_domains(agent_id: str, role: str) -> list[str]:
    from .registry import get_agent_spec

    try:
        return get_agent_spec(agent_id)["domains"]
    except KeyError:
        return {"analyst": ["Healthcare"], "engineer": ["Healthcare", "Finance", "ML"],
                "ml_engineer": ["ML", "Healthcare"], "guardian": []}.get(role, [])


def _llm_plan(agent_id: str, role: str, objective: str, entities: list[dict]) -> list[dict] | None:
    if not settings.llm_model:
        return None
    try:
        import litellm

        spec = _spec(agent_id, role)
        catalog = "\n".join(
            f"- URN {e['urn']} | name: {e.get('name', '')} | domain: {e.get('domain', '')} | "
            f"classification: {e.get('data_classification', 'public')}"
            for e in entities[:60]
        )
        system = (
            "You are the planner for a governed agent. The ONLY resources an agent "
            "may act on are the catalog items below; you MUST use the exact URN strings "
            "from that list and never invent or modify a URN.\n\n"
            "{catalog}\n\n"
            "Return ONLY a JSON array of actions, each "
            '{{"action": "<one of {tools}>", "resource": "<an exact catalog URN>"}}. '
            "Do not add commentary.".format(
                catalog=catalog, tools=", ".join(GATEWAY_TOOLS))
        )
        user = f"Agent role: {role}. Objective: {objective}. Tools: {spec['tools']}."
        resp = litellm.completion(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            api_base=settings.llm_base_url or None,
            api_key=settings.llm_api_key or None,
            temperature=settings.llm_temperature,
            timeout=30,
        )
        text = resp.choices[0].message.content or ""
        plan = _extract_json_array(text)
        return _validate_plan(plan, entities)
    except Exception:  # noqa: BLE001 — any LLM failure degrades to the rule engine
        return None


def _spec(agent_id: str, role: str) -> dict:
    from .registry import get_agent_spec

    try:
        return get_agent_spec(agent_id)
    except KeyError:
        return {"tools": GATEWAY_TOOLS, "domains": []}


def _extract_json_array(text: str) -> list | None:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _canonical_urn(resource: str, entities: list[dict]) -> str:
    """Resolve an LLM-returned resource to a real catalog URN.

    Exact URNs pass through; near-misses (e.g. an invented
    ``urn:catalog:data/marketing_campaign_attribution``) are matched back onto
    the catalog by entity name so the gateway only ever sees valid resources.
    """
    urns = {e["urn"] for e in entities}
    if resource in urns:
        return resource
    norm = re.sub(r"[_\-\s]", ".", resource.lower())
    for e in entities:
        name = re.sub(r"[_\-\s]", ".", str(e.get("name", "")).lower())
        if name and (name in norm or norm in name):
            return e["urn"]
    return ""


def _validate_plan(plan, entities: list[dict]) -> list[dict] | None:
    if not isinstance(plan, list) or not plan:
        return None
    out = []
    for step in plan[:6]:
        if not isinstance(step, dict):
            continue
        action = step.get("action", "")
        resource = step.get("resource", "")
        if action in GATEWAY_TOOLS and isinstance(resource, str) and resource:
            resource = _canonical_urn(resource, entities)
            if resource:
                out.append({"action": action, "resource": resource})
    return out or None


def build_plan(agent_id: str, role: str, objective: str, entities: list[dict]) -> tuple[list[dict], str]:
    """Build a governed action plan, preferring the LLM planner when configured.

    Returns ``(plan, source)`` where source is ``"llm"`` or ``"rule"``.
    """
    with _tracer("agents").start_as_current_span(
        "agents.plan", attributes={"agent.id": agent_id, "agent.role": role}
    ) as span:
        llm = _llm_plan(agent_id, role, objective, entities)
        plan = llm if llm else rule_based_plan(agent_id, role, objective, entities)
        source = "llm" if llm else "rule"
        span.set_attribute("plan.source", source)
        span.set_attribute("plan.actions", len(plan))
        return plan, source
