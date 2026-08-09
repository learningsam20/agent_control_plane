"""LangGraph workflow for governed agents.

Graph: ``planner → executor → summarizer``. The planner turns the objective
into a plan; the executor runs each action through the governed toolset (the
control-plane gateway); the summarizer writes the run outcome. The graph is
checkpointed with a MemorySaver so runs can be inspected/resumed by thread_id.
"""

from __future__ import annotations

from typing import Annotated, TypedDict, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from app.telemetry import meter as _meter, tracer as _tracer

from .planner import build_plan
from .tools import GovernedToolSet

_MAX_ACTIONS = 6


class AgentState(TypedDict, total=False):
    agent_id: str
    role: str
    objective: str
    plan: list[dict]
    plan_source: str
    results: list[dict]
    summary: str
    denied: bool


def _planner_node(tools: GovernedToolSet):
    def planner(state: AgentState) -> AgentState:
        entities = tools.catalog_fn()
        plan, source = build_plan(state["agent_id"], state.get("role", ""),
                                  state["objective"], entities)
        return {"plan": plan[: _MAX_ACTIONS], "plan_source": source,
                "results": [], "denied": False}

    return planner


def _executor_node(tools: GovernedToolSet):
    def executor(state: AgentState) -> AgentState:
        results = []
        denied = False
        with _tracer("agents").start_as_current_span(
            "agents.execute", attributes={"agent.id": state["agent_id"]}
        ):
            for step in state.get("plan", []):
                action = step["action"]
                resource = step["resource"]
                try:
                    resp = tools.call(action, resource)
                    entry = {
                        "action": action,
                        "resource": resource,
                        "decision": resp.get("decision", "deny"),
                        "reason": resp.get("reason", ""),
                        "policy": resp.get("policy_name", ""),
                        "audit_seq": resp.get("audit_seq"),
                        "result": resp.get("result"),
                    }
                except Exception as exc:  # noqa: BLE001
                    entry = {
                        "action": action,
                        "resource": resource,
                        "decision": "failed",
                        "reason": f"tool error: {exc}",
                        "policy": "",
                        "audit_seq": None,
                        "result": None,
                    }
                results.append(entry)
                if entry["decision"] != "allow":
                    denied = True
        return {"results": results, "denied": denied}

    return executor


def _summarizer_node(state: AgentState) -> AgentState:
    results = state.get("results", [])
    allowed = sum(1 for r in results if r.get("decision") == "allow")
    denied_count = sum(1 for r in results if r.get("decision") == "deny")
    failed = sum(1 for r in results if r.get("decision") == "failed")

    if not results:
        summary = "No actions planned."
    else:
        source = state.get("plan_source", "rule")
        lines = [f"[planner: {source}] Plan executed: {len(results)} action(s), "
                 f"{allowed} allowed, {denied_count} denied, {failed} failed."]
        for r in results:
            status = {"allow": "allowed", "deny": "DENIED", "failed": "FAILED"}.get(
                r["decision"], r["decision"]
            )
            lines.append(f"  · {r['action']} {r['resource']} → {status} "
                         f"({r.get('policy') or r.get('reason') or ''})")
        summary = "\n".join(lines)
    return {"summary": summary}


def build_workflow(tools: GovernedToolSet):
    """Build (and compile) the governed agent graph for a given toolset."""
    graph = StateGraph(AgentState)
    graph.add_node("planner", _planner_node(tools))
    graph.add_node("executor", _executor_node(tools))
    graph.add_node("summarizer", _summarizer_node)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "summarizer")
    graph.add_edge("summarizer", END)
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


def run_graph(tools: GovernedToolSet, agent_id: str, role: str, objective: str,
              thread_id: str) -> dict:
    """Invoke the governed graph once and return the final state."""
    app = build_workflow(tools)
    state = app.invoke(
        {"agent_id": agent_id, "role": role, "objective": objective},
        config={"configurable": {"thread_id": thread_id}},
    )
    return state
