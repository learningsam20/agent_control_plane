"""Agents worker: executes pending agent runs as a real agent runtime.

The worker is a separate process from the control plane. It claims pending runs
from the API, then drives the LangGraph agent with genuine Ed25519-signed HTTP
requests to the gateway — the private key lives in the agent runtime, and the
control plane only ever sees signed envelopes.

Run: ``cd backend && python3 -m agents.worker``  (``--once`` for a single poll)
"""

from __future__ import annotations

import sys
import time

import httpx

from app.config import get_settings
from app.telemetry import emit_event, emit_log, init_telemetry

from .runner import execute_run

settings = get_settings()

POLL_INTERVAL = settings.worker_poll_interval
WORKER_NAME = settings.worker_name


def claim_and_run(base_url: str, worker: str = WORKER_NAME) -> int:
    """Claim and execute every currently-pending run. Returns how many ran."""
    pending = httpx.get(f"{base_url}/api/runs/pending", timeout=10).json()
    ran = 0
    for run in pending:
        run_id = run["id"]
        claim = httpx.post(f"{base_url}/api/runs/{run_id}/claim",
                           json={"worker": worker}, timeout=10)
        if claim.status_code >= 400:
            emit_log("agents-worker", "claim rejected", level="WARN",
                     run_id=run_id, status_code=claim.status_code)
            continue
        emit_event("agents-worker", "agent.run.claimed",
                   run_id=run_id, agent_id=run["agent_id"], worker=worker)
        try:
            result = execute_run(run["agent_id"], run["objective"],
                                 run_id=run_id, mode="http")
            status = result["status"] if result["status"] in ("succeeded", "denied") else "failed"
            payload = {
                "status": status,
                "plan": result["plan"],
                "results": result["results"],
                "summary": result["summary"],
            }
        except Exception as exc:  # noqa: BLE001
            emit_log("agents-worker", "run execution failed", level="ERROR",
                     run_id=run_id, agent_id=run["agent_id"], error=str(exc))
            payload = {
                "status": "failed",
                "plan": [],
                "results": [],
                "summary": f"run failed: {exc}",
            }
        complete = httpx.post(f"{base_url}/api/runs/{run_id}/complete",
                              json=payload, timeout=10)
        if complete.status_code < 400:
            print(f"[{worker}] run {run_id} ({run['agent_id']}) → {payload['status']}")
            emit_event("agents-worker", f"agent.run.{payload['status']}",
                       run_id=run_id, agent_id=run["agent_id"])
            ran += 1
        else:
            print(f"[{worker}] run {run_id} could not be completed: {complete.text}")
            emit_log("agents-worker", "run completion failed", level="ERROR",
                     run_id=run_id, status_code=complete.status_code)
    return ran


def main(interval: float = POLL_INTERVAL, once: bool = False) -> None:
    init_telemetry("agents-worker")
    base_url = get_settings().self_url.rstrip("/")
    print(f"[{WORKER_NAME}] polling {base_url}/api/runs/pending "
          f"(interval {interval}s)")
    emit_log("agents-worker", "worker started", level="INFO",
             base_url=base_url, interval=interval)
    while True:
        try:
            claim_and_run(base_url)
        except Exception as exc:  # noqa: BLE001
            print(f"[{WORKER_NAME}] poll error: {exc}")
            emit_log("agents-worker", "poll error", level="ERROR", error=str(exc))
        if once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    once = "--once" in sys.argv[1:]
    main(once=once)
