"""Python SDK for agents acting through the Agent Control Plane.

Agents use this SDK to onboard, sign requests with their Ed25519 identity, act
against the DataHub catalog through the gateway, and verify the audit chain.

Usage::

    from controlplane import ControlPlaneClient

    cp = ControlPlaneClient()                    # CONTROLPLANE_URL env, or default
    creds = cp.register("my-agent", ["Marketing"])          # keypair created
    creds.save("my-agent.json")                             # keep the private key safe

    cp = ControlPlaneClient.from_credentials("my-agent.json")
    result = cp.act("read", "urn:li:dataset:(...campaign_attribution...)")
    print(result["decision"], result.get("result"))
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def default_base_url() -> str:
    """Resolve the control plane URL from configuration (env first, then the
    documented default). Set CONTROLPLANE_URL to point at a different instance."""
    return os.environ.get("CONTROLPLANE_URL", "http://localhost:5186")


def _canonical_json(data) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class AgentCredentials:
    """Agent identity. The private key never leaves the agent."""

    def __init__(self, agent_id: str, private_key_pem: str, public_key_pem: str):
        self.agent_id = agent_id
        self.private_key_pem = private_key_pem
        self.public_key_pem = public_key_pem

    def sign(self, data: bytes) -> str:
        import base64

        private_key = serialization.load_pem_private_key(self.private_key_pem.encode(), password=None)
        return base64.urlsafe_b64encode(private_key.sign(data)).decode()

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "private_key": self.private_key_pem,
            "public_key": self.public_key_pem,
        }

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)
        os.chmod(path, 0o600)

    @classmethod
    def load(cls, path: str) -> "AgentCredentials":
        with open(path) as fh:
            data = json.load(fh)
        return cls(data["agent_id"], data["private_key"], data["public_key"])

    @classmethod
    def generate(cls, agent_id: str = "pending") -> "AgentCredentials":
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
        return cls(agent_id, private_pem, public_pem)


class ControlPlaneClient:
    def __init__(self, base_url: str | None = None, creds: AgentCredentials | None = None):
        self.base_url = (base_url or default_base_url()).rstrip("/")
        self.creds = creds

    @classmethod
    def from_credentials(cls, path: str, base_url: str | None = None) -> "ControlPlaneClient":
        return cls(base_url=base_url, creds=AgentCredentials.load(path))

    # -- lifecycle ---------------------------------------------------------

    def register(self, name: str, granted_domains: list[str], description: str = "") -> AgentCredentials:
        keys = AgentCredentials.generate()
        payload = {
            "name": name,
            "description": description,
            "public_key": keys.public_key_pem,
            "granted_domains": granted_domains,
        }
        resp = httpx.post(f"{self.base_url}/api/agents/register", json=payload, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        self.creds = AgentCredentials(body["id"], keys.private_key_pem, body["public_key"])
        return self.creds

    # -- gateway ------------------------------------------------------------

    def act(self, action_type: str, resource: str, delegation_token: str = "",
            target: dict | None = None) -> dict:
        """Submit a signed action request to the policy gateway."""
        if self.creds is None:
            raise RuntimeError("no credentials; register the agent or load credentials first")

        request_id = hashlib.sha256(
            f"{time.time_ns()}:{self.creds.agent_id}:{uuid.uuid4()}".encode()
        ).hexdigest()[:24]

        body = {
            "agent_id": self.creds.agent_id,
            "request_id": request_id,
            "action": {"type": action_type, "resource": resource},
            "target": target,
            "delegation_token": delegation_token,
        }
        signature = self.creds.sign(_canonical_json(body).encode())
        resp = httpx.post(
            f"{self.base_url}/api/requests/gateway",
            json=body,
            headers={"X-Agent-Signature": signature},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # -- delegation -----------------------------------------------------------

    def delegate(self, delegatee_id: str, scope: dict, max_depth: int = 1,
                 ttl_hours: float | None = None) -> dict:
        """Delegate a scoped capability to another agent, signed by this agent."""
        if self.creds is None:
            raise RuntimeError("no credentials")
        signed_payload = {
            "delegator_id": self.creds.agent_id,
            "delegatee_id": delegatee_id,
            "scope": scope,
            "max_depth": max_depth,
        }
        body = dict(signed_payload)
        body["ttl_hours"] = ttl_hours
        body["signature"] = self.creds.sign(_canonical_json(signed_payload).encode())
        resp = httpx.post(f"{self.base_url}/api/delegations", json=body, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # -- datahub ----------------------------------------------------------------

    def datahub_act(self, entity_urn: str, action_type: str, metadata: dict | None = None) -> dict:
        if self.creds is None:
            raise RuntimeError("no credentials")
        resp = httpx.post(
            f"{self.base_url}/api/datahub/actions",
            json={
                "agent_id": self.creds.agent_id,
                "entity_urn": entity_urn,
                "action_type": action_type,
                "metadata": metadata or {},
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def catalog(self, domain: str | None = None) -> list[dict]:
        params = {"domain": domain} if domain else {}
        resp = httpx.get(f"{self.base_url}/api/datahub/entities", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # -- audit ------------------------------------------------------------------

    def verify_chain(self) -> dict:
        resp = httpx.get(f"{self.base_url}/api/audit/verify/chain", timeout=10)
        resp.raise_for_status()
        return resp.json()
