"""Native policy engine.

Policies are stored as ordered JSON rules evaluated against a normalized input
object. The engine is default-deny (zero trust): a request is allowed only when
a matching ``allow`` rule is found and no ``deny`` rule matched first.

Evaluation order is deterministic by the policy ``order`` field.
"""

import json
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from . import models

TIER_ORDER = models.TIER_ORDER


@dataclass
class Decision:
    allow: bool
    reason: str
    policy_name: str = "default-deny"


def _tier_index(tier: str) -> int:
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else -1


def _resolve(path: str, data: dict):
    node = data
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return node


def _compare(op: str, actual, expected) -> bool:
    if op == "eq":
        return actual == expected
    if op == "neq":
        return actual != expected
    if op == "in":
        return actual in expected if isinstance(expected, list) else actual == expected
    if op == "not_in":
        return actual not in expected if isinstance(expected, list) else actual != expected
    if op == "exists":
        return actual is not None
    if op == "matches":
        return bool(re.search(str(expected), str(actual) if actual is not None else ""))
    if op == "is_true":
        return actual is True
    if op == "is_false":
        return actual is False
    # numeric / tier ordering
    if op in ("gt", "gte", "lt", "lte"):
        if actual is None:
            return False
        if str(actual) in TIER_ORDER or str(expected) in TIER_ORDER:
            left, right = _tier_index(str(actual)), _tier_index(str(expected))
        else:
            try:
                left, right = float(actual), float(expected)
            except (TypeError, ValueError):
                return False
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        return left <= right
    return False


def condition_matches(condition: dict, input_data: dict) -> bool:
    path = condition.get("path", "")
    op = condition.get("op", "eq")
    value = condition.get("value")
    ref = condition.get("ref")
    if ref:
        value = _resolve(ref, input_data)
    if condition.get("any"):
        return any(_compare(op, _resolve(p, input_data), value) for p in condition["any"])
    return _compare(op, _resolve(path, input_data), value)


def evaluate(
    db: Session,
    input_data: dict,
    enabled_only: bool = True,
    extra: dict | None = None,
) -> Decision:
    """Evaluate ``input_data`` against the policy set. First matching rule wins.

    ``extra`` merges additive context (e.g. lineage facts like
    ``upstream_restricted``) into the input under its own keys so policies can
    reference them without changing the core contract. It is empty by default,
    keeping existing callers unchanged.
    """
    if extra:
        input_data = {**input_data, **extra}
    query = db.query(models.Policy).order_by(models.Policy.order.asc())
    if enabled_only:
        query = query.filter(models.Policy.enabled.is_(True))

    for policy in query.all():
        actions = json.loads(policy.actions or "[]")
        action_type = (input_data.get("action") or {}).get("type")
        if actions and action_type not in actions:
            continue
        conditions = json.loads(policy.conditions or "[]")
        if conditions and not all(condition_matches(c, input_data) for c in conditions):
            continue
        allow = policy.effect == "allow"
        return Decision(allow=allow, reason=policy.name, policy_name=policy.name)

    return Decision(allow=False, reason="no matching policy (default deny)", policy_name="default-deny")
