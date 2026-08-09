# Agent Control Plane — OPA (Rego) policy set
#
# Native (Python) mirror of the seed policies, expressed for an Open Policy
# Agent sidecar. The control plane auto-detects OPA at
# CONTROLPLANE_OPA_URL (default http://localhost:8181) and falls back to the
# native engine when OPA is unreachable.
#
# Query contract:  POST /v1/data/controlplane with input
#
#   {
#     "agent": {
#       "id": ..., "status": "active",
#       "reputation_tier": "standard",
#       "reputation_tier_rank": 1,
#       "granted_domains": ["Marketing", "Sales"]
#     },
#     "action": "read",
#     "target": {
#       "urn": ..., "domain": "Finance",
#       "data_classification": "restricted"
#     },
#     "delegation": {
#       "active": false, "depth": 0, "max_depth": 0,
#       "dataset_scope_match": false, "action_in_scope": false
#     }
#   }
#
# Decision: data.controlplane.allow is true only when an allow rule matched and
# no deny rule matched (zero trust, default deny). The matched rule names are
# surfaced in `allow_rule` / `deny_reason` for audit; the control plane adapter
# derives the human-readable reason from those sets.
#
# NOTE: this module targets a Rego subset (no `else` chains, no extraction of a
# single element out of a partial set) that is accepted by both classic OPA and
# OPA 1.x so the bundled policy stays portable.

package controlplane

import future.keywords.if
import future.keywords.in

default allow := false

# --- deny rules (partial set; any match denies) ---

# deny-inactive-agents: zero-trust guardrail. Inactive agents never act.
deny_reason["agent.status not active"] if {
    input.agent.status != "active"
}

# deny-delegation-depth-exceeded
deny_reason["delegation depth exceeded"] if {
    input.delegation.active
    input.delegation.depth >= input.delegation.max_depth
}

# deny-outside-granted-domains
deny_reason["domain not in agent grants and no dataset-scoped delegation"] if {
    not input.target.domain in input.agent.granted_domains
    not input.delegation.dataset_scope_match
}

# deny action outside delegated scope
deny_reason["action outside delegated scope"] if {
    input.delegation.active
    not input.delegation.action_in_scope
}

any_deny_reason if deny_reason[_]

# --- allow rules (partial set; ordered by seed policy order) ---

# allow-read-sensitive (order 40)
allow_rule["allow-read-sensitive"] if {
    input.action in {"read", "query"}
    input.agent.reputation_tier_rank >= 1            # standard
    input.target.data_classification in {"public", "sensitive"}
    not any_deny_reason
}

# allow-transform-elevated (order 50)
allow_rule["allow-transform-elevated"] if {
    input.action == "transform"
    input.agent.reputation_tier_rank >= 2            # elevated
    input.target.data_classification in {"public", "sensitive"}
    not any_deny_reason
}

# allow-write-elevated (order 60)
allow_rule["allow-write-elevated"] if {
    input.action in {"write", "ingest"}
    input.agent.reputation_tier_rank >= 2            # elevated
    input.target.data_classification in {"public", "sensitive"}
    not any_deny_reason
}

# allow-restricted-write-privileged (order 70)
allow_rule["allow-restricted-write-privileged"] if {
    input.action in {"read", "query", "write", "transform", "ingest"}
    input.agent.reputation_tier_rank >= 3            # privileged
    input.target.data_classification == "restricted"
    not any_deny_reason
}

# Iterate (never index) the sets: a defined-but-empty set is truthy in Rego,
# and single-element extraction from a partial set is not portable across OPA
# 1.x. Membership iteration succeeds only when a rule actually matched.
allow if allow_rule[_]
