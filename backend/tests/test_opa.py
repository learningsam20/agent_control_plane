"""Unit tests for the Open Policy Agent adapter.

Exercises the Rego input contract mapping, verbatim policy push (no package
double-wrapping), and decision parsing without requiring a live OPA server.
"""

import httpx
import pytest

from app import opa as opa_mod
from app.opa import build_opa_input


def test_build_opa_input_maps_native_contract():
    native = {
        "agent": {"id": "ag_1", "reputation_tier": "elevated", "trust_score": 5,
                  "status": "active", "granted_domains": ["Marketing", "Sales"]},
        "action": {"type": "read", "resource": "urn:li:dataset:(...)"},
        "target": {"entity_type": "dataset", "domain": "Marketing",
                   "data_classification": "sensitive", "owner_team": "growth"},
        "delegation": {"active": True, "depth": 1, "max_depth": 2, "delegator_id": "ag_0",
                       "dataset_scope_match": True, "action_in_scope": True},
    }
    out = build_opa_input(native)
    # Rego contract: plain action string + numeric tier rank
    assert out["action"] == "read"
    assert out["agent"]["reputation_tier"] == "elevated"
    assert out["agent"]["reputation_tier_rank"] == 2  # TIER_ORDER index
    assert out["agent"]["granted_domains"] == ["Marketing", "Sales"]
    assert out["target"]["domain"] == "Marketing"
    assert out["target"]["urn"].startswith("urn:li:")
    assert out["delegation"] == {
        "active": True, "depth": 1, "max_depth": 2,
        "dataset_scope_match": True, "action_in_scope": True,
    }


def test_build_opa_input_unknown_tier_fails_closed():
    out = build_opa_input({
        "agent": {"reputation_tier": "superuser"},
        "action": {"type": "read"},
        "target": {},
        "delegation": {},
    })
    assert out["agent"]["reputation_tier_rank"] == 0
    assert out["delegation"]["action_in_scope"] is False


def test_opa_evaluate_parses_decision(monkeypatch):
    def fake_post(url, json=None, timeout=5):
        assert url.endswith("/v1/data/controlplane")
        assert json["input"] == {"action": "read"}
        return _FakeResp(200, {"result": {"allow": True, "allow_rule": {"allow-read-sensitive": True}}})

    monkeypatch.setattr(opa_mod.httpx, "post", fake_post)
    decision = opa_mod.evaluate({"action": "read"}, name="controlplane")
    assert decision is not None
    assert decision.allow is True
    assert decision.reason == "allow-read-sensitive"
    assert decision.policy_name == "opa"


def test_opa_evaluate_deny_reason_joined(monkeypatch):
    def fake_post(url, json=None, timeout=5):
        return _FakeResp(200, {"result": {
            "allow": False,
            "deny_reason": {"domain not in agent grants and no dataset-scoped delegation": True},
        }})

    monkeypatch.setattr(opa_mod.httpx, "post", fake_post)
    decision = opa_mod.evaluate({}, name="controlplane")
    assert decision.allow is False
    assert decision.reason == "domain not in agent grants and no dataset-scoped delegation"


def test_opa_evaluate_falls_back_on_error(monkeypatch):
    def fake_post(url, json=None, timeout=5):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(opa_mod.httpx, "post", fake_post)
    assert opa_mod.evaluate({"action": "read"}, name="controlplane") is None


def test_opa_push_policy_is_verbatim(monkeypatch):
    sent = {}

    def fake_put(url, json=None, timeout=5):
        assert url.endswith("/v1/policies/controlplane")
        sent["body"] = json
        return _FakeResp(201)

    monkeypatch.setattr(opa_mod.httpx, "put", fake_put)
    rego = "package controlplane\n\nallow := true\n"
    assert opa_mod.push_policy(rego, name="controlplane") is True
    assert sent["body"]["policy"] == rego  # no package double-wrapping


def test_opa_engine_choice(monkeypatch):
    from app.config import Settings

    monkeypatch.setattr(opa_mod, "available", lambda: False)
    monkeypatch.setattr(opa_mod, "settings", Settings(
        _env_file=None, policy_engine="auto", opa_url="http://localhost:8181"))
    assert opa_mod.engine_choice() == "native"  # auto falls back when OPA is down

    monkeypatch.setattr(opa_mod, "settings", Settings(
        _env_file=None, policy_engine="opa", opa_url=""))
    assert opa_mod.engine_choice() == "opa"

    monkeypatch.setattr(opa_mod, "available", lambda: True)
    monkeypatch.setattr(opa_mod, "settings", Settings(
        _env_file=None, policy_engine="auto", opa_url="http://localhost:8181"))
    assert opa_mod.engine_choice() == "opa"  # auto prefers OPA when reachable


class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _restore_settings():
    """Guard against leaking monkeypatched module settings into other tests."""
    original = opa_mod.settings
    yield
    opa_mod.settings = original
