"""Optional DataHub analytics agent (Talk-to-Data) client.

When ``USE_ANALYTICS_AGENT`` is enabled the control plane can answer
natural-language analytics questions by calling a running
``datahub-analytics-agent`` service (default http://localhost:8100). The agent
writes SQL, runs it against its connected engines, and returns text + optional
charts via a Server-Sent-Events stream.

The analytics agent is a separate deployable service (PyPI ``datahub-analytics-agent``),
not a library — this module talks to its REST + SSE API:
  POST /api/conversations                       -> {id, ...}
  POST /api/conversations/{id}/messages  {text} -> SSE stream
"""

from __future__ import annotations

import json
import re
import uuid

import httpx

from ..config import get_settings

settings = get_settings()


class AnalyticsAgentError(RuntimeError):
    pass


class AnalyticsAgentClient:
    def __init__(self, url: str | None = None, engine: str | None = None):
        self.url = (url or settings.analytics_agent_url).rstrip("/")
        self.engine = engine if engine is not None else settings.analytics_agent_engine

    @property
    def enabled(self) -> bool:
        return bool(settings.use_analytics_agent) and bool(self.url)

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "Accept": "text/event-stream"}

    def ask(self, question: str, engine: str | None = None) -> dict:
        """Answer a natural-language analytics question.

        Returns ``{conversation_id, answer, sql, chart, events}`` where
        ``answer`` is the final assistant text and ``sql``/``chart`` are the
        most recent ones produced during the run (when available).
        """
        if not self.enabled:
            raise AnalyticsAgentError("analytics agent is not enabled (USE_ANALYTICS_AGENT)")
        engine = engine or self.engine or "default"
        try:
            conv = httpx.post(
                f"{self.url}/api/conversations",
                json={"title": question[:60], "engine_name": engine},
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            conv.raise_for_status()
            conversation_id = conv.json().get("id") or str(uuid.uuid4())

            resp = httpx.post(
                f"{self.url}/api/conversations/{conversation_id}/messages",
                json={"text": question},
                headers=self._headers(),
                timeout=120,
            )
            resp.raise_for_status()
            return {
                "conversation_id": conversation_id,
                **_parse_sse(resp.text),
            }
        except httpx.HTTPError as exc:
            raise AnalyticsAgentError(f"analytics agent request failed: {exc}") from exc


def _parse_sse(raw: str) -> dict:
    """Parse the analytics agent SSE stream into answer / sql / chart / events."""
    text_parts: list[str] = []
    sql: str | None = None
    chart: dict | None = None
    events: list[str] = []
    event_name = ""
    data_buf: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_buf
        if not event_name:
            return
        data = "\n".join(data_buf)
        events.append(event_name)
        try:
            payload = json.loads(data) if data else {}
        except (TypeError, ValueError):
            payload = {"text": data}
        if event_name == "TEXT":
            text_parts.append(payload.get("text") or "")
        elif event_name == "SQL":
            sql = payload.get("sql") or payload.get("text") or ""
        elif event_name == "CHART":
            chart = payload
        event_name = ""
        data_buf = []

    for line in raw.splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_buf.append(line[5:].strip())
        elif line == "":
            flush()
    flush()

    answer = re.sub(r"\n{3,}", "\n\n", "\n".join(part.strip() for part in text_parts)).strip()
    if not answer and sql:
        answer = f"Generated SQL:\n{sql}"
    return {"answer": answer, "sql": sql, "chart": chart, "events": events}


def get_analytics_client() -> AnalyticsAgentClient:
    return AnalyticsAgentClient()
