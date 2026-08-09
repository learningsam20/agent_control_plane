import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .config import get_settings


def generate_keypair() -> tuple[str, str]:
    """Generate an Ed25519 keypair. Returns (private_key_pem, public_key_pem)."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def canonical_json(data) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign(private_key_pem: str, data: bytes) -> str:
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    signature = private_key.sign(data)
    return base64.urlsafe_b64encode(signature).decode()


def verify(public_key_pem: str, signature_b64: str, data: bytes) -> bool:
    """Verify an Ed25519 signature. Returns True when valid, False otherwise."""
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode())
        signature = base64.urlsafe_b64decode(signature_b64)
        public_key.verify(signature, data)
        return True
    except InvalidSignature:
        return False
    except Exception:  # noqa: BLE001
        return False


def create_access_token(agent_id: str) -> str:
    settings = get_settings()
    payload = {
        "sub": agent_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.token_algorithm)


def decode_access_token(token: str) -> str | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.token_algorithm])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
