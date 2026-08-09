"""Governed LangGraph agents.

Agents are normal LangGraph/LangChain agents whose every tool call goes through
the control plane gateway as a signed action request. The control plane decides
allow/deny, audits, and feeds reputation; the agent only executes within the
governed envelope.
"""

from .registry import get_agent_spec, GOVERNED_AGENTS, load_demo_credentials
from .runner import execute_run

__all__ = ["GOVERNED_AGENTS", "get_agent_spec", "load_demo_credentials", "execute_run"]
