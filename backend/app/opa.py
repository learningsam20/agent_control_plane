"""Optional Open Policy Agent (OPA) adapter.

When an OPA server is reachable the control plane pushes its Rego policy bundle
and evaluates requests there; otherwise it transparently falls back to the
native engine so the platform works offline.

The bundled Rego module (``policies/datahub.rego``) declares
``package controlplane`` and exposes ``data.controlplane.allow`` plus the
matched rule names in the ``allow_rule`` / ``deny_reason`` partial sets. The
adapter queries that data path and maps the native policy input onto the Rego
query contract (plain ``action`` string, numeric ``reputation_tier_rank``,
explicit ``delegation.action_in_scope``).
"""

from pathlib import Path

import httpx

from . import models
from .config import get_settings
from .policy import Decision

settings = get_settings()


def _policy_path() -> Path:
    """Resolve the bundled Rego module (config override, else repo policies/)."""
    if settings.opa_policy_file:
        return Path(settings.opa_policy_file)
    return Path(__file__).resolve().parents[2] / "policies" / "datahub.rego"


def load_rego() -> str:
    return _policy_path().read_text()


def available() -> bool:
    if not settings.opa_url:
        return False
    try:
        resp = httpx.get(f"{settings.opa_url}/v1/policies", timeout=1.5)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def push_policy(rego: str, name: str | None = None) -> bool:
    """Push a Rego module to OPA. The module declares its own package, so it is
    uploaded verbatim under the configured policy id.

    OPA <1.x accepts a JSON body ``{"policy": ...}`` while OPA 1.x expects the
    raw Rego module as ``text/plain``; try both and accept either.
    """
    name = name or settings.opa_policy_name
    url = f"{settings.opa_url}/v1/policies/{name}"
    try:
        resp = httpx.put(url, json={"policy": rego}, timeout=5)
        if resp.status_code in (200, 201):
            return True
        resp = httpx.put(url, content=rego,
                         headers={"Content-Type": "text/plain"}, timeout=5)
        return resp.status_code in (200, 201)
    except httpx.HTTPError:
        return False


def push_policy_file(path: str | None = None) -> bool:
    """Push the bundled Rego module (or an explicit file) to OPA."""
    if path:
        rego = Path(path).read_text()
    else:
        rego = load_rego()
    return push_policy(rego)


def build_opa_input(input_data: dict) -> dict:
    """Map the native policy input to the Rego query contract.

    The native engine treats ``input.action`` as a dict and compares tiers as
    strings; the Rego contract expects a plain action string, numeric tier
    ranks, and an explicit delegation action-scope flag.
    """
    agent = input_data.get("agent") or {}
    action = input_data.get("action") or {}
    target = input_data.get("target") or {}
    delegation = input_data.get("delegation") or {}
    tier = agent.get("reputation_tier", "untrusted")
    rank = models.TIER_ORDER.index(tier) if tier in models.TIER_ORDER else 0
    return {
        "agent": {
            "id": agent.get("id", ""),
            "status": agent.get("status", "active"),
            "reputation_tier": tier,
            "reputation_tier_rank": rank,
            "granted_domains": agent.get("granted_domains", []),
        },
        "action": action.get("type", ""),
        "target": {
            "urn": action.get("resource", ""),
            "domain": target.get("domain", ""),
            "data_classification": target.get("data_classification", "public"),
        },
        "delegation": {
            "active": bool(delegation.get("active")),
            "depth": delegation.get("depth", 0),
            "max_depth": delegation.get("max_depth", 0),
            "dataset_scope_match": bool(delegation.get("dataset_scope_match")),
            "action_in_scope": bool(delegation.get("action_in_scope")),
        },
    }


def evaluate(input_data: dict, name: str | None = None) -> Decision | None:
    """Evaluate an input against the OPA policy.

    Returns a ``Decision`` or None when OPA is unavailable / errored so callers
    can transparently fall back to the native engine.

    The Rego module exposes the matched rule names as partial sets
    (``allow_rule`` / ``deny_reason``, serialized as JSON objects); the reason
    string is derived here rather than inside Rego for OPA 1.x portability.
    """
    name = name or settings.opa_policy_name
    try:
        resp = httpx.post(
            f"{settings.opa_url}/v1/data/{name}",
            json={"input": input_data},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json().get("result", {})
        if isinstance(data, dict) and "allow" in data:
            allow = bool(data.get("allow", False))
            if allow:
                allowed_rules = list((data.get("allow_rule") or {}).keys())
                reason = allowed_rules[0] if allowed_rules else "opa"
            else:
                deny_reasons = list((data.get("deny_reason") or {}).keys())
                reason = ", ".join(deny_reasons) or "no matching policy (default deny)"
            return Decision(allow=allow, reason=reason, policy_name="opa")
        return None
    except httpx.HTTPError:
        return None


def engine_choice() -> str:
    """Resolve the configured engine mode to an actual engine: 'native' or 'opa'."""
    mode = settings.policy_engine
    if mode == "native":
        return "native"
    if mode == "opa":
        return "opa"
    return "opa" if available() else "native"
