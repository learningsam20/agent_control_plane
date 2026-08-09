from datetime import timedelta

from .util import utcnow

from sqlalchemy.orm import Session

from . import models
from .config import get_settings
from .security import canonical_json, digest, sign, verify

settings = get_settings()


def _delegation_proof_token(delegator_id: str, delegatee_id: str, scope: dict,
                            max_depth: int, nonce: str) -> str:
    payload = canonical_json(
        {"delegator": delegator_id, "delegatee": delegatee_id,
         "scope": scope, "max_depth": max_depth, "nonce": nonce}
    )
    return digest(payload.encode())


def _inherited_depth(db: Session, delegator_id: str) -> tuple[int, int | None]:
    """If the delegator is themselves acting under a delegation (transitive
    delegation), the new delegation inherits the chain depth and a tighter
    max depth so authority cannot be extended beyond the original grant.
    """
    parent = (
        db.query(models.Delegation)
        .filter(
            models.Delegation.delegatee_id == delegator_id,
            models.Delegation.active.is_(True),
            (models.Delegation.expires_at.is_(None) | (models.Delegation.expires_at > utcnow())),
        )
        .order_by(models.Delegation.issued_at.desc())
        .first()
    )
    if parent is None:
        return 0, None
    return parent.depth + 1, parent.max_depth


def issue(
    db: Session,
    delegator: models.Agent,
    delegatee: models.Agent,
    scope: dict,
    max_depth: int,
    ttl_hours: float | None = None,
    signature: str = "",
) -> models.Delegation:
    """Issue a scoped delegation from ``delegator`` to ``delegatee``.

    The delegation is anchored to the delegator via an Ed25519 signature over a
    canonical description of the delegation, producing a verifiable proof token.
    """
    if delegator.status != "active":
        raise ValueError("delegator agent is not active")
    if delegatee.status != "active":
        raise ValueError("delegatee agent is not active")
    if delegator.id == delegatee.id:
        raise ValueError("an agent cannot delegate to itself")

    # Scope validation
    allowed_actions = scope.get("actions", [])
    if not isinstance(allowed_actions, list) or not allowed_actions:
        raise ValueError("delegation scope must list at least one action type")
    if any(a not in models.ACTION_TYPES for a in allowed_actions):
        raise ValueError("delegation scope contains unknown action type")

    depth, inherited_max_depth = _inherited_depth(db, delegator.id)
    if inherited_max_depth is not None:
        max_depth = min(max_depth, inherited_max_depth)
        if depth >= max_depth:
            raise ValueError(
                f"delegation depth {depth} already reaches the authorized chain limit {max_depth}"
            )

    nonce = digest(f"{utcnow().timestamp()}:{delegator.id}:{delegatee.id}".encode())
    proof = _delegation_proof_token(delegator.id, delegatee.id, scope, max_depth, nonce)

    # The delegator signs the canonical delegation grant (identity, scope, depth);
    # the control plane verifies it against the delegator's public key.
    canonical = canonical_json({
        "delegator_id": delegator.id,
        "delegatee_id": delegatee.id,
        "scope": scope,
        "max_depth": max_depth,
    })
    if signature and not verify(delegator.public_key, signature, canonical.encode()):
        raise ValueError("delegator signature is invalid")

    expires_at = None
    if ttl_hours:
        expires_at = utcnow() + timedelta(hours=ttl_hours)

    delegation = models.Delegation(
        id=f"dlg-{nonce[:12]}",
        delegator_id=delegator.id,
        delegatee_id=delegatee.id,
        scope=canonical_json(scope),
        max_depth=max_depth,
        depth=depth,
        active=True,
        token=proof,
        expires_at=expires_at,
    )
    db.add(delegation)
    db.flush()
    return delegation


def resolve(db: Session, token: str, agent_id: str) -> models.Delegation | None:
    """Resolve an active delegation token for a given acting agent."""
    delegation = (
        db.query(models.Delegation)
        .filter(models.Delegation.token == token, models.Delegation.delegatee_id == agent_id)
        .first()
    )
    if delegation is None or not delegation.active:
        return None
    if delegation.expires_at and delegation.expires_at < utcnow():
        return None
    if delegation.revoked_at:
        return None
    return delegation


def status_of(delegation: models.Delegation) -> str:
    """Effective token validity — the same rule ``resolve`` applies.

    ``active`` only means the row was not explicitly revoked; the *effective*
    status also accounts for expiry, which is what the gateway enforces.
    """
    if delegation.revoked_at or not delegation.active:
        return "revoked"
    if delegation.expires_at and delegation.expires_at < utcnow():
        return "expired"
    return "active"


def scope_matches(delegation: models.Delegation, action_type: str, resource: str,
                  domain: str = "") -> bool:
    import json

    scope = json.loads(delegation.scope)
    actions = scope.get("actions", [])
    datasets = scope.get("datasets", [])
    domains = scope.get("domains", [])
    if action_type not in actions:
        return False
    if datasets and resource not in datasets:
        return False
    if domains and domain and domain not in domains:
        return False
    return True


def revoke(db: Session, delegation: models.Delegation) -> models.Delegation:
    delegation.active = False
    delegation.revoked_at = utcnow()
    return delegation
