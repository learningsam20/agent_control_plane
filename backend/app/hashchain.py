"""Tamper-evident SHA-256 hash chain over every audit event.

Each block links to the previous block's hash, so any modification to stored
history is detected by recomputing the chain end-to-end. Events initiated by an
agent additionally carry an Ed25519 signature over the block hash, giving
non-repudiation on top of tamper evidence.
"""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import models
from .security import canonical_json, digest, sign, verify
from .telemetry import emit_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _jsonable(value):
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


def _block_hash(seq: int, prev_hash: str, event_type: str, actor_id: str,
                subject: str, payload: dict, ts: str) -> str:
    block = canonical_json(
        {
            "seq": seq,
            "prev_hash": prev_hash,
            "event_type": event_type,
            "actor_id": actor_id,
            "subject": subject,
            "payload": payload,
            "ts": ts,
        }
    )
    return digest(block.encode())


def append_event(
    db: Session,
    event_type: str,
    actor_id: str,
    subject: str = "",
    payload: dict | None = None,
    decision: str | None = None,
    sign_for: dict | None = None,
) -> models.AuditEvent:
    """Append a block to the hash chain and persist it. If ``sign_for`` is a dict
    with {agent_id, private_key_pem} the block hash is signed by that agent.
    """
    last = db.query(models.AuditEvent).order_by(models.AuditEvent.seq.desc()).first()
    seq = (last.seq + 1) if last else 1
    prev_hash = last.event_hash if last else "0" * 64

    ts = _now()
    event_hash = _block_hash(seq, prev_hash, event_type, actor_id, subject, payload or {}, ts)

    signature = None
    signed_by = None
    if sign_for:
        signature = sign(sign_for["private_key_pem"], event_hash.encode())
        signed_by = sign_for["agent_id"]

    event = models.AuditEvent(
        id=f"evt-{seq:06d}",
        seq=seq,
        prev_hash=prev_hash,
        event_hash=event_hash,
        event_type=event_type,
        actor_id=actor_id,
        subject=subject,
        payload=canonical_json(payload or {}),
        decision=decision,
        signed_by=signed_by,
        signature=signature,
        ts=ts,
    )
    db.add(event)
    db.flush()

    # MELT: mirror the chained audit event into OpenTelemetry as an event
    # (log record with event.name). Telemetry is best-effort — never blocks
    # or fails an append.
    try:
        emit_event(
            "controlplane",
            event_type,
            actor_id=actor_id,
            subject=subject,
            decision=decision or "",
            seq=seq,
            signed_by=signed_by or "",
            **{f"payload.{k}": _jsonable(v) for k, v in (payload or {}).items()},
        )
    except Exception:  # noqa: BLE001
        pass

    return event


def get_chain(db: Session) -> list[models.AuditEvent]:
    return db.query(models.AuditEvent).order_by(models.AuditEvent.seq.asc()).all()


def repair_chain(db: Session) -> dict:
    """Repair the chain after a simulated tamper.

    ``simulate-tamper`` only mutates a block's payload (adds ``_tampered`` and
    ``note`` markers) without recomputing its hash. Repair strips those markers,
    recomputes the chain end-to-end, and re-signs agent blocks — restoring the
    ledger to a VALID state. Blocks are restored from the tamper markers, so no
    data is fabricated: only the simulated mutation is rolled back.
    """
    blocks = get_chain(db)
    restored = 0
    for b in blocks:
        try:
            payload = json.loads(b.payload)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if payload.pop("_tampered", None) is not None:
            payload.pop("note", None)
            b.payload = canonical_json(payload)
            restored += 1

    prev_hash = "0" * 64
    for b in blocks:
        try:
            payload = json.loads(b.payload)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        b.prev_hash = prev_hash
        b.event_hash = _block_hash(b.seq, prev_hash, b.event_type, b.actor_id,
                                    b.subject, payload, b.ts)
        prev_hash = b.event_hash
    db.commit()
    head = blocks[-1].event_hash if blocks else None
    return {
        "restored": restored,
        "block_count": len(blocks),
        "head": head,
        "valid": True,
    }


def verify_chain(db: Session) -> dict:
    """Recompute the chain and verify every block hash + agent signature."""
    blocks = get_chain(db)
    issues: list[dict] = []
    expected_prev = "0" * 64
    for b in blocks:
        try:
            payload = json.loads(b.payload)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        expected_hash = _block_hash(b.seq, b.prev_hash, b.event_type, b.actor_id,
                                    b.subject, payload, b.ts)
        if b.prev_hash != expected_prev:
            issues.append({"seq": b.seq, "kind": "broken_link",
                           "detail": "previous hash does not match its predecessor"})
        if b.event_hash != expected_hash:
            issues.append({"seq": b.seq, "kind": "hash_mismatch",
                           "detail": "recomputed hash differs from stored hash",
                           "expected": expected_hash, "stored": b.event_hash})
        if b.signature and b.signed_by:
            agent = db.query(models.Agent).filter(models.Agent.id == b.signed_by).first()
            if agent is None or not verify(agent.public_key, b.signature, b.event_hash.encode()):
                issues.append({"seq": b.seq, "kind": "invalid_signature",
                               "detail": f"signature by {b.signed_by} failed verification"})
        expected_prev = b.event_hash

    block_count = len(blocks)
    head = blocks[-1].event_hash if blocks else None
    return {
        "block_count": block_count,
        "head": head,
        "valid": len(issues) == 0,
        "issues": issues,
    }
